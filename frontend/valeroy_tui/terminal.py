"""Terminal control: ANSI setup, alternate screen, raw input, key decoding.

Handles the Windows console (via SetConsoleMode) and POSIX terminals (via
termios) behind one interface so the rest of the TUI never branches on platform.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import dataclass

IS_WINDOWS = platform.system() == "Windows"

# --------------------------------------------------------------------------- #
# ANSI escape sequences
# --------------------------------------------------------------------------- #

ALT_SCREEN_ON = "\x1b[?1049h"
ALT_SCREEN_OFF = "\x1b[?1049l"
CURSOR_HIDE = "\x1b[?25l"
CURSOR_SHOW = "\x1b[?25h"
CLEAR_ALL = "\x1b[2J\x1b[H"
RESET = "\x1b[0m"
WRAP_OFF = "\x1b[?7l"
WRAP_ON = "\x1b[?7h"


def fg(color: int) -> str:
    return f"\x1b[38;5;{color}m"


def bg(color: int) -> str:
    return f"\x1b[48;5;{color}m"


def move(x: int, y: int) -> str:
    """Move the cursor to a zero-indexed column/row."""
    return f"\x1b[{y + 1};{x + 1}H"


# --------------------------------------------------------------------------- #
# Keys
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Key:
    """A decoded keypress.

    `name` is one of: char, enter, backspace, tab, shift-tab, escape, up, down,
    left, right, home, end, page-up, page-down, delete, ctrl-<letter>, resize,
    or unknown.
    """

    name: str
    char: str = ""

    @property
    def is_char(self) -> bool:
        return self.name == "char"


class Terminal:
    """Owns the terminal's mode for the life of the TUI."""

    def __init__(self, stream=None) -> None:
        self.out = stream or sys.stdout
        self._saved_termios = None
        self._saved_console_mode = None
        self._active = False

    # -- lifecycle --------------------------------------------------------- #

    def size(self) -> tuple[int, int]:
        """(columns, rows), with a sane floor so layout never divides by zero."""
        try:
            cols, rows = shutil.get_terminal_size(fallback=(100, 30))
        except OSError:
            cols, rows = 100, 30
        return max(40, cols), max(12, rows)

    def enter(self) -> None:
        """Switch to the alternate screen in raw mode."""
        if self._active:
            return
        self._enable_vt()
        self._enter_raw()
        self.write(ALT_SCREEN_ON + CURSOR_HIDE + WRAP_OFF + CLEAR_ALL)
        self.flush()
        self._active = True

    def leave(self) -> None:
        """Restore the terminal. Safe to call more than once."""
        if not self._active:
            return
        self.write(RESET + WRAP_ON + CURSOR_SHOW + ALT_SCREEN_OFF)
        self.flush()
        self._exit_raw()
        self._active = False

    def __enter__(self) -> "Terminal":
        self.enter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.leave()

    # -- output ------------------------------------------------------------ #

    def write(self, text: str) -> None:
        try:
            self.out.write(text)
        except (BrokenPipeError, ValueError):
            pass

    def flush(self) -> None:
        try:
            self.out.flush()
        except (BrokenPipeError, ValueError):
            pass

    # -- platform plumbing ------------------------------------------------- #

    def _enable_vt(self) -> None:
        """Turn on ANSI processing. Needed on older Windows consoles."""
        if not IS_WINDOWS:
            return
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = wintypes.DWORD()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                self._saved_console_mode = mode.value
                # ENABLE_VIRTUAL_TERMINAL_PROCESSING | ENABLE_PROCESSED_OUTPUT
                kernel32.SetConsoleMode(handle, mode.value | 0x0004 | 0x0001)
            # Also ask the input handle for VT sequences where supported.
            in_handle = kernel32.GetStdHandle(-10)
            in_mode = wintypes.DWORD()
            if kernel32.GetConsoleMode(in_handle, ctypes.byref(in_mode)):
                # Clear ENABLE_QUICK_EDIT_MODE so clicks do not freeze output.
                kernel32.SetConsoleMode(in_handle, (in_mode.value & ~0x0040) | 0x0080)
        except (ImportError, OSError, AttributeError):
            pass

    def _enter_raw(self) -> None:
        if IS_WINDOWS:
            return
        try:
            import termios
            import tty

            fd = sys.stdin.fileno()
            self._saved_termios = termios.tcgetattr(fd)
            tty.setraw(fd)
        except (ImportError, OSError, ValueError):
            self._saved_termios = None

    def _exit_raw(self) -> None:
        if IS_WINDOWS:
            return
        if self._saved_termios is None:
            return
        try:
            import termios

            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._saved_termios)
        except (ImportError, OSError, ValueError):
            pass
        finally:
            self._saved_termios = None

    # -- input ------------------------------------------------------------- #

    def read_key(self, timeout: float | None = None) -> Key | None:
        """Read one keypress. Returns None when `timeout` elapses first."""
        if IS_WINDOWS:
            return self._read_key_windows(timeout)
        return self._read_key_posix(timeout)

    def _read_key_windows(self, timeout: float | None) -> Key | None:
        import msvcrt
        import time

        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                # Arrow/function keys arrive as a two-character sequence.
                if ch in ("\x00", "\xe0"):
                    code = msvcrt.getwch()
                    return Key({
                        "H": "up", "P": "down", "K": "left", "M": "right",
                        "G": "home", "O": "end", "I": "page-up", "Q": "page-down",
                        "S": "delete",
                    }.get(code, "unknown"))
                return self._classify(ch)

            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(0.008)

    def _read_key_posix(self, timeout: float | None) -> Key | None:
        import select

        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            return None
        ch = sys.stdin.read(1)
        if ch != "\x1b":
            return self._classify(ch)

        # Escape sequence: pull the rest without blocking.
        sequence = ""
        while True:
            ready, _, _ = select.select([sys.stdin], [], [], 0.02)
            if not ready:
                break
            sequence += sys.stdin.read(1)
            if sequence[-1].isalpha() or sequence[-1] == "~":
                break

        if not sequence:
            return Key("escape")
        return Key({
            "[A": "up", "[B": "down", "[C": "right", "[D": "left",
            "[H": "home", "[F": "end", "OH": "home", "OF": "end",
            "[1~": "home", "[4~": "end", "[5~": "page-up", "[6~": "page-down",
            "[3~": "delete", "[Z": "shift-tab",
        }.get(sequence, "unknown"))

    @staticmethod
    def _classify(ch: str) -> Key:
        if ch in ("\r", "\n"):
            return Key("enter")
        if ch in ("\x7f", "\b", "\x08"):
            return Key("backspace")
        if ch == "\t":
            return Key("tab")
        if ch == "\x1b":
            return Key("escape")
        code = ord(ch[0]) if ch else 0
        if code < 32:
            # Ctrl-A..Ctrl-Z
            return Key(f"ctrl-{chr(code + 96)}")
        return Key("char", ch)


def supports_color() -> bool:
    """Whether to emit color at all."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("VALEROY_FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


def is_interactive() -> bool:
    """Whether a full-screen TUI is possible here."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False
