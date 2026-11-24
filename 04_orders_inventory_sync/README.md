# Demo 04: Orders → Inventory Sync (API integration)
> **Demo project against a bundled mock store API with sample data. Not client work.**

**Problem:** online orders and the stock sheet drift apart. Staff update stock by hand, cancellations get forgotten, and items oversell.

**What it does (scheduled, e.g. every 15 minutes):**
1. Calls the store's REST API with a bearer token. It pulls only orders **changed since the last run**, follows **cursor pagination**, and **retries 429 and 5xx errors** with backoff.
2. Applies each order to the stock sheet **exactly once**, keyed by order ID and status. Re-running or re-fetching never deducts twice.
3. **Puts stock back** when a paid order is later cancelled.
4. Reports **unknown SKUs** instead of crashing, and raises **low-stock alerts** against reorder levels.
5. Writes `stock_after_sync.csv`, plus `sync_report.xlsx` with Stock, Low Stock, Data Problems and Run Log sheets. State is kept in `sync_state.json`.

**Demo result:** 23 orders synced, 0 applied twice, 1 cancellation restocked, 1 low-stock alert, 1 unknown SKU surfaced.

**Tests:** `python -m unittest -v`. All 7 pass. They run against the live mock HTTP server and cover pagination with rate-limit retries, correct deductions, idempotent replay, cancellation restock, unknown SKU, bad token and low-stock flags.

**Run:** `python sync.py` (it starts the mock store automatically). The mock API can also run on its own with `python mock_store.py`.

**Real platforms:** the client class is the only part that changes per platform (Shopify, WooCommerce, Daraz seller API, a custom ERP). The sync, idempotency and alerting logic stay the same. The stock sheet can be Google Sheets instead of CSV.
