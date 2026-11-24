# Demo 06: Streaming LLM API Backend (FastAPI)
> **Demo project. The offline test provider stands in for the model; the Claude streaming provider is included.**

**What it does:** a production-style API in front of an LLM.
- `POST /v1/chat` streams output as Server-Sent Events (or returns one JSON response), with an `X-Request-ID` on every response.
- A background writer fed by a **bounded queue** aggregates the streamed chunks into **one JSON log line per request**. When the queue is full, writers wait (backpressure) instead of dropping logs.
- **OpenTelemetry** span per request: request ID, time to first token, chunk count, status.
- Mid-stream provider failures become an SSE `error` event, are logged with status `error`, and are counted in `/metrics`.
- `/health` and `/metrics` (requests, errors, average TTFT).

**Tests:** `python -m unittest -v` (7 pass). They cover streaming, request-ID propagation to header, log and span, lossless log aggregation, mid-stream failure, non-streaming mode, validation, and the Claude provider with a stubbed client.
**Run:** `uvicorn app:app --port 8000`. Set `LLM_PROVIDER=anthropic` plus `ANTHROPIC_API_KEY` for live model output.
