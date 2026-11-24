# Demo 02: AI Invoice Extractor
> **Demo project built with synthetic sample invoices. Not client work.**

**Problem:** accounts and purchasing teams re-key supplier invoices by hand, which is slow and error-prone. Duplicates and arithmetic errors get paid.

**What it does:**
1. Reads supplier invoices as PDFs. Every supplier uses a different layout and different labels.
2. Extracts supplier, invoice number, date, PO, currency, subtotal, tax, total and line items into a strict JSON schema.
   - **Claude mode:** sends the PDF to Claude (Anthropic Messages API, official Python SDK) with **structured outputs** (`output_config.format` JSON schema), refusal handling and server-side fallbacks.
   - **Offline mode:** a rule-based parser for the sample layouts, so the demo and tests run with no API key and no cost.
3. Validates every invoice:
   - required fields present
   - supplier is in the vendor master
   - a PO number exists (needed for 3-way matching)
   - qty × price = amount
   - lines sum to the subtotal
   - subtotal + tax = total
   - the date isn't in the future or older than 90 days
   - **no duplicate supplier + invoice number**
4. Auto-approves clean invoices and sends the rest to a **human review queue** with the reason.
5. Writes `invoices.csv`, `line_items.csv`, `review_queue.csv` and an Excel `invoice_register.xlsx`.

**Demo result (offline mode):** 6 invoices: 3 auto-approved, 3 sent to review (missing PO, duplicate, total ≠ subtotal + tax).

**Tests:** `python -m unittest -v`. All 11 pass. They cover extraction, each validation rule, end-to-end outputs, and the Claude request shape and refusal handling, using a stubbed client.
**Not yet verified:** Claude mode against the live API. It needs the client's own Anthropic API key. Model is configurable (`--model`, default `claude-opus-5-5`; a cheaper model such as `claude-haiku-5-5` can be chosen per client volume after testing on their documents).

**Run:**
```
python make_samples.py          # generate the sample PDFs
python extractor.py             # offline mode
pip install anthropic && python extractor.py --mode claude    # live mode, client key required
```

**Extensions offered:** Gmail/Outlook inbox intake, Google Sheets output, PO and goods-received matching, accounting system export (QuickBooks/Xero CSV), scanned-image invoices.
