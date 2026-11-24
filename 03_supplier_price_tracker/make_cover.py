import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1]))
import pipeline as pl  # noqa: E402
from cover_kit import render_cover  # noqa: E402

con = sqlite3.connect(HERE / "output" / "prices.sqlite")
res = pl.analyse(con, 5)
a, best = res["alerts"], res["best"].set_index("sku")
rows = []
for r in a.itertuples():
    badge = (f"{r.change_pct:+.1f}%", "red" if r.change_pct > 0 else "green")
    cheapest = best.loc[r.sku, "cheapest_supplier"].replace(" (Sample)", "")
    rows.append([r.sku, r.supplier.replace(" (Sample)", ""), f"${r.prev_usd:.2f} → ${r.price_usd:.2f}",
                 badge, cheapest])
top = a.iloc[0]
print(render_cover(
    HERE / "images" / "cover_4x3.png",
    "Supplier Price Tracker",
    "CSV + Excel (PKR) + JSON API → normalised USD → SQLite history → alerts",
    [("Suppliers", 3, "ink"), ("SKUs mapped", best.shape[0], "ink"),
     ("Price alerts (≥5%)", len(a), "amber"), ("Biggest move", f"{top.change_pct:+.1f}%", "red")],
    f"This week's alerts (vs {res['latest'].previous[0]})",
    [("SKU", 250), ("Supplier", 330), ("Price", 260), ("Change", 170), ("Cheapest now", 400)],
    rows,
    "Demo project · sample data · Python + pandas + SQLite, scheduled weekly"))
