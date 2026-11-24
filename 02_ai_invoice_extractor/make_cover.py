import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1]))
from cover_kit import render_cover  # noqa: E402

inv = pd.read_csv(HERE / "output" / "invoices.csv").fillna("")
ok = (inv.status == "AUTO-APPROVED").sum()
rows = []
for r in inv.itertuples():
    badge = ("Auto-approved", "green") if r.status == "AUTO-APPROVED" else ("Review", "red")
    issue = r.issues.split(";")[0] if r.issues else "All checks passed"
    rows.append([r.supplier.replace(" (Sample)", ""), r.invoice_number, f"${r.total:,.2f}", badge, issue])

print(render_cover(
    HERE / "images" / "cover_4x3.png",
    "AI Invoice Extractor",
    "PDF invoices → structured data → validation rules → review queue",
    [("Invoices", len(inv), "ink"), ("Auto-approved", ok, "green"),
     ("Sent to review", len(inv) - ok, "red"), ("Value captured", f"${inv.total.sum():,.0f}", "navy")],
    "Batch result",
    [("Supplier", 300), ("Invoice", 150), ("Total", 160), ("Status", 220), ("Reason", 580)],
    rows,
    "Demo project · sample data · Python + Claude API (structured outputs) + pandas"))
