"""
DEMO PROJECT (synthetic data) - LLM evaluation harness.

Answers the question clients actually ask: "Which model should we use for OUR task, and
what will it cost?" Every candidate system runs on the same labelled dataset and is scored
per field, with latency, estimated cost per 1,000 documents and a failure list.

Candidates:
  * ClaudeCandidate(model)  - Anthropic Messages API with JSON-schema structured outputs
                              (official SDK; client's own key). Cost from response.usage.
  * RegexBaseline / KeywordBaseline - offline systems, so the harness runs with no key and
                              shows how a leaderboard and failure analysis look.

Usage:
    python make_dataset.py
    python harness.py                                   # offline baselines only
    python harness.py --models claude-haiku-5-5 claude-sonnet-5-5 claude-opus-5-5   # live
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
FIELDS = ["supplier", "po_number", "quantity", "delivery_date"]
# USD per million tokens (input, output), Anthropic first-party list prices (Nov 2026).
PRICES = {"claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5-5": (2.00, 10.00), "claude-haiku-5-5": (0.10, 0.50)}
SCHEMA = {
    "type": "object",
    "properties": {"supplier": {"type": "string"}, "po_number": {"type": "string"},
                   "quantity": {"type": "integer"}, "delivery_date": {"type": "string"}},
    "required": FIELDS, "additionalProperties": False,
}
PROMPT = ("Extract the supplier name, purchase order number, quantity and delivery date from this "
          "supplier email. Return the date as YYYY-MM-DD.\n\nEmail:\n")


def parse_date(s: str) -> str:
    for fmt in ("%d/%m/%Y", "%B %d, %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(" .;"), fmt).date().isoformat()
        except ValueError:
            pass
    return ""


class RegexBaseline:
    name = "regex-baseline"

    def predict(self, text: str) -> tuple[dict, dict]:
        po = re.search(r"PO[#\s-]*(?:no\.\s*)?(PO-\d+|\d+)", text) or re.search(r"(PO-\d+)", text)
        qty = re.search(r"(\d+)\s*(?:units|pcs|items)", text) or re.search(r"Quantity:\s*(\d+)", text)
        date_m = re.search(r"(\d{2}/\d{2}/\d{4}|[A-Z][a-z]+ \d{1,2}, \d{4}|\d{1,2} [A-Z][a-z]{2} \d{4})", text)
        sup = re.search(r"(?:Regards,|Best,|^|-)\s*\n?([A-Z][\w.]+(?: [A-Z][\w.]+)+?)(?: accounts| here| sales|$)", text, re.M)
        po_val = po.group(1) if po else ""
        if po_val and not po_val.startswith("PO-"):
            po_val = "PO-" + po_val
        return ({"supplier": sup.group(1).strip() if sup else "", "po_number": po_val,
                 "quantity": int(qty.group(1)) if qty else None,
                 "delivery_date": parse_date(date_m.group(1)) if date_m else ""}, {})


class KeywordBaseline:
    """Deliberately naive: looks for known supplier names and the first number."""
    name = "keyword-baseline"
    KNOWN = ["Lahore Paper House", "ColorTech Supplies", "BindRight Traders", "PlateMakers Co.", "PackLine Cartons"]

    def predict(self, text: str) -> tuple[dict, dict]:
        sup = next((k for k in self.KNOWN if k in text), "")
        po = re.search(r"PO-\d+", text)
        nums = [int(n) for n in re.findall(r"\b(\d{2,4})\b", text) if not text.count(f"PO-{n}")]
        return ({"supplier": sup, "po_number": po.group(0) if po else "",
                 "quantity": nums[0] if nums else None, "delivery_date": ""}, {})


class ClaudeCandidate:
    def __init__(self, model: str, client=None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.client, self.model, self.name = client, model, model

    def predict(self, text: str) -> tuple[dict, dict]:
        r = self.client.messages.create(
            model=self.model, max_tokens=1000,
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": PROMPT + text}])
        if r.stop_reason == "refusal":
            return ({f: "" for f in FIELDS}, {"refused": True})
        out = json.loads(next(b.text for b in r.content if getattr(b, "type", "") == "text"))
        return (out, {"input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens})


def normalise(field: str, v):
    if v is None:
        return None
    if field == "quantity":
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    return str(v).strip().lower()


def run_candidate(candidate, dataset: list[dict]) -> dict:
    per_field = {f: 0 for f in FIELDS}
    exact, latency, failures, tok_in, tok_out = 0, [], [], 0, 0
    for row in dataset:
        t0 = time.perf_counter()
        pred, usage = candidate.predict(row["text"])
        latency.append((time.perf_counter() - t0) * 1000)
        tok_in += usage.get("input_tokens", 0)
        tok_out += usage.get("output_tokens", 0)
        wrong = [f for f in FIELDS if normalise(f, pred.get(f)) != normalise(f, row["gold"][f])]
        for f in FIELDS:
            per_field[f] += f not in wrong
        exact += not wrong
        if wrong:
            failures.append({"id": row["id"], "wrong_fields": wrong,
                             "predicted": {f: pred.get(f) for f in wrong},
                             "expected": {f: row["gold"][f] for f in wrong}})
    n = len(dataset)
    price = PRICES.get(getattr(candidate, "model", ""), (0.0, 0.0))
    cost_per_1k = (tok_in * price[0] + tok_out * price[1]) / 1e6 / n * 1000 if n else 0.0
    return {"candidate": candidate.name, "n": n, "exact_match": exact / n,
            "field_accuracy": {f: per_field[f] / n for f in FIELDS},
            "p50_latency_ms": sorted(latency)[n // 2], "cost_per_1k_docs_usd": round(cost_per_1k, 4),
            "failures": failures}


def leaderboard(results: list[dict]) -> str:
    lines = ["| Candidate | Exact match | " + " | ".join(FIELDS) + " | p50 latency | $/1k docs |",
             "|---|---|" + "---|" * len(FIELDS) + "---|---|"]
    for r in sorted(results, key=lambda r: r["exact_match"], reverse=True):
        fa = " | ".join(f"{r['field_accuracy'][f]:.0%}" for f in FIELDS)
        lines.append(f"| {r['candidate']} | {r['exact_match']:.0%} | {fa} | {r['p50_latency_ms']:.1f} ms | "
                     f"{r['cost_per_1k_docs_usd']:.2f} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="*", default=[])
    a = ap.parse_args()
    dataset = json.loads((HERE / "dataset.json").read_text(encoding="utf-8"))
    candidates = [RegexBaseline(), KeywordBaseline()] + [ClaudeCandidate(m) for m in a.models]
    results = [run_candidate(c, dataset) for c in candidates]
    out = HERE / "output"
    out.mkdir(exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    board = leaderboard(results)
    (out / "leaderboard.md").write_text("# Leaderboard (demo, synthetic data)\n\n" + board, encoding="utf-8")
    print(board)
    for r in results:
        print(f"\n{r['candidate']}: {len(r['failures'])} failures", r["failures"][:2])


if __name__ == "__main__":
    main()
