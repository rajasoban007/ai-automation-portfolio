"""Generate a small labelled dataset of synthetic supplier emails (demo data, not real)."""
import json
import random
from datetime import date, timedelta
from pathlib import Path

SUPPLIERS = ["Lahore Paper House", "ColorTech Supplies", "BindRight Traders", "PlateMakers Co.", "PackLine Cartons"]
TEMPLATES = [
    "Hi team,\nConfirming your order {po} for {qty} units. Expected delivery on {d1}.\nRegards,\n{sup}",
    "Dear buyer, we have received PO {po}. Quantity: {qty}. We will dispatch so it reaches you by {d2}. - {sup} accounts",
    "Re: order {po}\nThanks for the order. {qty} pcs are being packed and should arrive {d3}.\nBest, {sup}",
    "{sup} here. Your purchase order no. {po} ({qty} items) is confirmed; delivery date {d1}.",
    "Hello! Quick update on PO#{po}: we can supply {qty} units, delivery {d2}. Kind regards from the {sup} sales desk.",
]


def main(n=15, seed=3):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        sup, po, qty = rng.choice(SUPPLIERS), f"PO-{2300 + i}", rng.choice([50, 120, 200, 500, 1000])
        d = date(2026, 12, 1) + timedelta(days=rng.randint(0, 40))
        text = rng.choice(TEMPLATES).format(
            sup=sup, po=po, qty=qty, d1=d.strftime("%d/%m/%Y"), d2=d.strftime("%B %d, %Y"), d3=d.strftime("%d %b %Y"))
        rows.append({"id": i, "text": text,
                     "gold": {"supplier": sup, "po_number": po, "quantity": qty, "delivery_date": d.isoformat()}})
    out = Path(__file__).parent / "dataset.json"
    out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(out, len(rows))


if __name__ == "__main__":
    main()
