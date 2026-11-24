"""Tests: python -m unittest -v"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import app as backend


def sse_events(text: str):
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
        events.append((lines.get("event", "message"), json.loads(lines.get("data", "{}"))))
    return events


class BackendTests(unittest.TestCase):
    def make(self, provider):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "requests.jsonl"
        self.spans = InMemorySpanExporter()
        return backend.create_app(provider=provider, log_path=self.log, span_exporter=self.spans)

    def tearDown(self):
        self.tmp.cleanup()

    def logs(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()]

    def test_stream_returns_chunks_and_done(self):
        with TestClient(self.make(backend.FakeProvider())) as c:
            r = c.post("/v1/chat", json={"prompt": "hello"})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.headers["content-type"].startswith("text/event-stream"))
            ev = sse_events(r.text)
            text = "".join(d["text"] for e, d in ev if e == "message")
            self.assertIn("Demo answer to: hello.", text)
            self.assertEqual(ev[-1][0], "done")

    def test_request_id_propagates_to_header_log_and_span(self):
        with TestClient(self.make(backend.FakeProvider())) as c:
            r = c.post("/v1/chat", json={"prompt": "hi"}, headers={"x-request-id": "req-123"})
            self.assertEqual(r.headers["x-request-id"], "req-123")
        rec = self.logs()[0]
        self.assertEqual(rec["request_id"], "req-123")
        self.assertEqual(rec["status"], "ok")
        self.assertGreater(rec["chunks"], 3)
        span = self.spans.get_finished_spans()[0]
        self.assertEqual(span.attributes["request.id"], "req-123")
        self.assertEqual(span.attributes["llm.status"], "ok")

    def test_logged_output_equals_streamed_output(self):
        with TestClient(self.make(backend.FakeProvider())) as c:
            r = c.post("/v1/chat", json={"prompt": "abc"})
            streamed = "".join(d["text"] for e, d in sse_events(r.text) if e == "message")
        self.assertEqual(self.logs()[0]["output"], streamed)  # lossless aggregation

    def test_midstream_failure_emits_error_event_and_logs(self):
        with TestClient(self.make(backend.FakeProvider(fail_after=3))) as c:
            r = c.post("/v1/chat", json={"prompt": "x"})
            ev = sse_events(r.text)
            self.assertEqual(ev[-1][0], "error")
            self.assertIn("unavailable", ev[-1][1]["error"])
            self.assertEqual(c.get("/metrics").json()["errors"], 1)
        rec = self.logs()[0]
        self.assertEqual((rec["status"], rec["chunks"]), ("error", 3))

    def test_non_streaming_mode_and_metrics(self):
        with TestClient(self.make(backend.FakeProvider())) as c:
            r = c.post("/v1/chat", json={"prompt": "q", "stream": False})
            self.assertEqual(r.status_code, 200)
            self.assertIn("Demo answer", r.json()["output"])
            m = c.get("/metrics").json()
            self.assertEqual(m["requests"], 1)
            self.assertIsNotNone(m["avg_ttft_ms"])

    def test_validation_rejects_empty_prompt(self):
        with TestClient(self.make(backend.FakeProvider())) as c:
            self.assertEqual(c.post("/v1/chat", json={"prompt": ""}).status_code, 422)

    def test_anthropic_provider_streams_text(self):
        class FakeStream:
            def __init__(self): self.text_stream = self._gen()
            async def _gen(self):
                for t in ["Hel", "lo"]:
                    yield t
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
        calls = []
        def stream(**kw):
            calls.append(kw)
            return FakeStream()
        fake_client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))
        provider = backend.AnthropicProvider(client=fake_client)
        with TestClient(self.make(provider)) as c:
            r = c.post("/v1/chat", json={"prompt": "hi"})
            text = "".join(d["text"] for e, d in sse_events(r.text) if e == "message")
        self.assertEqual(text, "Hello")
        self.assertEqual(calls[0]["model"], backend.DEFAULT_MODEL)


if __name__ == "__main__":
    unittest.main()
