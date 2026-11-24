# Demo 08: AP & Vendor-Spend Report from an Accounting API
> **Demo project against a bundled mock accounting API with sample data. Not client work. Not a live QuickBooks or Xero integration.**

**Problem:** finance teams export bills from QuickBooks/Xero every week, rebuild the vendor-spend and AP-aging sheets by hand, and only notice a missing or double-entered bill when a supplier chases payment.

**What it does (scheduled, e.g. every Monday 07:00):**
1. Connects with the **OAuth2 refresh-token flow** and refreshes the short-lived access token automatically when it expires mid-run.
2. Pulls only bills **changed since the last run** (offset pagination, `startposition`/`maxresults`), and **retries 429 and 5xx** responses.
3. Keeps bills keyed by ID, so an edited or paid bill **replaces** its old copy and is never counted twice.
4. **Reconciles** open AP against the ledger's own control total. On a mismatch the report says *do not send* and lists the difference.
5. Flags **duplicate bill numbers** per vendor and bills pointing at an **unknown vendor**.
6. Writes `output/ap_vendor_report.xlsx`: Summary, Vendor Spend (by month), AP Aging (not due / 1–30 / 31–60 / 61–90 / 90+ days overdue) and Exceptions.

**Demo result:** 36 bills, open AP 20,437.57 = ledger control (reconciled), 2 exceptions (1 duplicate bill number, 1 unknown vendor), 3 token refreshes and 2 rate-limit retries handled.

**Tests:** `python -m unittest -v`. All 8 pass against the live mock server: pagination + rate limits + token expiry, first-run reconciliation, incremental runs with no double counting, duplicate/unknown-vendor flags, a voided bill breaking reconciliation, aging buckets, a bad refresh token, and the Excel sheets.

**Run:** `python ap_report.py` (starts the mock API automatically). The mock can also run alone: `python mock_ledger.py`.

**Real platforms:** only `LedgerClient` changes (QuickBooks Online Accounting API, Xero, Zoho Books). A production version would also use the platform's change-data-capture or deleted-records feed, which is exactly the gap the "voided bill" test shows.
