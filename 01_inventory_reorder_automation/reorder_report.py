"""
DEMO PROJECT (sample data) - Shopfloor Logic portfolio
Inventory reorder automation: reads stock + usage history, calculates reorder
points, flags items to buy, drafts purchase orders per supplier, and builds an
Excel dashboard plus an HTML email summary.

Usage:
    python reorder_report.py                  # generates demo data, then the report
    python reorder_report.py --items my.csv --usage my_usage.csv

items.csv : sku,name,supplier,unit_cost,on_hand,on_order,lead_time_days,moq
usage.csv : date,sku,qty_used
"""
import argparse
import math
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HERE = Path(__file__).parent
OUT = HERE / "output"
SERVICE_LEVEL_Z = 1.65  # ~95% service level
REVIEW_DAYS = 7         # weekly ordering cycle


def make_demo_data(seed=7):
    """Synthetic data for a small printing/stationery business. Not real."""
    rng = random.Random(seed)
    catalogue = [
        ("PAP-80G-A4", "Offset paper 80gsm A4 (ream)", "Lahore Paper House", 6.10, 14),
        ("PAP-70G-23x36", "Newsprint 70gsm 23x36 (ream)", "Lahore Paper House", 9.40, 14),
        ("BRD-300G", "Art card 300gsm (sheet pack)", "Lahore Paper House", 18.00, 21),
        ("INK-CYAN-1KG", "Offset ink cyan 1kg", "ColorTech Supplies", 11.50, 10),
        ("INK-MAG-1KG", "Offset ink magenta 1kg", "ColorTech Supplies", 11.50, 10),
        ("INK-YEL-1KG", "Offset ink yellow 1kg", "ColorTech Supplies", 11.00, 10),
        ("INK-BLK-1KG", "Offset ink black 1kg", "ColorTech Supplies", 9.80, 10),
        ("PLT-CTP-A1", "CTP plate A1", "PlateMakers Co.", 7.20, 7),
        ("GLU-PUR-5KG", "PUR binding glue 5kg", "BindRight Traders", 32.00, 12),
        ("WRP-SHRINK", "Shrink wrap roll", "BindRight Traders", 14.50, 5),
        ("CTN-BOX-L", "Carton box large (25 pcs)", "PackLine", 8.00, 4),
        ("BLD-WIRE", "Wire-O binding spools", "BindRight Traders", 21.00, 12),
    ]
    start = date.today() - timedelta(days=90)
    usage_rows, item_rows = [], []
    for sku, name, sup, cost, lead in catalogue:
        base = rng.uniform(2, 25)
        for d in range(90):
            day = start + timedelta(days=d)
            if day.weekday() == 6:  # Sunday closed
                continue
            qty = max(0, round(rng.gauss(base, base * 0.35)))
            usage_rows.append((day.isoformat(), sku, qty))
        on_hand = round(base * rng.uniform(4, 30))
        on_order = rng.choice([0, 0, 0, round(base * 10)])
        moq = rng.choice([10, 20, 25, 50])
        item_rows.append((sku, name, sup, cost, on_hand, on_order, lead, moq))
    items = pd.DataFrame(item_rows, columns=["sku", "name", "supplier", "unit_cost",
                                             "on_hand", "on_order", "lead_time_days", "moq"])
    usage = pd.DataFrame(usage_rows, columns=["date", "sku", "qty_used"])
    return items, usage


