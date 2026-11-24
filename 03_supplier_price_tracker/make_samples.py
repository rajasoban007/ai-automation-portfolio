"""Generate 4 weekly snapshots of supplier price lists in mixed formats. Synthetic data."""
import json
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
SAMPLES = HERE / "samples"

# Same item, different supplier codes / names - like real life.
CATALOGUE = {
    "PAPER-80G-A4": {"base": 6.10, "names": {"lph": ("LPH-A4-80", "A4 Offset 80gsm Ream"),
                                              "mkt": ("P80A4", "Paper A4 80 GSM (500 sh)"),
                                              "glb": ("GL-0080-A4", "Offset Paper A4 80g")}},
    "INK-CYAN-1KG": {"base": 11.50, "names": {"lph": ("LPH-INK-C", "Cyan Offset Ink 1 kg"),
                                              "mkt": ("INKC1", "Ink Cyan 1KG Tin"),
                                              "glb": ("GL-INK-CY", "Process Cyan 1kg")}},
    "PLATE-CTP-A1": {"base": 7.20, "names": {"mkt": ("CTPA1", "CTP Plate A1"),
                                             "glb": ("GL-CTP-A1", "Thermal CTP Plate A1")}},
    "GLUE-PUR-5KG": {"base": 32.00, "names": {"lph": ("LPH-PUR5", "PUR Glue 5kg"),
                                              "glb": ("GL-PUR-05", "PUR Hotmelt 5 kg")}},
    "CARTON-L-25": {"base": 8.00, "names": {"mkt": ("CTN-L", "Large Carton x25"),
                                            "glb": ("GL-CTN-L25", "Carton Large (25)")}},
}
SUPPLIERS = {"lph": "Lahore Paper House (Sample)", "mkt": "Market Traders (Sample)",
             "glb": "Global Print Supply (Sample)"}


def main(seed=11):
    rng = random.Random(seed)
    start = date.today() - timedelta(weeks=3)
    factor = {(item, s): rng.uniform(0.95, 1.08) for item, v in CATALOGUE.items() for s in v["names"]}
    for w in range(4):
        snap = start + timedelta(weeks=w)
        folder = SAMPLES / snap.isoformat()
        folder.mkdir(parents=True, exist_ok=True)
        rows = {s: [] for s in SUPPLIERS}
        for item, v in CATALOGUE.items():
            for s, (code, name) in v["names"].items():
                drift = 1 + rng.uniform(-0.01, 0.015) * w
                if item == "PAPER-80G-A4" and s == "lph" and w == 3:
                    drift *= 1.12            # a real price jump to catch
                if item == "INK-CYAN-1KG" and s == "glb" and w == 3:
                    drift *= 0.90            # a price drop - new cheapest
                rows[s].append((code, name, round(v["base"] * factor[(item, s)] * drift, 2)))
        # lph sends CSV, mkt sends Excel (prices in PKR), glb exposes a JSON "API" export
        pd.DataFrame(rows["lph"], columns=["Item Code", "Description", "Price USD"]).to_csv(
            folder / "lahore_paper_house.csv", index=False)
        pd.DataFrame([(c, n, round(p * 280, 0)) for c, n, p in rows["mkt"]],
                     columns=["Code", "Item", "Rate (PKR)"]).to_excel(folder / "market_traders.xlsx", index=False)
        (folder / "global_print_supply.json").write_text(json.dumps({
            "supplier": SUPPLIERS["glb"], "currency": "USD", "as_of": snap.isoformat(),
            "items": [{"sku": c, "title": n, "unit_price": p} for c, n, p in rows["glb"]]}, indent=1))
        print(folder)


if __name__ == "__main__":
    main()
