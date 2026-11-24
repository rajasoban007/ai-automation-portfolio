"""Render a 4:3 portfolio cover image from the demo output (Pillow only)."""
import os
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

import reorder_report as rr

HERE = Path(__file__).parent
# Set COVER_FONT to a .ttf path (e.g. Inter); falls back to Pillow's built-in font.
FONT = os.environ.get("COVER_FONT", "Inter-Variable.ttf")
NAVY, INK, MUTED, BG, CARD = "#1F3A5F", "#1B1F24", "#6B7280", "#F4F6F9", "#FFFFFF"
RED, AMBER, BLUE, GREEN = "#D9534F", "#E8A33D", "#3B82C4", "#3FA37A"


def font(size, weight=400):
    try:
        f = ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default(size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


def main():
    items = pd.read_csv(HERE / "output" / "demo_items.csv")
    usage = pd.read_csv(HERE / "output" / "demo_usage.csv")
    df = rr.calculate(items, usage)

    W, H = 1600, 1200
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 150], fill=NAVY)
    d.text((60, 38), "Inventory Reorder Automation", font=font(54, 700), fill="white")
    d.text((62, 104), "Safety stock · reorder points · draft POs by supplier · weekly email",
           font=font(26, 400), fill="#C9D6E8")

    kpis = [("SKUs tracked", f"{len(df)}", INK),
            ("Urgent", f"{(df.status == 'URGENT').sum()}", RED),
            ("To reorder", f"{(df.order_qty > 0).sum()}", AMBER),
            ("Suggested PO", f"${df.order_value.sum():,.0f}", NAVY)]
    x, y, w, h, gap = 60, 190, 350, 150, 26
    for label, val, col in kpis:
        d.rounded_rectangle([x, y, x + w, y + h], 18, fill=CARD, outline="#E3E7ED", width=2)
        d.text((x + 28, y + 24), label, font=font(26, 500), fill=MUTED)
        d.text((x + 28, y + 62), val, font=font(60, 700), fill=col)
        x += w + gap

    # bar chart: days of cover vs lead time
    cy0 = 380
    d.rounded_rectangle([60, cy0, W - 60, H - 110], 18, fill=CARD, outline="#E3E7ED", width=2)
    d.text((95, cy0 + 26), "Days of stock cover vs supplier lead time", font=font(30, 600), fill=INK)
    lx = 95
    for txt, col in (("Cover OK", GREEN), ("Urgent", RED), ("Lead time", MUTED)):
        d.rectangle([lx, cy0 + 80, lx + 22, cy0 + 102], fill=col)
        d.text((lx + 32, cy0 + 76), txt, font=font(22), fill=MUTED)
        lx += 190
    rows = df.sort_values("days_of_cover").head(8)
    top, left, right = cy0 + 130, 360, W - 140
    maxv = max(rows.days_of_cover.max(), rows.lead_time_days.max()) * 1.1
    bh = 52
    for i, r in enumerate(rows.itertuples()):
        yy = top + i * (bh + 14)
        d.text((95, yy + 12), r.sku, font=font(22, 500), fill=INK)
        bw = (right - left) * r.days_of_cover / maxv
        col = RED if r.status == "URGENT" else GREEN
        d.rounded_rectangle([left, yy, left + bw, yy + bh], 8, fill=col)
        lt = left + (right - left) * r.lead_time_days / maxv
        d.text((max(left + bw, lt) + 14, yy + 12), f"{r.days_of_cover:g} d", font=font(22, 600), fill=INK)
        d.line([lt, yy - 4, lt, yy + bh + 4], fill=INK, width=4)

    d.text((60, H - 80), "Demo project · sample data · Python + pandas + openpyxl",
           font=font(24, 500), fill=MUTED)
    d.text((W - 360, H - 80), "Soban Farooq", font=font(26, 700), fill=NAVY)
    out = HERE / "images" / "cover_4x3.png"
    im.save(out, optimize=True)
    print(out)


if __name__ == "__main__":
    main()
