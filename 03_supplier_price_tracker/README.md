# Demo 03: Supplier Price Tracker (data pipeline)
> **Demo project built with synthetic supplier price lists. Not client work.**

**Problem:** purchasing teams get price lists from many suppliers in different formats, currencies and item codes. Price rises slip through unnoticed, and nobody knows who is cheapest this week.

**What it does (one scheduled run per week):**
1. **Extract.** Reads each supplier's own format: a CSV in USD, an Excel sheet priced in **PKR**, and a JSON API export.
2. **Transform.** Maps each supplier's item codes to internal SKUs, converts to USD, and rejects bad rows: unmapped codes, non-positive prices, unexpected currency. Every problem is logged as a warning.
3. **Load.** Stores every snapshot in **SQLite**. Re-running a week doesn't duplicate rows.
4. **Report.** Shows week-over-week change per supplier and SKU, an **alert list** for moves above a threshold (default 5%), the **cheapest supplier per SKU** with the saving against the dearest, and the full price history.
5. Writes `price_report.xlsx` and an HTML alert email for the purchasing team.

**Demo result:** 3 suppliers, 5 SKUs and 4 weekly snapshots. It catches a +13.2% paper price rise and a −8.7% ink price drop that makes a new supplier cheapest.

**Tests:** `python -m unittest -v`. All 8 pass. They cover format normalisation, PKR conversion, warnings for unmapped codes and missing files, wrong-currency rejection, jump detection, cheapest-supplier switch, idempotent reload and report output.

**Run:** `python make_samples.py` then `python pipeline.py [--threshold 5]`

**Production notes:** live exchange rate from a source the client chooses. Supplier data is pulled only from files, emails or APIs the supplier provides, or websites whose terms allow automated access. The SKU map lives in a sheet the client can edit. Output can go to Google Sheets or Slack.
