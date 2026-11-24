"""
DEMO PROJECT - Production-style streaming LLM API backend (FastAPI).

  POST /v1/chat  -> Server-Sent Events stream of model output (or one JSON response)
  GET  /health   -> liveness
  GET  /metrics  -> request counts, errors, average time-to-first-token

Production concerns covered:
  * streaming with SSE, request IDs on every response (X-Request-ID)
  * a background log writer fed by a BOUNDED queue (backpressure, nothing dropped):
    chunked output is aggregated into one JSON line per request in logs/requests.jsonl
  * OpenTelemetry tracing: one span per request with TTFT, chunk count, status
  * clean error handling: provider failures become an SSE `error` event + logged status

Providers:
  * AnthropicProvider - official SDK, async streaming (needs `pip install anthropic` + key)
  * FakeProvider      - deterministic offline stream so the demo and tests run anywhere

Run:  uvicorn app:app --port 8000      then  curl -N -X POST localhost:8000/v1/chat -d '{"prompt":"hi"}'
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from pydantic import BaseModel, Field

DEFAULT_MODEL = "claude-opus-5-5"
LOG_PATH = Path(os.environ.get("LLM_LOG_PATH", Path(__file__).parent / "logs" / "requests.jsonl"))


# ---------------------------------------------------------------- providers
class FakeProvider:
    """Streams a canned answer word by word. `fail_after` simulates a mid-stream outage."""

    def __init__(self, delay: float = 0.0, fail_after: int | None = None):
        self.delay, self.fail_after = delay, fail_after

    async def stream(self, prompt: str):
        words = f"Demo answer to: {prompt}. This text is streamed in chunks.".split(" ")
        for i, w in enumerate(words):
            if self.fail_after is not None and i == self.fail_after:
                raise RuntimeError("upstream model unavailable")
            if self.delay:
                await asyncio.sleep(self.delay)
            yield w + (" " if i < len(words) - 1 else "")


class AnthropicProvider:
    def __init__(self, model: str = DEFAULT_MODEL, client=None):
        if client is None:
            import anthropic  # lazy import; FakeProvider needs no SDK
            client = anthropic.AsyncAnthropic()
        self.client, self.model = client, model

    async def stream(self, prompt: str):
        async with self.client.beta.messages.stream(
            model=self.model, max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
        ) as s:
            async for text in s.text_stream:
                yield text


# ---------------------------------------------------------------- logging + metrics
class LogWriter:
    """Background task: drains a bounded queue and appends one JSON line per request."""

    def __init__(self, path: Path, maxsize: int = 1000):
        self.path, self.queue = path, asyncio.Queue(maxsize=maxsize)
        self.task: asyncio.Task | None = None

    async def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.task = asyncio.create_task(self._run())

    async def put(self, record: dict):
        await self.queue.put(record)  # waits when full (backpressure) instead of dropping

    async def _run(self):
        while True:
            rec = await self.queue.get()
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            self.queue.task_done()

    async def stop(self):
        await self.queue.join()
        if self.task:
            self.task.cancel()


class Metrics:
    def __init__(self):
        self.requests = self.errors = 0
        self.ttft_ms: list[float] = []

    def snapshot(self):
        avg = round(sum(self.ttft_ms) / len(self.ttft_ms), 1) if self.ttft_ms else None
        return {"requests": self.requests, "errors": self.errors, "avg_ttft_ms": avg}


# ---------------------------------------------------------------- app factory
class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    stream: bool = True


def create_app(provider=None, log_path: Path = LOG_PATH, span_exporter=None) -> FastAPI:
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter or ConsoleSpanExporter()))
    tracer = tracer_provider.get_tracer("llm-backend")
    writer, metrics = LogWriter(log_path), Metrics()
    provider = provider or (AnthropicProvider() if os.environ.get("LLM_PROVIDER") == "anthropic"
                            else FakeProvider(delay=0.02))

    @asynccontextmanager
    async def lifespan(_app):
        await writer.start()
        yield
        await writer.stop()

    app = FastAPI(title="LLM streaming backend (demo)", lifespan=lifespan)
    app.state.writer, app.state.metrics = writer, metrics

    async def run(prompt: str, request_id: str):
        """Yields text chunks; always logs one record and ends the span, even on error."""
        metrics.requests += 1
        start, first, chunks, parts, status, error = time.perf_counter(), None, 0, [], "ok", None
        # start_span (not start_as_current_span): this generator yields across awaits, and a
        # "current" span would be detached in a different context than it was attached in.
        span = tracer.start_span("chat")
        span.set_attribute("request.id", request_id)
        span.set_attribute("prompt.chars", len(prompt))
        try:
            async for piece in provider.stream(prompt):
                if first is None:
                    first = time.perf_counter()
                chunks += 1
                parts.append(piece)
                yield piece
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception as e:  # provider failure mid-stream
            status, error = "error", str(e)
            metrics.errors += 1
            yield RuntimeError(error)
        finally:
            ttft = round((first - start) * 1000, 1) if first else None
            if ttft is not None:
                metrics.ttft_ms.append(ttft)
            span.set_attribute("llm.chunks", chunks)
            span.set_attribute("llm.status", status)
            if ttft is not None:
                span.set_attribute("llm.ttft_ms", ttft)
            span.end()
            await writer.put({"request_id": request_id, "ts": time.time(), "status": status,
                              "error": error, "chunks": chunks, "ttft_ms": ttft,
                              "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                              "prompt_chars": len(prompt), "output": "".join(parts)})

    @app.post("/v1/chat")
    async def chat(body: ChatRequest, request: Request):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        if not body.stream:
            text, err = [], None
            async for piece in run(body.prompt, rid):
                if isinstance(piece, Exception):
                    err = str(piece)
                else:
                    text.append(piece)
            status = 502 if err else 200
            return JSONResponse({"request_id": rid, "output": "".join(text), "error": err},
                                status_code=status, headers={"X-Request-ID": rid})

        async def sse():
            async for piece in run(body.prompt, rid):
                if isinstance(piece, Exception):
                    yield f"event: error\ndata: {json.dumps({'error': str(piece)})}\n\n"
                    return
                yield f"data: {json.dumps({'text': piece})}\n\n"
            yield "event: done\ndata: {}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream", headers={"X-Request-ID": rid})

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/metrics")
    async def get_metrics():
        return metrics.snapshot()

    return app


app = create_app()
