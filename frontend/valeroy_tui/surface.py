"""Drawing surface for the TUI.

Wraps the C++ render accelerator (``frontend/cpp/vtui_render.cpp``), which keeps
a styled cell grid and emits only the cells that changed since the last flush.
That diffing is what keeps the screen from flickering while tokens stream in.

When the native library has not been built, :class:`PythonSurface` provides the
same interface in pure Python.
"""

from __future__ import annotations

import ctypes
from typing import Protocol

from valeroy_backend import native

# Attribute bits, mirroring vtui_render.h
BOLD = 0x01
DIM = 0x02
ITALIC = 0x04
UNDERLINE = 0x08
REVERSE = 0x10


class Surface(Protocol):
    """What the app draws onto."""

    cols: int
    rows: int

    def resize(self, cols: int, rows: int) -> None: ...
    def clear(self) -> None: ...
    def fill(self, x: int, y: int, w: int, h: int, bg: int) -> None: ...
    def put(self, x: int, y: int, text: str, fg: int = -1, bg: int = -1,
            attr: int = 0) -> int: ...
    def flush(self) -> str: ...
    def invalidate(self) -> None: ...
    def close(self) -> None: ...


# --------------------------------------------------------------------------- #
# Native surface
# --------------------------------------------------------------------------- #

def _bind_render_lib() -> ctypes.CDLL | None:
    lib = native._load("vtui_render")  # noqa: SLF001 - shared loader
    if lib is None:
        return None
    try:
        lib.vr_create.argtypes = [ctypes.c_int32, ctypes.c_int32]
        lib.vr_create.restype = ctypes.c_int32
        lib.vr_destroy.argtypes = [ctypes.c_int32]
        lib.vr_destroy.restype = None
        lib.vr_resize.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]
        lib.vr_resize.restype = ctypes.c_int32
        lib.vr_clear.argtypes = [ctypes.c_int32]
        lib.vr_clear.restype = ctypes.c_int32
        lib.vr_fill.argtypes = [ctypes.c_int32] * 6
        lib.vr_fill.restype = ctypes.c_int32
        lib.vr_put.argtypes = [
            ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_char_p,
            ctypes.c_int32, ctypes.c_int32, ctypes.c_uint32,
        ]
        lib.vr_put.restype = ctypes.c_int32
        lib.vr_flush.argtypes = [ctypes.c_int32, ctypes.c_char_p, ctypes.c_size_t]
        lib.vr_flush.restype = ctypes.c_int32
        lib.vr_invalidate.argtypes = [ctypes.c_int32]
        lib.vr_invalidate.restype = ctypes.c_int32
    except AttributeError:
        return None
    return lib


_RENDER = _bind_render_lib()


class NativeSurface:
    """Cell grid backed by the C++ accelerator."""

    def __init__(self, cols: int, rows: int) -> None:
        if _RENDER is None:
            raise RuntimeError("the native render library is not available")
        self._lib = _RENDER
        self._handle = int(self._lib.vr_create(cols, rows))
        if self._handle == 0:
            raise RuntimeError(f"vr_create({cols}, {rows}) failed")
        self.cols = cols
        self.rows = rows

    def resize(self, cols: int, rows: int) -> None:
        if (cols, rows) == (self.cols, self.rows):
            return
        self._lib.vr_resize(self._handle, cols, rows)
        self.cols, self.rows = cols, rows

    def clear(self) -> None:
        self._lib.vr_clear(self._handle)

    def fill(self, x: int, y: int, w: int, h: int, bg: int) -> None:
        self._lib.vr_fill(self._handle, x, y, w, h, bg)

    def put(self, x: int, y: int, text: str, fg: int = -1, bg: int = -1,
            attr: int = 0) -> int:
        if not text:
            return 0
        return int(self._lib.vr_put(
            self._handle, x, y, text.encode("utf-8"), fg, bg, attr
        ))

    def flush(self) -> str:
        # Worst case is every cell carrying a full style prefix.
        cap = max(4096, self.cols * self.rows * 24 + 256)
        buf = ctypes.create_string_buffer(cap)
        written = int(self._lib.vr_flush(self._handle, buf, cap))
        if written <= 0:
            return ""
        return buf.value.decode("utf-8", "replace")

    def invalidate(self) -> None:
        self._lib.vr_invalidate(self._handle)

    def close(self) -> None:
        if getattr(self, "_handle", 0):
            self._lib.vr_destroy(self._handle)
            self._handle = 0

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Python surface
# --------------------------------------------------------------------------- #

