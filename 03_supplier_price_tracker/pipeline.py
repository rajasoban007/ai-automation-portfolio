"""
DEMO PROJECT (sample data) - Supplier price tracker / data pipeline.

Each run ingests the latest supplier price lists (CSV, Excel, JSON API export - each in its
own format and currency), maps supplier codes to internal SKUs, converts to USD, stores the
snapshot in SQLite, and reports price changes, alerts and the cheapest supplier per SKU.

Usage:
    python pipeline.py                 # ingest every snapshot folder in ./samples, then report
    python pipeline.py --threshold 5   # alert on moves of 5% or more
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
PKR_PER_USD = 280.0  # demo constant; production pulls a daily rate from the client's chosen source

# supplier code -> internal SKU (in production this lives in a mapping sheet the client edits)
SKU_MAP = {
    "LPH-A4-80": "PAPER-80G-A4", "P80A4": "PAPER-80G-A4", "GL-0080-A4": "PAPER-80G-A4",
    "LPH-INK-C": "INK-CYAN-1KG", "INKC1": "INK-CYAN-1KG", "GL-INK-CY": "INK-CYAN-1KG",
    "CTPA1": "PLATE-CTP-A1", "GL-CTP-A1": "PLATE-CTP-A1",
    "LPH-PUR5": "GLUE-PUR-5KG", "GL-PUR-05": "GLUE-PUR-5KG",
    "CTN-L": "CARTON-L-25", "GL-CTN-L25": "CARTON-L-25",
}


# ------------------------------------------------------------------ extract + transform
def load_lahore_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    return pd.DataFrame({"supplier": "Lahore Paper House (Sample)", "supplier_code": df["Item Code"],
                         "description": df["Description"], "price_usd": df["Price USD"].astype(float)})


def load_market_xlsx(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path)
    return pd.DataFrame({"supplier": "Market Traders (Sample)", "supplier_code": df["Code"],
                         "description": df["Item"],
                         "price_usd": (df["Rate (PKR)"].astype(float) / PKR_PER_USD).round(2)})


def load_global_json(path: Path) -> pd.DataFrame:
    data = json.loads(path.read_text())
    if data.get("currency") != "USD":
        raise ValueError(f"{path.name}: unexpected currency {data.get('currency')}")
    df = pd.DataFrame(data["items"])
    return pd.DataFrame({"supplier": data["supplier"], "supplier_code": df["sku"],
                         "description": df["title"], "price_usd": df["unit_price"].astype(float)})


LOADERS = {"lahore_paper_house.csv": load_lahore_csv, "market_traders.xlsx": load_market_xlsx,
           "global_print_supply.json": load_global_json}


def transform(folder: Path) -> tuple[pd.DataFrame, list[str]]:
    frames, warnings = [], []
    for name, loader in LOADERS.items():
        p = folder / name
        if not p.exists():
            warnings.append(f"{folder.name}: missing {name}")
            continue
        frames.append(loader(p))
    df = pd.concat(frames, ignore_index=True)
    df["sku"] = df["supplier_code"].map(SKU_MAP)
    for code in df.loc[df["sku"].isna(), "supplier_code"]:
        warnings.append(f"{folder.name}: unmapped supplier code {code}")
    df = df.dropna(subset=["sku"])
    bad = df["price_usd"] <= 0
    warnings += [f"{folder.name}: non-positive price for {c}" for c in df.loc[bad, "supplier_code"]]
    df = df[~bad]
    df["snapshot"] = folder.name
    return df, warnings


# ------------------------------------------------------------------ load
def connect(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE IF NOT EXISTS prices (
        snapshot TEXT, supplier TEXT, supplier_code TEXT, sku TEXT, description TEXT, price_usd REAL,
        PRIMARY KEY (snapshot, supplier, supplier_code))""")
    return con


def load(con: sqlite3.Connection, df: pd.DataFrame) -> int:
    rows = df[["snapshot", "supplier", "supplier_code", "sku", "description", "price_usd"]].itertuples(index=False)
    cur = con.executemany("INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?)", list(rows))
    con.commit()
    return cur.rowcount


