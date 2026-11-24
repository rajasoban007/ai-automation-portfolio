"""4:3 portfolio cover for Demo 08, built from the real output workbook (run ap_report.py first)."""
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1]))
from cover_kit import render_cover

x = pd.read_excel(HERE / "output" / "ap_vendor_report.xlsx", sheet_name=None)
s = dict(zip(x["Summary"]["Item"], x["Summary"]["Value"]))
aging = x["AP Aging"].sort_values("Open balance", ascending=False)
exc = x["Exceptions"]

rows = []
for _, r in aging.iterrows():
    over60 = r.get("61-90 days overdue", 0) + r.get("90+ days overdue", 0)
    rows.append([r["Vendor"], f"{r.get('Not yet due', 0):,.0f}",
                 f"{r.get('1-30 days overdue', 0) + r.get('31-60 days overdue', 0):,.0f}",
                 (f"{over60:,.0f}", "red" if over60 > 1500 else "amber" if over60 else "green"),
                 f"{r['Open balance']:,.0f}"])
for _, e in exc.iterrows():
    rows.append([f"⚠ {e['Bill']}", (str(e["Issue"]).split(" (")[0], "amber"), "", "", f"{e['Amount']:,.0f}"])

recon = str(s["Reconciled"]) == "YES"
out = HERE / "images" / "cover_4x3.png"
out.parent.mkdir(exist_ok=True)
print(render_cover(out, "AP & Vendor-Spend Report",
    "Accounting API (QuickBooks-style) → incremental pull → reconcile → Excel, every Monday",
    [("Bills pulled", int(s["Bills in report"]), "ink"), ("Open AP", f"{float(s['Open AP (report)']):,.0f}", "ink"),
     ("Matches ledger", "YES" if recon else "NO", "green" if recon else "red"),
     ("Exceptions", int(s["Exceptions"]), "red")],
    "AP aging by vendor + flagged bills",
    [("Vendor", 420), ("Not yet due", 220), ("1–60 days over", 250), ("60+ days over", 250), ("Open", 200)], rows,
    "Demo project · mock API, sample data · Python, OAuth2 refresh, retries, pandas · 8 tests"))
