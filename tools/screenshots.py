#!/usr/bin/env python3
"""Draw the docs' screenshots from the scenarios, so they never go stale.

  uv run --with pillow --with fonttools tools/screenshots.py
  (or: pip install pillow fonttools; python3 tools/screenshots.py)

Writes PNGs under docs/images/: every scenario at its own width, one
scenario across widths, and each column on its own. Each cell is drawn on a
grid as a terminal would, with block characters drawn as shapes so bars
meet without gaps. Clock times are in UTC, as in the snapshot tests.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ["TZ"] = "UTC"
os.environ["CLAUDE_STATUSLINE_DAY_START"] = "7"  # as the scenarios were written
time.tzset()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "statusline"))
import statusline as sl  # noqa: E402

from fontTools.ttLib import TTCollection, TTFont  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

# ---- look ----------------------------------------------------------------------
SIZE = 22
LINE = 1.36      # line height, in font sizes
PAD = 28
BG = (24, 25, 28)
FG = (221, 221, 216)
FRAME = (60, 62, 68)
DOTS = ((237, 106, 94), (245, 191, 79), (98, 197, 84))

# (path, index in a collection) in order of preference; the first that exists wins
MONO = [("/System/Library/Fonts/Menlo.ttc", 0), ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 0),
        ("/usr/share/fonts/TTF/DejaVuSansMono.ttf", 0)]
MONO_BOLD = [("/System/Library/Fonts/Menlo.ttc", 1), ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 0),
             ("/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf", 0)]
FALLBACK = [("/System/Library/Fonts/Apple Symbols.ttf", 0), ("/System/Library/Fonts/SFNSMono.ttf", 0),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0)]


def xterm(n):
    """RGB for a 256-colour index."""
    base = [(0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205), (0, 205, 205),
            (229, 229, 229), (127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0), (92, 92, 255),
            (255, 0, 255), (0, 255, 255), (255, 255, 255)]
    if n < 16:
        return base[n]
    if n < 232:
        n -= 16
        step = lambda v: 0 if v == 0 else 55 + v * 40
        return step(n // 36), step(n // 6 % 6), step(n % 6)
    v = 8 + (n - 232) * 10
    return v, v, v


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


DIM = mix(FG, BG, 0.5)


# ---- fonts -----------------------------------------------------------------------
class Face:
    """A font plus the characters it has, so a missing one falls back."""

    def __init__(self, path, index):
        self.font = ImageFont.truetype(path, SIZE, index=index)
        tt = TTCollection(path).fonts[index] if path.endswith(".ttc") else TTFont(path)
        self.has = set(tt.getBestCmap())


def first(choices):
    for path, index in choices:
        if Path(path).exists():
            return Face(path, index)
    sys.exit(f"no font found; tried {[p for p, _ in choices]}")


REGULAR, BOLD = first(MONO), first(MONO_BOLD)
FALLBACKS = [Face(p, i) for p, i in FALLBACK if Path(p).exists()]
CELL_W = round(REGULAR.font.getlength("M"))
CELL_H = round(SIZE * LINE)


def face_for(ch, bold):
    main = BOLD if bold else REGULAR
    if ord(ch) in main.has:
        return main
    return next((f for f in FALLBACKS if ord(ch) in f.has), main)


# ---- drawing ---------------------------------------------------------------------
EIGHTHS = {c: i + 1 for i, c in enumerate("▁▂▃▄▅▆▇█")}
SHADES = {"░": 0.25, "▒": 0.5, "▓": 0.7}


def block(draw, ch, x, y, color, bg):
    """Block elements as shapes, the way terminals draw them; False if `ch` isn't one."""
    w, h = CELL_W, CELL_H
    if ch in EIGHTHS:
        top = y + h - round(h * EIGHTHS[ch] / 8)
        draw.rectangle((x, top, x + w - 1, y + h - 1), fill=color)
    elif ch in SHADES:
        draw.rectangle((x, y, x + w - 1, y + h - 1), fill=mix(bg, color, SHADES[ch]))
    elif ch == "▕":
        draw.rectangle((x + w - max(2, w // 8), y, x + w - 1, y + h - 1), fill=color)
    elif ch == "▏":
        draw.rectangle((x, y, x + max(2, w // 8) - 1, y + h - 1), fill=color)
    elif ch == "┃":
        t = max(2, w // 5)
        draw.rectangle((x + (w - t) // 2, y, x + (w - t) // 2 + t - 1, y + h - 1), fill=color)
    else:
        return False
    return True


def style_colors(style):
    """(foreground, background or None, bold) for a segment's style."""
    if style is None:
        return FG, None, False
    if style == sl.DIM:
        return DIM, None, False
    if isinstance(style, tuple):  # ("bg", n): dark text on a coloured fill
        return (0, 0, 0), xterm(style[1]), True
    return xterm(style), None, False


def draw_lines(lines, cols=None, chrome=True):
    """An image of segment lines on a terminal-like grid, `cols` cells wide."""
    cols = cols or max(sl.width(l) for l in lines)
    top = 30 if chrome else 0
    img = Image.new("RGB", (cols * CELL_W + 2 * PAD, top + len(lines) * CELL_H + 2 * PAD), BG)
    d = ImageDraw.Draw(img)
    if chrome:
        d.rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=14, outline=FRAME, width=2)
        for i, color in enumerate(DOTS):
            cx, cy = PAD + i * 22, 22
            d.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=color)
    for row, line in enumerate(lines):
        y = top + PAD + row * CELL_H
        col = 0
        for text, style, _ in line:
            fg, bg, bold = style_colors(style)
            for ch in text:
                n = sl.cells(ch)
                if n == 0:
                    continue
                x = PAD + col * CELL_W
                if bg:
                    d.rectangle((x, y, x + n * CELL_W - 1, y + CELL_H - 1), fill=bg)
                if ch != " " and not block(d, ch, x, y, fg, bg or BG):
                    f = face_for(ch, bold)
                    d.text((x + n * CELL_W / 2, y + CELL_H / 2), ch, font=f.font, fill=fg, anchor="mm")
                col += n
    return img


def save(img, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)
    print(f"{path.relative_to(ROOT)}  {img.width}x{img.height}")


# ---- what to draw ------------------------------------------------------------------
def scenario(name):
    return json.loads((ROOT / "scenarios" / f"{name}.json").read_text())


def scenarios():
    return sorted((ROOT / "scenarios").glob("*.json"), key=lambda f: int(f.stem.split("-")[0]))


def columns(out):
    """Each column on its own, from the scenario that shows it best."""
    healthy = sl.build_model(scenario("1-healthy"))
    bad = sl.build_model(scenario("2-bad-day"))
    shots = {
        "tanks": sl.tanks(healthy),
        "repo": sl.repo_column(healthy),
        "ship": sl.ship_column(healthy),
        "ship-bad": sl.ship_column(bad),
        "session": sl.session_column(healthy, week=False, five=False),
        "week": sl.week_column(healthy),
        "week-bar": [sl.runway_line(healthy)],
        "system": sl.system_column(healthy),
        "system-bad": sl.system_column(bad),
        "alerts": [sl.alerts_line(bad)],
    }
    for name, lines in shots.items():
        save(draw_lines(lines, chrome=False), out / "columns" / f"{name}.png")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(ROOT / "docs" / "images"))
    out = Path(ap.parse_args(argv).out)

    hero = scenario("1-healthy")
    save(draw_lines(sl.render_lines(hero, 240), 240), out / "hero.png")
    for f in scenarios():
        inp = json.loads(f.read_text())
        save(draw_lines(sl.render_lines(inp, inp["columns"]), inp["columns"]), out / "scenarios" / f"{f.stem}.png")
    for w in (80, 120, 160, 200, 240):
        save(draw_lines(sl.render_lines(hero, w), w), out / "widths" / f"healthy-{w}.png")
    columns(out)


if __name__ == "__main__":
    main(sys.argv[1:])
