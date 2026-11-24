# Demo 01: Inventory Reorder Automation
> **Demo project built with synthetic sample data. Not client work.**

**Problem:** small manufacturers and distributors reorder from memory or gut feel. Stock runs out and production stops, or cash sits tied up in overstock.

**What it does (one command, scheduled weekly):**
1. Reads a stock list (on hand, on order, supplier, lead time, MOQ) and the usage history. Any ERP, Excel or Sheets export works.
2. Calculates **safety stock, reorder point and order-up-to level** for each SKU from actual usage variability (about a 95% service level).
3. Flags **URGENT** items (days of cover shorter than supplier lead time), **REORDER** and **WATCH** items.
4. Drafts **purchase orders grouped by supplier**, rounded to each supplier's MOQ.
5. Builds an **Excel dashboard** (KPIs, cover-vs-lead-time chart, colour-coded status sheet, method notes) and an **HTML email summary** for the owner or purchasing team.

**Demo result:** 12 SKUs tracked, 2 urgent, $3,010 suggested PO value, $33.8k stock on hand.

**Stack:** Python, pandas, openpyxl. Runs on Windows Task Scheduler, a cron job or GitHub Actions. It ports to Google Apps Script for teams that work in Sheets.

**Extensions offered:** auto-email POs to suppliers after approval, Google Sheets live version, AI step that reads supplier quotes and price changes from email.

Run: `python reorder_report.py` (demo data) or `python reorder_report.py --items items.csv --usage usage.csv`.

## Tests
`python -m unittest` runs 9 tests (reorder maths, MOQ rounding, statuses, workbook and email output). Added 21 Nov 2026.
