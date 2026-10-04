"""Inline terminal prompts: masked secrets, line input, scrolling menus.

These are the pieces the setup wizard and the login flow are built from. They
draw inline (not on the alternate screen) so the wizard reads like a normal
terminal session, and they fall back to plain ``input()`` when there is no TTY
so the flow still works when piped.

The selectable menus honour the spec's controls: Up/Down to scroll, Space to
toggle a choice in a multi-select, Enter to confirm. The row under the cursor is
drawn in bright yellow.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Sequence

from .terminal import Terminal, is_interactive

# 256-colour palette used across the inline prompts.
YELLOW = "\x1b[38;5;220m"
DIM = "\x1b[38;5;244m"
ACCENT = "\x1b[38;5;178m"
OK = "\x1b[38;5;78m"
ERR = "\x1b[38;5;203m"
BOLD = "\x1b[1m"
RESET = "\x1b[0m"
CLEAR_LINE = "\x1b[2K\r"


def _supports_style() -> bool:
    return sys.stdout.isatty()


def paint(text: str, *codes: str) -> str:
    if not _supports_style() or not codes:
        return text
    return "".join(codes) + text + RESET


def banner(line: str) -> None:
    print(paint(line, ACCENT, BOLD))


def note(line: str) -> None:
    print(paint(line, DIM))


def ok(line: str) -> None:
    print(paint("✓ ", OK) + line)


def error(line: str) -> None:
    print(paint("✗ ", ERR) + line)


# --------------------------------------------------------------------------- #
# Text input
# --------------------------------------------------------------------------- #

def ask_line(prompt: str, *, default: str = "", allow_empty: bool = False) -> str:
    """Read a single line, re-prompting until it is acceptable."""
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            raw = input(paint(f"{prompt}{suffix}: ", ACCENT))
        except EOFError:
            return default
        value = raw.strip() or default
        if value or allow_empty:
            return value
        error("this field is required")


def ask_secret(prompt: str, *, confirm: bool = False,
               confirm_prompt: str = "Confirm password") -> str:
    """Read a masked secret. Optionally require it to be typed twice."""
    while True:
        first = _read_masked(f"{prompt}: ")
        if not first:
            error("this field is required")
            continue
        if not confirm:
            return first
        second = _read_masked(f"{confirm_prompt}: ")
        if first == second:
            return first
        error("the entries did not match - try again")


def _read_masked(label: str) -> str:
    """Read a line without echoing it, showing a bullet per character."""
    if not is_interactive():
        # Piped/non-TTY input: read a line straight from stdin. (getpass is not
        # usable here - on Windows it reads the console directly and would hang
        # when stdin is a pipe.)
        line = sys.stdin.readline()
        if not line:
            return ""
        return line.rstrip("\r\n")

    term = Terminal()
    term._enter_raw()  # noqa: SLF001 - intentional: raw mode without alt screen
    try:
        sys.stdout.write(paint(label, ACCENT))
        sys.stdout.flush()
        buffer: list[str] = []
        while True:
            key = term.read_key()
            if key is None:
                continue
            if key.name == "enter":
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buffer)
            if key.name == "backspace":
                if buffer:
                    buffer.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if key.name in ("ctrl-c",):
                sys.stdout.write("\n")
                raise KeyboardInterrupt
            if key.is_char and key.char >= " ":
                buffer.append(key.char)
                sys.stdout.write("•")
                sys.stdout.flush()
    finally:
        term._exit_raw()  # noqa: SLF001


def ask_yes_no(prompt: str, *, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    answer = ask_line(f"{prompt} ({hint})", default="y" if default else "n").lower()
    return answer.startswith("y")


# --------------------------------------------------------------------------- #
# Scrolling menus
# --------------------------------------------------------------------------- #

@dataclass
class Item:
    value: str
    label: str
    detail: str = ""


def _render_menu(title: str, items: Sequence[Item], index: int,
                 selected: set[int] | None, footer: str, window: int) -> int:
    """Draw the menu and return the number of lines written."""
    lines: list[str] = [paint(title, ACCENT, BOLD)]
    half = window // 2
    start = max(0, min(index - half, max(0, len(items) - window)))
    end = min(len(items), start + window)
    for i in range(start, end):
        item = items[i]
        cursor = "▸" if i == index else " "
        if selected is not None:
            box = "[x]" if i in selected else "[ ]"
            body = f"{cursor} {box} {item.label}"
        else:
            body = f"{cursor} {item.label}"
        if item.detail:
            body = f"{body}  —  {item.detail}"
        if i == index:
            lines.append(paint(body, YELLOW, BOLD))
        else:
            lines.append(body)
    if len(items) > window:
        lines.append(paint(f"  ({index + 1}/{len(items)})", DIM))
    if footer:
        lines.append(paint(footer, DIM))
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()
    return len(lines)


def _clear_lines(n: int) -> None:
    if n <= 0:
        return
    # Move up n lines and clear each.
    sys.stdout.write(f"\x1b[{n}A")
    for _ in range(n):
        sys.stdout.write("\x1b[2K\x1b[1B")
    sys.stdout.write(f"\x1b[{n}A")
    sys.stdout.flush()


def select_one(title: str, items: Sequence[Item], *,
               footer: str = "↑/↓ move · Enter choose · q cancel",
               window: int = 12) -> Item | None:
    """Single-select scrolling menu. Returns None when cancelled."""
    if not items:
        return None
    if not is_interactive():
        # Non-interactive: take the first item.
        return items[0]

    term = Terminal()
    term._enter_raw()  # noqa: SLF001
    index = 0
    drawn = 0
    try:
        while True:
            if drawn:
                _clear_lines(drawn)
            drawn = _render_menu(title, items, index, None, footer, window)
            key = term.read_key()
            if key is None:
                continue
            if key.name == "up":
                index = (index - 1) % len(items)
            elif key.name == "down":
                index = (index + 1) % len(items)
            elif key.name == "enter":
                return items[index]
            elif key.name in ("escape", "ctrl-c") or (key.is_char and key.char in ("q", "Q")):
                return None
    finally:
        term._exit_raw()  # noqa: SLF001


def select_many(title: str, items: Sequence[Item], *,
                preselected: Sequence[int] = (),
                footer: str = "↑/↓ move · Space toggle · Enter confirm · q cancel",
                window: int = 14) -> list[Item]:
    """Multi-select scrolling menu. Returns the chosen items (possibly empty)."""
    if not items:
        return []
    selected = set(preselected)
    if not is_interactive():
        return [items[i] for i in sorted(selected)]

    term = Terminal()
    term._enter_raw()  # noqa: SLF001
    index = 0
    drawn = 0
    try:
        while True:
            if drawn:
                _clear_lines(drawn)
            drawn = _render_menu(title, items, index, selected, footer, window)
            key = term.read_key()
            if key is None:
                continue
            if key.name == "up":
                index = (index - 1) % len(items)
            elif key.name == "down":
                index = (index + 1) % len(items)
            elif key.is_char and key.char == " ":
                selected ^= {index}
            elif key.name == "enter":
                return [items[i] for i in sorted(selected)]
            elif key.name in ("escape", "ctrl-c") or (key.is_char and key.char in ("q", "Q")):
                return []
    finally:
        term._exit_raw()  # noqa: SLF001
