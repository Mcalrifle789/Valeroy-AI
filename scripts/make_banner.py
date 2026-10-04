"""Regenerate frontend/valeroy_tui/banner.py from assets/valeroy-logo.png.

Decodes the PNG with the standard library only, crops to the wordmark,
downsamples into terminal half-block cells (centre-sampled), maps each pixel
to the nearest xterm-256 colour - dark/plum pixels become "theme base" so the
banner blends with any theme - and writes run-length-encoded Python data.

Usage:  python scripts/make_banner.py   # no options; emits two scales
"""

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGO = ROOT / "assets" / "valeroy-logo.png"
OUT = ROOT / "frontend" / "valeroy_tui" / "banner.py"

BG_LUM = 48   # luminance below this counts as logo background
              # (measured: plum background ~23-35, diluted strokes 55+)
WIDE_CELLS = 110
NARROW_CELLS = 72


# --------------------------------------------------------------------------- #
# Minimal PNG decoder (8-bit, RGB / RGBA / greyscale, no interlace)
# --------------------------------------------------------------------------- #

def read_png(path: Path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos, idat = 8, b""
    while pos < len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            w, h, bitd, color, _comp, _filt, inter = struct.unpack(">IIBBBBB", chunk)
            assert bitd == 8 and inter == 0, "only 8-bit non-interlaced PNGs"
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
        pos += 12 + length
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    raw = zlib.decompress(idat)
    stride = w * channels
    out = bytearray()
    prev = bytearray(stride)
    i = 0
    for _ in range(h):
        ftype = raw[i]
        i += 1
        line = bytearray(raw[i:i + stride])
        i += stride
        if ftype == 1:
            for x in range(channels, stride):
                line[x] = (line[x] + line[x - channels]) & 255
        elif ftype == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif ftype == 3:
            for x in range(stride):
                a = line[x - channels] if x >= channels else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 255
        elif ftype == 4:
            for x in range(stride):
                a = line[x - channels] if x >= channels else 0
                b = prev[x]
                c = prev[x - channels] if x >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 255
        out += line
        prev = line
    return w, h, channels, bytes(out)


W, H, CH, PIX = read_png(LOGO)


def pixel(x: int, y: int):
    o = (y * W + x) * CH
    r, g, b = PIX[o], PIX[o + 1], PIX[o + 2]
    if CH == 4 and PIX[o + 3] < 128:
        return 0, 0, 0
    return r, g, b


# --------------------------------------------------------------------------- #
# xterm-256 palette + nearest lookup
# --------------------------------------------------------------------------- #

def xterm_rgb(i: int):
    if i < 16:
        base = [(0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238),
                (205, 0, 205), (0, 205, 205), (229, 229, 229), (127, 127, 127),
                (255, 0, 0), (0, 255, 0), (255, 255, 0), (92, 92, 255),
                (255, 0, 255), (0, 255, 255), (255, 255, 255)]
        return base[i]
    if i < 232:
        v = i - 16
        r, g, b = v // 36, (v // 6) % 6, v % 6
        lev = lambda c: 0 if c == 0 else 55 + c * 40
        return lev(r), lev(g), lev(b)
    g = 8 + (i - 232) * 10
    return g, g, g


PALETTE = [xterm_rgb(i) for i in range(256)]


def nearest(r: int, g: int, b: int) -> int:
    best, best_d = 0, 1 << 30
    for i, (pr, pg, pb) in enumerate(PALETTE):
        d = 2 * (r - pr) ** 2 + 4 * (g - pg) ** 2 + 3 * (b - pb) ** 2
        if d < best_d:
            best, best_d = i, d
    return best


def lum(r: int, g: int, b: int) -> float:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# --------------------------------------------------------------------------- #
# Crop: find the wordmark band by row profile of bright pixels
# --------------------------------------------------------------------------- #

STEP = 4
prof = [sum(1 for x in range(0, W, STEP) if lum(*pixel(x, y)) > 110) * STEP
        for y in range(H)]
thr = W * 0.04
bands = []
start = last_bright = None
for y, c in enumerate(prof):
    if c > thr:
        if start is None:
            start = y
        last_bright = y
    elif start is not None and y - last_bright > 6:
        bands.append((start, last_bright))
        start = None
if start is not None:
    bands.append((start, last_bright))
assert bands, "no bright content found"
# Tallest band is the wordmark; absorb nearby bands (letter flourishes such as
# the V serif and the y tail) within 30 rows of it.
main = max(bands, key=lambda b: b[1] - b[0])
b_top, b_bot = main
for a, b in bands:
    if b < b_top and b_top - b <= 30:
        b_top = a
    if a > b_bot and a - b_bot <= 30:
        b_bot = b

ys_rows = range(max(0, b_top - 4), min(H, b_bot + 5))

# Column profile inside the wordmark band, to reject the decorative arcs that
# cross the full image width.
prof_x = [sum(1 for y in ys_rows if lum(*pixel(x, y)) > 110) for x in range(W)]
xthr = (b_bot - b_top) * 0.04
xbands = []
xstart = xlast = None
for x, c in enumerate(prof_x):
    if c > xthr:
        if xstart is None:
            xstart = x
        xlast = x
    elif xstart is not None and x - xlast > 24:
        xbands.append((xstart, xlast))
        xstart = None
if xstart is not None:
    xbands.append((xstart, xlast))
xbands = [(a, b) for a, b in xbands if b - a > 20]
assert xbands, "no wordmark columns found"
xs = [x for a, b in xbands for x in (a, b)]
x0, x1 = max(0, min(xs) - 8), min(W, max(xs) + 9)
y0, y1 = max(0, b_top - 4), min(H, b_bot + 5)
cw, chh = x1 - x0, y1 - y0
print(f"crop: x {x0}..{x1}  y {y0}..{y1}  ({cw}x{chh})")


# --------------------------------------------------------------------------- #
# Downsample into half-block cells (centre-sampled, 1 cell = 1x2 source pixels)
# --------------------------------------------------------------------------- #

def classify(r: int, g: int, b: int):
    """Map a pixel to a palette index, or None for logo background."""
    if lum(r, g, b) < BG_LUM:
        return None
    idx = nearest(r, g, b)
    # Near-grey indices are plum background bleeding through - treat as bg.
    if 232 <= idx <= 240:
        return None
    return idx


def gen(width: int):
    """Downsample the crop to `width` cells; returns (w, h, encoded rows)."""
    cells_w = min(width, cw)
    lsx = cw / cells_w
    cells_h = max(1, round(chh / lsx / 2))
    lsy = chh / (cells_h * 2)

    def cell_box(cx: int, cy: int):
        # Centre-point sampling: averaging over the block dilutes thin serif
        # strokes into mud at this scale; the centre pixel is representative.
        xx = min(W - 1, x0 + int((cx + 0.5) * lsx))
        yy = min(H - 1, y0 + int((cy + 0.5) * lsy))
        return pixel(xx, yy)

    grid = []  # (fg_index or None, bg_index or None) per cell
    for cy in range(cells_h):
        for cx in range(cells_w):
            top = classify(*cell_box(cx, cy * 2))
            bot = classify(*cell_box(cx, cy * 2 + 1))
            grid.append((top, bot))

    # Despeckle: drop gold cells with no gold neighbour (background texture
    # noise); two passes so pairs of stray pixels go too.
    def gold(cx, cy):
        if not (0 <= cx < cells_w and 0 <= cy < cells_h):
            return False
        fg, bg = grid[cy * cells_w + cx]
        return fg is not None or bg is not None

    for _ in range(2):
        drop = []
        for cy in range(cells_h):
            for cx in range(cells_w):
                if not gold(cx, cy):
                    continue
                neigh = sum(gold(cx + dx, cy + dy)
                            for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                            if dx or dy)
                if neigh == 0:
                    drop.append((cx, cy))
        for cx, cy in drop:
            grid[cy * cells_w + cx] = (None, None)

    rows = []
    for cy in range(cells_h):
        runs = []
        run_start = 0
        for cx in range(1, cells_w + 1):
            if cx == cells_w or grid[cy * cells_w + cx] != grid[cy * cells_w + run_start]:
                fg, bg = grid[cy * cells_w + run_start]
                text = "\u2580" * (cx - run_start)
                # Every run carries its column offset so drawing can skip over
                # background stretches; all-None runs act as spacers.
                runs.append((run_start, text, fg, bg))
                run_start = cx
        rows.append(runs)
    return cells_w, cells_h, rows


WIDE_W, WIDE_H, WIDE = gen(WIDE_CELLS)
NARROW_W, NARROW_H, NARROW = gen(NARROW_CELLS)
used = sorted({i for row in (WIDE + NARROW) for _, _, i, _ in row if i is not None})
print(f"wide: {WIDE_W}x{WIDE_H}  narrow: {NARROW_W}x{NARROW_H}  palette: {used}")


# --------------------------------------------------------------------------- #
# Emit banner.py
# --------------------------------------------------------------------------- #

def lit(v):
    return "None" if v is None else str(v)


def emit(name: str, width: int, height: int, rows) -> list[str]:
    out = [f"{name}_WIDTH = {width}", f"{name}_HEIGHT = {height}",
           f"{name}: list[list[tuple[int, str, int | None, int | None]]] = ["]
    for runs in rows:
        if not runs:
            out.append("    [],")
            continue
        parts = [f"({x}, {t!r}, {lit(fg)}, {lit(bg)})" for x, t, fg, bg in runs]
        out.append("    [" + ", ".join(parts) + "],")
    out.append("]")
    return out


lines = [
    '"""Pixelized Valeroy AI logo for the TUI header.',
    "",
    "Generated by scripts/make_banner.py from assets/valeroy-logo.png - do not",
    "edit by hand. Each row is a list of (x, text, fg, bg) runs of upper-half-",
    "block characters (\\u2580); fg is the top pixel colour, bg the bottom pixel",
    "colour, as xterm-256 indices. None means 'theme base', so the banner blends",
    "with whatever theme is active. Runs with both colours None are background",
    "spacers - skip drawing them, but use x to stay aligned.",
    "",
    "Two scales are precomputed: WIDE (needs a ~120-column terminal) and NARROW",
    "(fits ~84 columns). pick() chooses the largest one that fits.",
    '"""',
    "",
]
lines += emit("WIDE", WIDE_W, WIDE_H, WIDE)
lines.append("")
lines += emit("NARROW", NARROW_W, NARROW_H, NARROW)
lines += [
    "",
    'TAGLINE = "\\u2726 agentic royalty \\u2726"',
    "",
    "",
    "def pick(cols: int):",
    '    """Choose (rows, width, height) for the available columns, or None."""',
    "    if cols >= WIDE_WIDTH + 10:",
    "        return WIDE, WIDE_WIDTH, WIDE_HEIGHT",
    "    if cols >= NARROW_WIDTH + 10:",
    "        return NARROW, NARROW_WIDTH, NARROW_HEIGHT",
    "    return None",
    "",
    "",
    "def height_for(cols: int) -> int:",
    '    """Rows the banner will occupy at this terminal width (0 if hidden)."""',
    "    picked = pick(cols)",
    "    return (picked[2] + 1) if picked else 0  # + one tagline row",
    "",
    "",
    "def draw(surface, cols: int, y0: int, theme) -> None:",
    '    """Draw the banner centred at y0; background cells stay theme.base."""',
    "    picked = pick(cols)",
    "    if picked is None:",
    "        return",
    "    rows, width, _height = picked",
    "    x_off = (cols - width) // 2",
    "    for i, runs in enumerate(rows):",
    "        for x, text, fg, bg in runs:",
    "            if fg is None and bg is None:",
    "                continue  # background spacer - surface is already base",
    "            surface.put(x_off + x, y0 + i, text,",
    "                        fg=theme.base if fg is None else fg,",
    "                        bg=theme.base if bg is None else bg)",
    "    tag = TAGLINE",
    "    surface.put((cols - len(tag)) // 2, y0 + len(rows), tag,",
    "                fg=theme.accent, bg=theme.base)",
    "",
]
OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")