# ------------------------------------------------------------------ report
def analyse(con: sqlite3.Connection, threshold_pct: float = 5.0) -> dict[str, pd.DataFrame]:
    hist = pd.read_sql("SELECT * FROM prices ORDER BY snapshot", con)
    snaps = sorted(hist["snapshot"].unique())
    latest, prev = snaps[-1], (snaps[-2] if len(snaps) > 1 else None)
    cur = hist[hist.snapshot == latest]
    changes = pd.DataFrame()
    if prev:
        old = hist[hist.snapshot == prev][["supplier", "sku", "price_usd"]].rename(columns={"price_usd": "prev_usd"})
        changes = cur.merge(old, on=["supplier", "sku"], how="left")
        changes["change_pct"] = ((changes.price_usd / changes.prev_usd - 1) * 100).round(1)
        changes = changes.sort_values("change_pct", key=abs, ascending=False)
    alerts = changes[changes["change_pct"].abs() >= threshold_pct] if not changes.empty else changes
    best = (cur.sort_values("price_usd").groupby("sku", as_index=False).first()
            [["sku", "supplier", "price_usd"]].rename(columns={"supplier": "cheapest_supplier",
                                                               "price_usd": "best_usd"}))
    spread = cur.groupby("sku")["price_usd"].agg(["min", "max"]).reset_index()
    best = best.merge(spread, on="sku")
    best["saving_vs_dearest_pct"] = ((1 - best["min"] / best["max"]) * 100).round(1)
    trend = hist.pivot_table(index=["sku", "supplier"], columns="snapshot", values="price_usd").reset_index()
    return {"latest": pd.DataFrame({"snapshot": [latest], "previous": [prev]}),
            "changes": changes, "alerts": alerts, "best": best.drop(columns=["min", "max"]), "trend": trend}


def write_report(res: dict[str, pd.DataFrame], out: Path) -> dict[str, Path]:
    out.mkdir(exist_ok=True)
    xlsx = out / "price_report.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
        res["alerts"].to_excel(xw, sheet_name="Alerts", index=False)
        res["best"].to_excel(xw, sheet_name="Cheapest Supplier", index=False)
        res["changes"].to_excel(xw, sheet_name="All Changes", index=False)
        res["trend"].to_excel(xw, sheet_name="Price History", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(
                    45, max(len(str(c.value or "")) for c in col) + 2)
            ws.freeze_panes = "A2"
    a = res["alerts"]
    rows = "".join(f"<tr><td>{r.sku}</td><td>{r.supplier}</td><td>${r.prev_usd:,.2f}</td>"
                   f"<td>${r.price_usd:,.2f}</td><td>{r.change_pct:+.1f}%</td></tr>" for r in a.itertuples())
    html = out / "price_alert_email.html"
    html.write_text(f"""<html><body style="font-family:Segoe UI,Arial">
<p style="color:#888"><i>Demo project - sample data</i></p>
<h2 style="color:#1F3A5F">Supplier price alert - {res['latest'].snapshot[0]}</h2>
<p>{len(a)} price move(s) at or above the alert threshold since {res['latest'].previous[0]}.</p>
<table border="1" cellpadding="6" style="border-collapse:collapse"><tr style="background:#1F3A5F;color:#fff">
<th>SKU</th><th>Supplier</th><th>Was</th><th>Now</th><th>Change</th></tr>{rows}</table></body></html>""",
                    encoding="utf-8")
    return {"xlsx": xlsx, "html": html}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--samples", type=Path, default=HERE / "samples")
    ap.add_argument("--db", type=Path, default=HERE / "output" / "prices.sqlite")
    ap.add_argument("--threshold", type=float, default=5.0)
    a = ap.parse_args()
    a.db.parent.mkdir(exist_ok=True)
    con = connect(a.db)
    for folder in sorted(p for p in a.samples.iterdir() if p.is_dir()):
        df, warns = transform(folder)
        n = load(con, df)
        print(f"{folder.name}: {n} prices loaded" + (f"  warnings: {warns}" if warns else ""))
    res = analyse(con, a.threshold)
    paths = write_report(res, a.db.parent)
    print(res["alerts"][["sku", "supplier", "prev_usd", "price_usd", "change_pct"]].to_string(index=False))
    print(f"\nReport: {paths['xlsx']}\nEmail:  {paths['html']}")


if __name__ == "__main__":
    main()
