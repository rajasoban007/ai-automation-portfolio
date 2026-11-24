# AI & Python Automation Portfolio

Eight small, tested demo projects by **Soban Farooq** (Python & AI engineer, Lahore). Each one solves a real operations problem end to end — LLM apps, document AI, evaluation, data pipelines and API integrations.

> **All projects are demos built with synthetic or sample data. None of them is client work.** LLM features run on your own Anthropic or OpenAI key; every project also has an offline mode so the tests run without a key.

| # | Project | What it shows | Tests |
|---|---|---|---|
| 05 | [Document Q&A (RAG) with evaluation](05_rag_document_qa) | BM25 retrieval + domain glossary, grounded Claude answers with citations and refusals, 20-question eval (hit@3, answer, citation, refusal accuracy) | 7 |
| 06 | [Streaming LLM API backend](06_llm_streaming_backend) | FastAPI + Server-Sent Events, bounded-queue log writer with backpressure, OpenTelemetry spans, `/health` and `/metrics` | 7 |
| 07 | [LLM evaluation harness](07_llm_eval_harness) | Same labelled set for every model: per-field accuracy, exact match, p50 latency, cost per 1,000 documents, failure list | 7 |
| 02 | [AI invoice / PO extractor](02_ai_invoice_extractor) | PDF → LLM → JSON-schema validation → review queue → Excel/CSV | 11 |
| 08 | [AP & vendor-spend report](08_ap_vendor_spend_report) | Mock accounting API: OAuth token refresh, retries, incremental pull, reconciliation, Excel report | 8 |
| 03 | [Supplier price tracker](03_supplier_price_tracker) | CSV/Excel/JSON price lists → currency conversion → SQLite history → price-move alerts | 8 |
| 04 | [Orders ↔ inventory sync](04_orders_inventory_sync) | Mock store API, idempotent order sync, stock updates, sync report | 7 |
| 01 | [Inventory reorder automation](01_inventory_reorder_automation) | Reorder points from usage and lead time, Excel dashboard, weekly email | 9 |

## Run it

```bash
pip install -r requirements.txt
cd 05_rag_document_qa
python -m unittest -v
```

Each folder has its own README with what it does, honest notes on its limits, and how to run it. `make_cover.py` files only render the portfolio images (set `COVER_FONT` to a `.ttf` path for the original look).

## About me

BS Electrical Engineering (Bahria University). By day I run production and procurement at a printing and publishing company, so these demos are built around the invoices, purchase orders, stock and supplier data that operations teams actually handle.

Available for freelance work on Upwork and Contra (contra.com/sobanfarooq).