def calculate(items: pd.DataFrame, usage: pd.DataFrame) -> pd.DataFrame:
    usage = usage.copy()
    usage["date"] = pd.to_datetime(usage["date"])
    days = (usage["date"].max() - usage["date"].min()).days + 1
    # Daily series incl. zero days, so std dev is honest
    daily = (usage.pivot_table(index="date", columns="sku", values="qty_used", aggfunc="sum")
             .reindex(pd.date_range(usage["date"].min(), usage["date"].max()), fill_value=0)
             .fillna(0))
    stats = pd.DataFrame({"avg_daily": daily.mean(), "std_daily": daily.std(ddof=0)})
    df = items.merge(stats, left_on="sku", right_index=True, how="left").fillna(
        {"avg_daily": 0, "std_daily": 0})

    lt = df["lead_time_days"]
    df["safety_stock"] = (SERVICE_LEVEL_Z * df["std_daily"] * (lt ** 0.5)).round()
    df["reorder_point"] = (df["avg_daily"] * lt + df["safety_stock"]).round()
    df["target_stock"] = (df["avg_daily"] * (lt + REVIEW_DAYS) + df["safety_stock"]).round()
    df["position"] = df["on_hand"] + df["on_order"]
    df["days_of_cover"] = (df["on_hand"] / df["avg_daily"].where(df["avg_daily"] > 0)).round(1)

    def order_qty(r):
        if r.position > r.reorder_point:
            return 0
        need = max(0, r.target_stock - r.position)
        return int(max(r.moq, math.ceil(need / r.moq) * r.moq)) if need else 0

    df["order_qty"] = df.apply(order_qty, axis=1)
    df["order_value"] = (df["order_qty"] * df["unit_cost"]).round(2)
    df["status"] = "OK"
    df.loc[df["order_qty"] > 0, "status"] = "REORDER"
    df.loc[df["days_of_cover"] < df["lead_time_days"], "status"] = "URGENT"
    df.loc[(df["status"] == "URGENT") & (df["order_qty"] == 0), "status"] = "WATCH"
    df["stock_value"] = (df["on_hand"] * df["unit_cost"]).round(2)
    df.attrs["history_days"] = days
    return df


HEAD = PatternFill("solid", fgColor="1F3A5F")
WHITE_BOLD = Font(color="FFFFFF", bold=True)


def write_table(ws, df, start_row=1):
    for c, col in enumerate(df.columns, 1):
        cell = ws.cell(row=start_row, column=c, value=col.replace("_", " ").title())
        cell.fill, cell.font = HEAD, WHITE_BOLD
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    for r, row in enumerate(df.itertuples(index=False), start_row + 1):
        for c, v in enumerate(row, 1):
            ws.cell(row=r, column=c, value=v)
    for c, col in enumerate(df.columns, 1):
        width = max(len(str(col)), *(len(str(v)) for v in df[col])) + 2
        ws.column_dimensions[get_column_letter(c)].width = min(width, 40)
    ws.freeze_panes = ws.cell(row=start_row + 1, column=1)


def build_workbook(df: pd.DataFrame, path: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Dashboard"
    ws["A1"] = "Inventory & Reorder Dashboard"
    ws["A1"].font = Font(size=16, bold=True, color="1F3A5F")
    ws["A2"] = f"DEMO PROJECT - sample data. Generated {date.today():%d %b %Y}. " \
               f"History: {df.attrs['history_days']} days."
    ws["A2"].font = Font(italic=True, color="888888")

    kpis = [
        ("SKUs tracked", len(df)),
        ("Urgent (cover < lead time)", int((df.status == "URGENT").sum())),
        ("To reorder", int((df.order_qty > 0).sum())),
        ("Suggested PO value ($)", round(df.order_value.sum(), 2)),
        ("Stock on hand value ($)", round(df.stock_value.sum(), 2)),
    ]
    for i, (k, v) in enumerate(kpis):
        col = 1 + i * 2
        ws.cell(row=4, column=col, value=k).font = Font(color="666666", size=9)
        ws.cell(row=5, column=col, value=v).font = Font(size=18, bold=True)
        ws.column_dimensions[get_column_letter(col)].width = 22

    cover = df[["sku", "days_of_cover", "lead_time_days"]].sort_values("days_of_cover")
    ws.cell(row=7, column=1, value="Days of cover vs lead time").font = Font(bold=True)
    write_table(ws, cover, start_row=8)
    ws.freeze_panes = None
    chart = BarChart()
    chart.type = "bar"
    chart.title = "Days of cover vs supplier lead time"
    chart.y_axis.title = "Days"
    data = Reference(ws, min_col=2, max_col=3, min_row=8, max_row=8 + len(cover))
    cats = Reference(ws, min_col=1, min_row=9, max_row=8 + len(cover))
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.height, chart.width = 9, 18
    ws.add_chart(chart, "E8")

    ws2 = wb.create_sheet("Stock Status")
    cols = ["sku", "name", "supplier", "on_hand", "on_order", "avg_daily", "lead_time_days",
            "safety_stock", "reorder_point", "days_of_cover", "order_qty", "order_value", "status"]
    t = df[cols].copy()
    t["avg_daily"] = t["avg_daily"].round(1)
    write_table(ws2, t.sort_values(["status", "days_of_cover"]))
    status_col = get_column_letter(len(cols))
    rng = f"{status_col}2:{status_col}{len(t) + 1}"
    for word, color in (("URGENT", "F8CBAD"), ("REORDER", "FFE699"), ("WATCH", "DDEBF7")):
        ws2.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=[f'"{word}"'],
                                                       fill=PatternFill("solid", fgColor=color)))

    ws3 = wb.create_sheet("Draft POs")
    po = df[df.order_qty > 0][["supplier", "sku", "name", "order_qty", "unit_cost", "order_value"]]
    write_table(ws3, po.sort_values("supplier"))
    r = len(po) + 3
    for sup, g in po.groupby("supplier"):
        ws3.cell(row=r, column=1, value=f"PO total - {sup}").font = Font(bold=True)
        ws3.cell(row=r, column=6, value=round(g.order_value.sum(), 2)).font = Font(bold=True)
        r += 1

    ws4 = wb.create_sheet("Method")
    notes = [
        "Safety stock = Z x std dev of daily usage x sqrt(lead time), Z = 1.65 (~95% service level)",
        "Reorder point = average daily usage x lead time + safety stock",
        f"Order up to = average daily usage x (lead time + {REVIEW_DAYS}-day review cycle) + safety stock",
        "Order qty rounded up to supplier MOQ; only raised when stock position <= reorder point",
        "URGENT = days of cover on hand < supplier lead time",
    ]
    for i, n in enumerate(notes, 1):
        ws4.cell(row=i, column=1, value=n)
    ws4.column_dimensions["A"].width = 110
    wb.save(path)


