"""Render the Market Pulse card PNG with Pillow (matches the existing card's look)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W = 1280
PAD = 50
ROW_H = 78
GOLD = (198, 167, 106)
INK = (26, 26, 26)
GREY = (120, 120, 120)
RULE = (232, 232, 232)
DARK_RULE = (40, 40, 40)
GREEN = (46, 125, 50)
RED = (198, 40, 40)
MUTED = (170, 170, 170)

_FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/truetype/roboto", "/System/Library/Fonts", "C:/Windows/Fonts",
]
_CANDIDATES = {
    "regular": ["Roboto-Regular.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf", "Helvetica.ttc", "arial.ttf"],
    "bold": ["Roboto-Bold.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf", "Helvetica.ttc", "arialbd.ttf"],
    "italic": ["Roboto-Italic.ttf", "LiberationSans-Italic.ttf", "DejaVuSans-Oblique.ttf", "Helvetica.ttc", "ariali.ttf"],
}


def _font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for d in _FONT_DIRS:
        for name in _CANDIDATES[kind]:
            p = Path(d) / name
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), size)
                except OSError:
                    continue
    return ImageFont.load_default()


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    return draw.textlength(text, font=font)


def _section_header(draw, y: int, title: str, subtitle: str | None = None) -> int:
    f = _font("bold", 24)
    spaced = "  ".join(title.upper())
    w = _text_w(draw, spaced, f)
    draw.text(((W - w) / 2, y), spaced, fill=GREY, font=f)
    y += 36
    if subtitle:
        fi = _font("italic", 20)
        w = _text_w(draw, subtitle, fi)
        draw.text(((W - w) / 2, y), subtitle, fill=GREY, font=fi)
        y += 30
    draw.line([(PAD, y + 8), (W - PAD, y + 8)], fill=DARK_RULE, width=2)
    return y + 24


def _row(draw, y: int, row: dict, sub_font, ticker_style: bool = False, cost: bool = False) -> int:
    """cost=True flips the colors: a rising input cost (crude, rates, freight) is red,
    a falling one is green. Equities keep the conventional green-up / red-down."""
    fb = _font("bold", 30)
    fr = _font("regular", 30)
    fs = _font("regular", 24)
    x = PAD + 10
    if ticker_style:
        draw.text((x, y + 18), row["label"], fill=INK, font=fb)
        x2 = x + _text_w(draw, row["label"], fb) + 12
        draw.text((x2, y + 24), row.get("sub", ""), fill=GREY, font=fs)
    else:
        draw.text((x, y + 18), row["label"], fill=INK, font=fb)
    # value, right-aligned in a column ending at 70% width
    vx = int(W * 0.70)
    vw = _text_w(draw, row["value_text"], fr)
    draw.text((vx - vw, y + 18), row["value_text"], fill=INK, font=fr)
    # change, right-aligned
    ch = row["change_text"]
    d = row["direction"]
    if cost:
        color = RED if d == "up" else GREEN if d == "down" else MUTED
    else:
        color = GREEN if d == "up" else RED if d == "down" else MUTED
    arrow = "▲ " if d == "up" else "▼ " if d == "down" else ""
    text = f"{arrow}{ch}"
    cw = _text_w(draw, text, fb)
    draw.text((W - PAD - 10 - cw, y + 18), text, fill=color, font=fb)
    draw.line([(PAD, y + ROW_H), (W - PAD, y + ROW_H)], fill=RULE, width=1)
    return y + ROW_H


def render_card(market: dict, out_path: Path) -> Path:
    n_rows = len(market["markets"]) + len(market["container"]) + len(market["stocks"])
    height = 60 + 3 * 90 + n_rows * ROW_H + 120
    img = Image.new("RGB", (W, height), "white")
    draw = ImageDraw.Draw(img)
    # gold border
    draw.rounded_rectangle([(6, 6), (W - 7, height - 7)], radius=18, outline=GOLD, width=3)

    y = 40
    y = _section_header(draw, y, market.get("inputs_title", "Inputs"))
    for r in market["markets"]:
        y = _row(draw, y, r, None, cost=True)
    y += 30
    y = _section_header(draw, y, market.get("container_title", "Container Spot Rates"),
                        market.get("container_subtitle"))
    for r in market["container"]:
        y = _row(draw, y, r, None, cost=True)
    y += 30
    y = _section_header(draw, y, "Furniture & Bedding")
    for r in market["stocks"]:
        y = _row(draw, y, r, None, ticker_style=True)

    fi = _font("italic", 22)
    note = f"Data as of previous market close ({market.get('as_of', '')}). Weekly series show — when unchanged."
    draw.text((PAD, height - 60), note, fill=GREY, font=fi)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path
