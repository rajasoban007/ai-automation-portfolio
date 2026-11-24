import json, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1]))
from cover_kit import render_cover
res = json.loads((HERE / "output" / "results.json").read_text())
fields = ["supplier", "po_number", "quantity", "delivery_date"]
rows = []
for r in sorted(res, key=lambda r: r["exact_match"], reverse=True):
    rows.append([r["candidate"], (f"{r['exact_match']:.0%}", "green" if r["exact_match"] >= .7 else "red")] +
                [f"{r['field_accuracy'][f]:.0%}" for f in fields])
rows.append(["claude-haiku/sonnet/opus-5-5", ("plug in key", "grey"), "-", "-", "-", "-"])
best = max(res, key=lambda r: r["exact_match"])
print(render_cover(HERE / "images" / "cover_4x3.png", "LLM Evaluation Harness",
    "Same labelled dataset → every model → per-field accuracy, latency, cost per 1k docs",
    [("Test documents", best["n"], "ink"), ("Candidates", len(res), "ink"),
     ("Best exact match", f"{best['exact_match']:.0%}", "green"), ("Failures listed", sum(len(r['failures']) for r in res), "red")],
    "Leaderboard: supplier-email field extraction",
    [("Candidate", 380), ("Exact match", 200), ("Supplier", 200), ("PO no.", 200), ("Qty", 200), ("Date", 220)], rows,
    "Demo project · synthetic emails · Python + Claude API structured outputs · 7 tests"))