class _Cell:
    __slots__ = ("glyph", "fg", "bg", "attr", "continuation")

    def __init__(self) -> None:
        self.glyph = " "
        self.fg = -1
        self.bg = -1
        self.attr = 0
        self.continuation = False

    def key(self) -> tuple:
        return (self.glyph, self.fg, self.bg, self.attr, self.continuation)


class PythonSurface:
    """Same contract as :class:`NativeSurface`, no compiler required."""

    def __init__(self, cols: int, rows: int) -> None:
        self.cols = cols
        self.rows = rows
        self._back = [[_Cell() for _ in range(cols)] for _ in range(rows)]
        self._front: list[list[tuple]] | None = None

    def resize(self, cols: int, rows: int) -> None:
        if (cols, rows) == (self.cols, self.rows):
            return
        self.cols, self.rows = cols, rows
        self._back = [[_Cell() for _ in range(cols)] for _ in range(rows)]
        self._front = None

    def clear(self) -> None:
        for row in self._back:
            for cell in row:
                cell.glyph = " "
                cell.fg = -1
                cell.bg = -1
                cell.attr = 0
                cell.continuation = False

    def fill(self, x: int, y: int, w: int, h: int, bg: int) -> None:
        for row in range(max(0, y), min(self.rows, y + h)):
            for col in range(max(0, x), min(self.cols, x + w)):
                cell = self._back[row][col]
                cell.glyph = " "
                cell.fg = -1
                cell.bg = bg
                cell.attr = 0
                cell.continuation = False

    def put(self, x: int, y: int, text: str, fg: int = -1, bg: int = -1,
            attr: int = 0) -> int:
        if not (0 <= y < self.rows) or not text:
            return 0
        col = x
        for ch in text:
            width = native._char_width(ch)  # noqa: SLF001
            if width == 0:
                continue
            if col + width > self.cols:
                break
            if col >= 0:
                cell = self._back[y][col]
                cell.glyph = ch
                cell.fg = fg
                cell.bg = bg
                cell.attr = attr
                cell.continuation = False
                if width == 2 and col + 1 < self.cols:
                    tail = self._back[y][col + 1]
                    tail.glyph = ""
                    tail.fg = fg
                    tail.bg = bg
                    tail.attr = attr
                    tail.continuation = True
            col += width
        return col - x

    def flush(self) -> str:
        parts: list[str] = []
        cur_style: tuple | None = None
        cursor: tuple[int, int] | None = None
        wrote = False

        for y in range(self.rows):
            for x in range(self.cols):
                cell = self._back[y][x]
                if cell.continuation:
                    continue
                if self._front is not None and self._front[y][x] == cell.key():
                    continue

                if cursor != (x, y):
                    parts.append(f"\x1b[{y + 1};{x + 1}H")
                style = (cell.fg, cell.bg, cell.attr)
                if style != cur_style:
                    parts.append(self._style(cell))
                    cur_style = style
                glyph = cell.glyph or " "
                parts.append(glyph)
                cursor = (x + max(1, native._char_width(glyph)), y)  # noqa: SLF001
                wrote = True

        self._front = [[cell.key() for cell in row] for row in self._back]
        if not wrote:
            return ""
        parts.append("\x1b[0m")
        return "".join(parts)

    @staticmethod
    def _style(cell: _Cell) -> str:
        codes = ["0"]
        if cell.attr & BOLD:
            codes.append("1")
        if cell.attr & DIM:
            codes.append("2")
        if cell.attr & ITALIC:
            codes.append("3")
        if cell.attr & UNDERLINE:
            codes.append("4")
        if cell.attr & REVERSE:
            codes.append("7")
        if 0 <= cell.fg <= 255:
            codes += ["38", "5", str(cell.fg)]
        if 0 <= cell.bg <= 255:
            codes += ["48", "5", str(cell.bg)]
        return "\x1b[" + ";".join(codes) + "m"

    def invalidate(self) -> None:
        self._front = None

    def close(self) -> None:
        self._front = None


def create(cols: int, rows: int) -> Surface:
    """Build the best available surface."""
    if _RENDER is not None:
        try:
            return NativeSurface(cols, rows)
        except RuntimeError:
            pass
    return PythonSurface(cols, rows)


def backend() -> str:
    return "c++" if _RENDER is not None else "python"
