"""Generate synthetic supplier invoices (PDF) for the demo. Not real companies or documents."""
from datetime import date, timedelta
from pathlib import Path

import pymupdf

HERE = Path(__file__).parent
SAMPLES = HERE / "samples"

TODAY = date.today()

# Each supplier uses a different layout / labels, like real inboxes do.
INVOICES = [
    {"file": "inv_lahore_paper_1041.pdf", "supplier": "Lahore Paper House (Sample)", "style": "A",
     "number": "LPH-1041", "date": TODAY - timedelta(days=6), "po": "PO-2207", "currency": "USD",
     "lines": [("Offset paper 80gsm A4 (ream)", 120, 6.10), ("Newsprint 70gsm 23x36 (ream)", 60, 9.40)],
     "tax_rate": 0.17},
    {"file": "inv_colortech_88.pdf", "supplier": "ColorTech Supplies (Sample)", "style": "B",
     "number": "CT-0088", "date": TODAY - timedelta(days=3), "po": "PO-2211", "currency": "USD",
     "lines": [("Offset ink cyan 1kg", 20, 11.50), ("Offset ink magenta 1kg", 20, 11.50),
               ("Offset ink black 1kg", 30, 9.80)], "tax_rate": 0.0},
    {"file": "inv_bindright_517.pdf", "supplier": "BindRight Traders (Sample)", "style": "C",
     "number": "BR-517", "date": TODAY - timedelta(days=12), "po": "", "currency": "USD",   # missing PO
     "lines": [("PUR binding glue 5kg", 10, 32.00), ("Wire-O binding spools", 8, 21.00)], "tax_rate": 0.05},
    {"file": "inv_platemakers_2290.pdf", "supplier": "PlateMakers Co. (Sample)", "style": "A",
     "number": "PM-2290", "date": TODAY - timedelta(days=1), "po": "PO-2215", "currency": "USD",
     "lines": [("CTP plate A1", 200, 7.20)], "tax_rate": 0.17, "total_override": 1702.40},  # math error
    {"file": "inv_colortech_88_resent.pdf", "supplier": "ColorTech Supplies (Sample)", "style": "B",
     "number": "CT-0088", "date": TODAY - timedelta(days=3), "po": "PO-2211", "currency": "USD",  # duplicate
     "lines": [("Offset ink cyan 1kg", 20, 11.50), ("Offset ink magenta 1kg", 20, 11.50),
               ("Offset ink black 1kg", 30, 9.80)], "tax_rate": 0.0},
    {"file": "inv_packline_77.pdf", "supplier": "PackLine Cartons (Sample)", "style": "C",
     "number": "PL-77", "date": TODAY - timedelta(days=9), "po": "PO-2209", "currency": "USD",
     "lines": [("Carton box large (25 pcs)", 40, 8.00), ("Shrink wrap roll", 12, 14.50)], "tax_rate": 0.05},
]

LABELS = {
    "A": {"title": "TAX INVOICE", "num": "Invoice No:", "date": "Invoice Date:", "po": "PO Number:",
          "datefmt": "%d/%m/%Y", "tax": "Sales Tax 17%:", "total": "Grand Total:"},
    "B": {"title": "INVOICE", "num": "Inv #", "date": "Date:", "po": "Purchase Order:",
          "datefmt": "%B %d, %Y", "tax": "Tax:", "total": "Amount Due:"},
    "C": {"title": "BILL", "num": "Bill Number:", "date": "Bill Date:", "po": "Your PO Ref:",
          "datefmt": "%Y-%m-%d", "tax": "GST 5%:", "total": "Total Due:"},
}


def money(x):
    return f"{x:,.2f}"


def render(inv):
    lab = LABELS[inv["style"]]
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4 points
    y = 60

    def put(text, x=50, size=10, font="helv"):
        nonlocal y
        page.insert_text((x, y), text, fontsize=size, fontname=font)

    put(inv["supplier"], size=16, font="hebo"); y += 18
    put("12 Industrial Estate, Sample City  |  accounts@example.com", size=9); y += 30
    put(lab["title"], size=14, font="hebo"); y += 24
    put(f"{lab['num']} {inv['number']}"); y += 15
    put(f"{lab['date']} {inv['date'].strftime(lab['datefmt'])}"); y += 15
    if inv["po"]:
        put(f"{lab['po']} {inv['po']}")
    y += 15
    put("Bill to: Sample Printing Co., Lahore"); y += 30

    header = f"{'Description':<34}{'Qty':>6}{'Unit Price':>13}{'Amount':>13}"
    put(header, font="cour", size=9); y += 6
    page.draw_line((50, y), (545, y)); y += 14
    subtotal = 0.0
    for desc, qty, unit in inv["lines"]:
        amt = round(qty * unit, 2)
        subtotal += amt
        put(f"{desc:<34}{qty:>6}{money(unit):>13}{money(amt):>13}", font="cour", size=9); y += 14
    y += 6
    page.draw_line((50, y), (545, y)); y += 16
    subtotal = round(subtotal, 2)
    tax = round(subtotal * inv["tax_rate"], 2)
    total = inv.get("total_override", round(subtotal + tax, 2))
    put(f"{'Subtotal:':<20}{inv['currency']} {money(subtotal):>12}", x=330, font="cour", size=9); y += 14
    put(f"{lab['tax']:<20}{inv['currency']} {money(tax):>12}", x=330, font="cour", size=9); y += 14
    put(f"{lab['total']:<20}{inv['currency']} {money(total):>12}", x=330, font="cour", size=10); y += 40
    put("SAMPLE DOCUMENT - generated for a portfolio demo. Not a real invoice.", size=8)
    out = SAMPLES / inv["file"]
    doc.save(out)
    doc.close()
    return out


def main():
    SAMPLES.mkdir(exist_ok=True)
    for inv in INVOICES:
        print(render(inv))


if __name__ == "__main__":
    main()