def build_email(df: pd.DataFrame, path: Path):
    urgent = df[df.status == "URGENT"]
    po = df[df.order_qty > 0]
    rows = "".join(
        f"<tr><td>{r.sku}</td><td>{r.name}</td><td>{r.days_of_cover}</td>"
        f"<td>{r.lead_time_days}</td><td>{r.order_qty}</td><td>${r.order_value:,.2f}</td></tr>"
        for r in po.sort_values("days_of_cover").itertuples())
    sup = "".join(f"<li>{s}: ${v:,.2f}</li>" for s, v in po.groupby("supplier").order_value.sum().items())
    html = f"""<html><body style="font-family:Segoe UI,Arial;color:#222">
<p style="color:#888"><i>Demo project - sample data</i></p>
<h2 style="color:#1F3A5F">Weekly reorder summary - {date.today():%d %b %Y}</h2>
<p><b>{len(urgent)}</b> urgent item(s), <b>{len(po)}</b> item(s) to reorder,
suggested PO value <b>${po.order_value.sum():,.2f}</b>.</p>
<h3>By supplier</h3><ul>{sup}</ul>
<table border="1" cellpadding="6" style="border-collapse:collapse">
<tr style="background:#1F3A5F;color:#fff"><th>SKU</th><th>Item</th><th>Days cover</th>
<th>Lead time</th><th>Order qty</th><th>Value</th></tr>{rows}</table>
<p>Full detail in the attached workbook.</p></body></html>"""
    path.write_text(html, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items")
    ap.add_argument("--usage")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    if a.items and a.usage:
        items, usage = pd.read_csv(a.items), pd.read_csv(a.usage)
    else:
        items, usage = make_demo_data()
        items.to_csv(OUT / "demo_items.csv", index=False)
        usage.to_csv(OUT / "demo_usage.csv", index=False)
    df = calculate(items, usage)
    build_workbook(df, OUT / "reorder_dashboard.xlsx")
    build_email(df, OUT / "weekly_reorder_email.html")
    print(df[["sku", "on_hand", "reorder_point", "days_of_cover", "order_qty", "status"]]
          .to_string(index=False))
    print(f"\nSuggested PO value: ${df.order_value.sum():,.2f}")


if __name__ == "__main__":
    main()
