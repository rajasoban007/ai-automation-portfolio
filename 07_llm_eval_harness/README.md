# Demo 07: LLM Evaluation Harness
> **Demo project built with synthetic supplier emails. Not client work.**

**What it does:** answers "which model should we use for our task, and what will it cost?" Every candidate runs on the same labelled dataset and gets per-field accuracy, exact-match rate, p50 latency, **estimated cost per 1,000 documents** (from real token usage × list prices) and a failure list showing exactly what each one got wrong.

Candidates: Claude models via the official SDK with JSON-schema structured outputs (client's key), plus two offline baselines so the harness runs anywhere.

**Offline result (15 emails):** regex baseline 73% exact match (misses suppliers in some layouts), keyword baseline 0% (never finds dates). The leaderboard makes that visible in one table.

**Tests:** `python -m unittest -v` (7 pass). They cover scoring, the failure list, the cost formula, structured-output requests, refusals, leaderboard order and date normalisation.
**Run:** `python make_dataset.py && python harness.py [--models claude-haiku-5-5 claude-sonnet-5-5 claude-opus-5-5]`
