"""Shared 4:3 portfolio cover renderer (Pillow only): header, KPI tiles, status table, footer."""
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Set COVER_FONT to a .ttf path (e.g. Inter); falls back to Pillow's built-in font.
FONT = os.environ.get("COVER_FONT", "Inter-Variable.ttf")
NAVY, INK, MUTED, BG, CARD, LINE = "#1F3A5F", "#1B1F24", "#6B7280", "#F4F6F9", "#FFFFFF", "#E3E7ED"
COLORS = {"red": "#D9534F", "amber": "#E8A33D", "green": "#3FA37A", "navy": NAVY, "ink": INK}
BADGE = {"red": ("#FBE3E2", "#B23B37"), "amber": ("#FCEFD9", "#9A6512"),
         "green": ("#DDF2E8", "#23764F"), "grey": ("#ECEFF3", "#4B5563")}


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


def fit(d, text, fnt, max_w):
    if d.textlength(text, font=fnt) <= max_w:
        return text
    while text and d.textlength(text + "…", font=fnt) > max_w:
        text = text[:-1]
    return text + "…"


def render_cover(out: Path, title: str, subtitle: str, kpis, table_title: str, columns, rows,
                 footer: str, author: str = "Soban Farooq"):
    """kpis: [(label, value, color)], columns: [(header, width_px)],
    rows: [[cell, ...]] where a cell is str or (text, badge_color)."""
    W, H = 1600, 1200
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 150], fill=NAVY)
    d.text((60, 38), title, font=font(54, 700), fill="white")
    d.text((62, 104), subtitle, font=font(26), fill="#C9D6E8")

    n = len(kpis)
    gap, x = 26, 60
    w = (W - 120 - gap * (n - 1)) // n
    for label, val, col in kpis:
        d.rounded_rectangle([x, 190, x + w, 340], 18, fill=CARD, outline=LINE, width=2)
        d.text((x + 28, 214), label, font=font(26, 500), fill=MUTED)
        d.text((x + 28, 252), fit(d, str(val), font(56, 700), w - 50), font=font(56, 700),
               fill=COLORS.get(col, col))
        x += w + gap

    top = 380
    d.rounded_rectangle([60, top, W - 60, H - 110], 18, fill=CARD, outline=LINE, width=2)
    d.text((95, top + 26), table_title, font=font(30, 600), fill=INK)
    y = top + 90
    x = 95
    for head, cw in columns:
        d.text((x, y), head, font=font(22, 600), fill=MUTED)
        x += cw
    y += 40
    d.line([95, y - 8, W - 95, y - 8], fill=LINE, width=2)
    for row in rows:
        x = 95
        for (head, cw), cell in zip(columns, row):
            if isinstance(cell, tuple):
                text, colr = cell
                bg, fg = BADGE[colr]
                f = font(20, 600)
                tw = d.textlength(text, font=f)
                d.rounded_rectangle([x, y - 4, x + tw + 24, y + 30], 14, fill=bg)
                d.text((x + 12, y), text, font=f, fill=fg)
            else:
                d.text((x, y), fit(d, str(cell), font(22), cw - 20), font=font(22), fill=INK)
            x += cw
        y += 56
        if y > H - 150:
            break

    d.text((60, H - 80), footer, font=font(24, 500), fill=MUTED)
    d.text((W - 60 - d.textlength(author, font=font(26, 700)), H - 80), author,
           font=font(26, 700), fill=NAVY)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, optimize=True)
    return out
