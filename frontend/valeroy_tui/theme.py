"""Valeroy themes.

Each theme is a flat set of 256-color indices. There are no panel borders to
colour: the terminal build drops the Electron app's boxes, so a theme works
through background washes, rules, accent text and dim/bright contrast instead.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    label: str
    # Core surfaces
    base: int          # page background
    surface: int       # chatbox / overlay background
    rule: int          # thin separator rules
    # Text
    text: int
    muted: int
    bright: int
    # Accents
    accent: int        # primary brand accent
    accent_alt: int    # secondary accent
    # Semantic
    ok: int
    warn: int
    error: int
    # Roles in the transcript
    user: int
    assistant: int
    # Selection in the command dropdown
    select_bg: int
    select_fg: int
    dark: bool = True


THEMES: tuple[Theme, ...] = (
    Theme("royal", "Royal (default)", base=233, surface=235, rule=238,
          text=252, muted=244, bright=231, accent=178, accent_alt=146,
          ok=78, warn=214, error=203, user=146, assistant=178,
          select_bg=237, select_fg=231),
    Theme("obsidian", "Obsidian", base=232, surface=234, rule=237,
          text=251, muted=243, bright=231, accent=117, accent_alt=146,
          ok=78, warn=214, error=203, user=117, assistant=252,
          select_bg=236, select_fg=231),
    Theme("gold", "Gold Leaf", base=233, surface=236, rule=240,
          text=253, muted=245, bright=231, accent=220, accent_alt=180,
          ok=112, warn=214, error=196, user=180, assistant=220,
          select_bg=238, select_fg=231),
    Theme("crown", "Crown Violet", base=233, surface=235, rule=239,
          text=252, muted=244, bright=231, accent=141, accent_alt=183,
          ok=84, warn=215, error=204, user=183, assistant=141,
          select_bg=54, select_fg=231),
    Theme("ember", "Ember", base=233, surface=235, rule=238,
          text=252, muted=244, bright=231, accent=209, accent_alt=180,
          ok=108, warn=214, error=203, user=180, assistant=209,
          select_bg=52, select_fg=231),
    Theme("forest", "Deep Forest", base=233, surface=235, rule=238,
          text=252, muted=243, bright=231, accent=71, accent_alt=108,
          ok=78, warn=214, error=203, user=108, assistant=71,
          select_bg=22, select_fg=231),
    Theme("ocean", "Ocean", base=233, surface=235, rule=238,
          text=252, muted=244, bright=231, accent=74, accent_alt=117,
          ok=79, warn=214, error=203, user=117, assistant=74,
          select_bg=24, select_fg=231),
    Theme("rose", "Rose Quartz", base=234, surface=236, rule=240,
          text=253, muted=245, bright=231, accent=211, accent_alt=218,
          ok=114, warn=215, error=204, user=218, assistant=211,
          select_bg=53, select_fg=231),
    Theme("slate", "Slate", base=234, surface=237, rule=241,
          text=252, muted=245, bright=231, accent=110, accent_alt=146,
          ok=78, warn=214, error=203, user=146, assistant=110,
          select_bg=239, select_fg=231),
    Theme("mono", "Monochrome", base=232, surface=235, rule=240,
          text=252, muted=243, bright=231, accent=250, accent_alt=245,
          ok=250, warn=250, error=252, user=245, assistant=252,
          select_bg=238, select_fg=231),
    Theme("mint", "Mint", base=233, surface=235, rule=238,
          text=252, muted=244, bright=231, accent=86, accent_alt=120,
          ok=84, warn=214, error=203, user=120, assistant=86,
          select_bg=23, select_fg=231),
    Theme("sand", "Sand", base=235, surface=237, rule=241,
          text=253, muted=246, bright=231, accent=180, accent_alt=223,
          ok=108, warn=214, error=203, user=223, assistant=180,
          select_bg=240, select_fg=231),
    Theme("ink", "Ink & Parchment", base=255, surface=253, rule=250,
          text=236, muted=243, bright=232, accent=94, accent_alt=130,
          ok=28, warn=130, error=124, user=130, assistant=94,
          select_bg=252, select_fg=232, dark=False),
    Theme("daylight", "Daylight", base=231, surface=254, rule=250,
          text=235, muted=244, bright=232, accent=25, accent_alt=31,
          ok=28, warn=130, error=124, user=31, assistant=25,
          select_bg=252, select_fg=232, dark=False),
    Theme("neon", "Neon", base=232, surface=234, rule=238,
          text=252, muted=243, bright=231, accent=201, accent_alt=51,
          ok=48, warn=226, error=197, user=51, assistant=201,
          select_bg=53, select_fg=231),
)

BY_NAME: dict[str, Theme] = {t.name: t for t in THEMES}
DEFAULT = THEMES[0]


def get(name: str | None) -> Theme:
    """Look up a theme, falling back to the default."""
    if not name:
        return DEFAULT
    return BY_NAME.get(name.strip().lower(), DEFAULT)


def next_after(name: str | None) -> Theme:
    """The next theme in the cycle. Backs bare ``/theme``."""
    current = get(name)
    index = THEMES.index(current)
    return THEMES[(index + 1) % len(THEMES)]


def names() -> list[str]:
    return [t.name for t in THEMES]
