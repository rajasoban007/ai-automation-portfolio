import json, sys, tempfile
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1])); sys.path.insert(0, str(HERE))
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
import app as backend
from cover_kit import render_cover
tmp = Path(tempfile.mkdtemp()) / "requests.jsonl"
spans = InMemorySpanExporter()
class Mixed:
    def __init__(self): self.n = 0
    async def stream(self, prompt):
        self.n += 1
        p = backend.FakeProvider(delay=0.002, fail_after=4 if self.n in (7, 15) else None)
        async for x in p.stream(prompt):
            yield x
with TestClient(backend.create_app(provider=Mixed(), log_path=tmp, span_exporter=spans)) as c:
    for i in range(20):
        c.post("/v1/chat", json={"prompt": f"question {i}"}, headers={"x-request-id": f"req-{i:03d}"})
    m = c.get("/metrics").json()
logs = [json.loads(l) for l in tmp.read_text().splitlines()]
rows = [[r["request_id"], (r["status"], "green" if r["status"] == "ok" else "red"), r["chunks"], f"{r['ttft_ms']} ms", f"{r['latency_ms']} ms"] for r in logs[4:12]]
print(render_cover(HERE / "images" / "cover_4x3.png", "Streaming LLM API Backend",
    "FastAPI · Server-Sent Events · background log queue · OpenTelemetry traces",
    [("Requests", m["requests"], "ink"), ("Errors handled", m["errors"], "red"),
     ("Avg time to first token", f"{m['avg_ttft_ms']} ms", "navy"), ("Spans traced", len(spans.get_finished_spans()), "green")],
    "Request log (one JSON line per request, aggregated from streamed chunks)",
    [("Request ID", 280), ("Status", 220), ("Chunks", 200), ("TTFT", 300), ("Latency", 300)], rows,
    "Demo project · offline test provider (Claude streaming provider included) · 7 tests"))
