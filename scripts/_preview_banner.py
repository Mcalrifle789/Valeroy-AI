"""Throwaway: reconstruct a PNG preview from the generated banner.py."""
import struct
import sys
import zlib

sys.path.insert(0, "frontend/valeroy_tui")
import banner  # noqa: E402


def xterm_rgb(i):
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


def render(rows, width, height, scale):
    base = xterm_rgb(233)  # theme base, stands in for None
    img_w = width * scale
    img_h = height * 2 * scale
    buf = bytearray()
    for runs in rows:
        row = [base] * width
        for x, text, fg, bg in runs:
            if fg is None and bg is None:
                continue
            top = xterm_rgb(fg) if fg is not None else base
            bot = xterm_rgb(bg) if bg is not None else base
            for i in range(len(text)):
                row[x + i] = (top, bot)
        for _ in range(scale):
            for cell in row:
                px = cell[0] if len(cell) == 2 else cell
                buf += bytes(px) * scale
        for _ in range(scale):
            for cell in row:
                px = cell[1] if len(cell) == 2 else cell
                buf += bytes(px) * scale
    return img_w, img_h, buf


def png(w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb[y * w * 3:(y + 1) * w * 3]) for y in range(h))
    comp = zlib.compress(raw, 9)
    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", comp) + chunk(b"IEND", b""))


which = sys.argv[1] if len(sys.argv) > 1 else "wide"
if which == "wide":
    rows, width, height = banner.WIDE, banner.WIDE_WIDTH, banner.WIDE_HEIGHT
else:
    rows, width, height = banner.NARROW, banner.NARROW_WIDTH, banner.NARROW_HEIGHT
w, h, buf = render(rows, width, height, 12)
name = f"build/banner_preview_{which}.png"
open(name, "wb").write(png(w, h, buf))
print(f"wrote {name} ({w}x{h})")