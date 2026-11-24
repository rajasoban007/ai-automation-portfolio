import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1]))
from cover_kit import render_cover  # noqa: E402

before = pd.read_csv(HERE / "data" / "stock.csv").set_index("sku")
after = pd.read_csv(HERE / "output" / "stock_after_sync.csv").set_index("sku")
log = pd.read_excel(HERE / "output" / "sync_report.xlsx", sheet_name="Run Log").iloc[0]
rows = []
for sku, r in after.iterrows():
    low = r.on_hand <= r.reorder_level
    rows.append([sku, int(before.loc[sku, "on_hand"]), int(r.on_hand), int(r.reorder_level),
                 ("Reorder", "red") if low else ("OK", "green")])
rows.append(["UNKNOWN-SKU (order 1010)", "–", "–", "–", ("Data problem", "amber")])
print(render_cover(
    HERE / "images" / "cover_4x3.png",
    "Orders → Inventory Sync",
    "Store REST API → paginated pull with retries → stock applied exactly once",
    [("Orders synced", 23, "ink"), ("Applied twice", 0, "green"),
     ("Cancellations restocked", int(log.restocked_cancellations), "navy"),
     ("Low-stock alerts", int((after.on_hand <= after.reorder_level).sum()), "red")],
    "Stock after sync",
    [("SKU", 420), ("Before", 200), ("After", 200), ("Reorder level", 260), ("Status", 330)],
    rows,
    "Demo project · sample data · Python + requests, idempotent & incremental"))
