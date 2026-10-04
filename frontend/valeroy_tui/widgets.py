"""Reusable TUI pieces: the text editor line, the overlay chooser, transcript.

Kept separate from :mod:`valeroy_tui.app` so each piece can be tested without a
terminal attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from valeroy_backend import native

from . import surface as surface_mod
from .theme import Theme


# --------------------------------------------------------------------------- #
# Single-line editor
# --------------------------------------------------------------------------- #

class Editor:
    """A one-line text editor with a cursor and history.

    Backs the chatbox. Deliberately minimal: no selection, no undo.
    """

    def __init__(self, history_limit: int = 200) -> None:
        self.text = ""
        self.cursor = 0
        self.history: list[str] = []
        self._history_index: int | None = None
        self._draft = ""
        self._history_limit = history_limit

    # -- editing ----------------------------------------------------------- #

    def insert(self, chunk: str) -> None:
        self.text = self.text[: self.cursor] + chunk + self.text[self.cursor :]
        self.cursor += len(chunk)
        self._history_index = None

    def backspace(self) -> None:
        if self.cursor > 0:
            self.text = self.text[: self.cursor - 1] + self.text[self.cursor :]
            self.cursor -= 1
            self._history_index = None

    def delete(self) -> None:
        if self.cursor < len(self.text):
            self.text = self.text[: self.cursor] + self.text[self.cursor + 1 :]
            self._history_index = None

    def delete_word(self) -> None:
        """Ctrl-W: remove the word before the cursor."""
        if self.cursor == 0:
            return
        head = self.text[: self.cursor].rstrip()
        cut = head.rfind(" ")
        new_head = head[: cut + 1] if cut >= 0 else ""
        self.text = new_head + self.text[self.cursor :]
        self.cursor = len(new_head)
        self._history_index = None

    def clear(self) -> str:
        """Empty the editor and return what was in it."""
        taken = self.text
        self.text = ""
        self.cursor = 0
        self._history_index = None
        return taken

    # -- movement ---------------------------------------------------------- #

    def left(self) -> None:
        self.cursor = max(0, self.cursor - 1)

    def right(self) -> None:
        self.cursor = min(len(self.text), self.cursor + 1)

    def home(self) -> None:
        self.cursor = 0

    def end(self) -> None:
        self.cursor = len(self.text)

    # -- history ----------------------------------------------------------- #

    def remember(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.history and self.history[-1] == text:
            return
        self.history.append(text)
        del self.history[: max(0, len(self.history) - self._history_limit)]

    def history_prev(self) -> bool:
        """Step back through history. True when the text changed."""
        if not self.history:
            return False
        if self._history_index is None:
            self._draft = self.text
            self._history_index = len(self.history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        else:
            return False
        self.text = self.history[self._history_index]
        self.cursor = len(self.text)
        return True

    def history_next(self) -> bool:
        """Step forward through history. True when the text changed."""
        if self._history_index is None:
            return False
        if self._history_index < len(self.history) - 1:
            self._history_index += 1
            self.text = self.history[self._history_index]
        else:
            self._history_index = None
            self.text = self._draft
        self.cursor = len(self.text)
        return True

    # -- rendering --------------------------------------------------------- #

    def visible(self, width: int) -> tuple[str, int]:
        """Clip the text to `width` columns around the cursor.

        Returns (visible_text, cursor_column_within_visible).
        """
        if width <= 0:
            return "", 0
        if native.display_width(self.text) <= width:
            return self.text, native.display_width(self.text[: self.cursor])

        # Keep the cursor in view, preferring to scroll the left edge.
        before = self.text[: self.cursor]
        cursor_col = native.display_width(before)
        start = 0
        while native.display_width(self.text[start : self.cursor]) > width - 1:
            start += 1
        clipped = self.text[start:]
        while native.display_width(clipped) > width:
            clipped = clipped[:-1]
        return clipped, min(width - 1, cursor_col - native.display_width(self.text[:start]))


# --------------------------------------------------------------------------- #
# Overlay chooser
# --------------------------------------------------------------------------- #

@dataclass
class Choice:
    """One row in a chooser overlay."""

    value: str
    label: str
    detail: str = ""
    badge: str = ""
    data: Any = None


class Chooser:
    """A scrolling overlay list.

    Serves double duty: the ``/`` command dropdown and the pickers behind
    ``/model``, ``/sessions``, ``/agent``, ``/provider`` and ``/theme``.
    """

    def __init__(self, title: str, choices: list[Choice], *,
                 max_visible: int = 10,
                 on_pick: Callable[[Choice], None] | None = None,
                 footer: str = "") -> None:
        self.title = title
        self.all_choices = choices
        self.choices = list(choices)
        self.index = 0
        self.offset = 0
        self.max_visible = max_visible
        self.on_pick = on_pick
        self.footer = footer
        self.filter_text = ""

    @property
    def active(self) -> bool:
        return bool(self.choices)

    @property
    def current(self) -> Choice | None:
        if not self.choices:
            return None
        return self.choices[min(self.index, len(self.choices) - 1)]

    def set_choices(self, choices: list[Choice]) -> None:
        self.choices = choices
        self.index = 0
        self.offset = 0

    def apply_filter(self, needle: str) -> None:
        """Narrow the list, matching on label, value and detail."""
        self.filter_text = needle
        lowered = needle.strip().lower()
        if not lowered:
            self.set_choices(list(self.all_choices))
            return
        starts, contains = [], []
        for choice in self.all_choices:
            haystack = f"{choice.value} {choice.label}".lower()
            if haystack.startswith(lowered) or choice.label.lower().startswith(lowered):
                starts.append(choice)
            elif lowered in haystack or lowered in choice.detail.lower():
                contains.append(choice)
        self.set_choices(starts + contains)

    def move(self, delta: int) -> None:
        if not self.choices:
            return
        self.index = max(0, min(len(self.choices) - 1, self.index + delta))
        visible = min(self.max_visible, len(self.choices))
        if self.index < self.offset:
            self.offset = self.index
        elif self.index >= self.offset + visible:
            self.offset = self.index - visible + 1

    def height(self) -> int:
        """Rows the overlay occupies, including its title and footer."""
        rows = min(self.max_visible, max(1, len(self.choices)))
        return rows + 1 + (1 if self.footer else 0)

    def draw(self, surf: surface_mod.Surface, x: int, y: int, width: int,
             th: Theme) -> None:
        """Paint the overlay with its top-left corner at (x, y)."""
        visible = min(self.max_visible, len(self.choices))
        total_rows = self.height()
        surf.fill(x, y, width, total_rows, th.surface)

        # Title row: no border, just a dim label and a count on the right.
        title = native.truncate(self.title, max(0, width - 12))
        surf.put(x + 1, y, title, fg=th.accent, bg=th.surface,
                 attr=surface_mod.BOLD)
        if len(self.choices) > visible:
            counter = f"{self.index + 1}/{len(self.choices)}"
            surf.put(x + width - len(counter) - 1, y, counter,
                     fg=th.muted, bg=th.surface)
        elif not self.choices:
            surf.put(x + width - 9, y, "no match", fg=th.muted, bg=th.surface)

        for row in range(visible):
            choice_index = self.offset + row
            if choice_index >= len(self.choices):
                break
            choice = self.choices[choice_index]
            selected = choice_index == self.index
            line_y = y + 1 + row
            row_bg = th.select_bg if selected else th.surface
            surf.fill(x, line_y, width, 1, row_bg)

            marker = "▸" if selected else " "
            surf.put(x + 1, line_y, marker,
                     fg=th.accent if selected else th.muted, bg=row_bg)

            label_fg = th.select_fg if selected else th.text
            label = native.truncate(choice.label, max(1, width // 2))
            used = surf.put(x + 3, line_y, label, fg=label_fg, bg=row_bg,
                            attr=surface_mod.BOLD if selected else 0)

            # Badge sits immediately after the label.
            column = x + 3 + used + 1
            if choice.badge:
                badge = native.truncate(choice.badge, 14)
                surf.put(column, line_y, badge, fg=th.accent_alt, bg=row_bg)
                column += native.display_width(badge) + 1

            remaining = x + width - column - 1
            if choice.detail and remaining > 4:
                detail = native.truncate(choice.detail, remaining)
                surf.put(column, line_y, detail, fg=th.muted, bg=row_bg)

        if self.footer:
            surf.put(x + 1, y + total_rows - 1,
                     native.truncate(self.footer, width - 2),
                     fg=th.muted, bg=th.surface)

    def pick(self) -> Choice | None:
        choice = self.current
        if choice is not None and self.on_pick is not None:
            self.on_pick(choice)
        return choice


# --------------------------------------------------------------------------- #
# Transcript
# --------------------------------------------------------------------------- #

@dataclass
class Message:
    """One entry in the transcript."""

    role: str           # user | assistant | system | error | note
    text: str
    streaming: bool = False
    meta: str = ""


@dataclass
class Transcript:
    """The conversation view, with wrapping and scrollback."""

    messages: list[Message] = field(default_factory=list)
    scroll: int = 0  # rows scrolled up from the bottom

    def add(self, role: str, text: str, *, streaming: bool = False,
            meta: str = "") -> Message:
        message = Message(role=role, text=text, streaming=streaming, meta=meta)
        self.messages.append(message)
        self.scroll = 0
        return message

    def clear(self) -> None:
        self.messages.clear()
        self.scroll = 0

    def layout(self, width: int, th: Theme) -> list[tuple[str, int, int]]:
        """Flatten the transcript into (text, fg, attr) rows for `width` columns."""
        rows: list[tuple[str, int, int]] = []
        gutter = 10  # room for the "valeroy ▸" prefix
        body_width = max(8, width - gutter)

        for index, message in enumerate(self.messages):
            if index:
                rows.append(("", th.text, 0))

            if message.role == "user":
                prefix, prefix_fg = "you", th.user
            elif message.role == "assistant":
                prefix, prefix_fg = "valeroy", th.assistant
            elif message.role == "error":
                prefix, prefix_fg = "error", th.error
            elif message.role == "note":
                prefix, prefix_fg = "", th.muted
            else:
                prefix, prefix_fg = "system", th.muted

            body_fg = {
                "user": th.text,
                "assistant": th.text,
                "error": th.error,
                "note": th.muted,
            }.get(message.role, th.muted)

            text = message.text
            if message.streaming:
                text = text + "█"

            lines = native.wrap(text, body_width) if text else [""]
            for line_index, line in enumerate(lines):
                if line_index == 0 and prefix:
                    label = f"{prefix} ▸ "
                    rows.append((label.ljust(gutter) + line, prefix_fg, 0))
                    # Mark the prefix width so the drawer can colour it apart.
                else:
                    rows.append((" " * gutter + line, body_fg, 0))

            if message.meta:
                rows.append((" " * gutter + message.meta, th.muted,
                             surface_mod.DIM))
        return rows

    def visible_rows(self, width: int, height: int,
                     th: Theme) -> list[tuple[str, int, int]]:
        """The window of rows to paint, honouring the scroll offset."""
        rows = self.layout(width, th)
        if height <= 0:
            return []
        if len(rows) <= height:
            self.scroll = 0
            return rows
        max_scroll = len(rows) - height
        self.scroll = max(0, min(self.scroll, max_scroll))
        end = len(rows) - self.scroll
        return rows[end - height : end]

    def total_rows(self, width: int, th: Theme) -> int:
        return len(self.layout(width, th))
