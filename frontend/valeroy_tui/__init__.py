"""Valeroy AI terminal frontend.

The TUI is a thin client over the gateway. It owns the screen, the chatbox and
the ``/`` command dropdown; every provider call and every credential lives in
the gateway process, not here.

Entry points (see :mod:`valeroy_tui.cli`):
    valeroy                 start the gateway and open the app
    valeroy setup           run the setup wizard
    valeroy setup status    print setup state (no secrets)
    valeroy setup reset     back up and clear setup state
"""

from __future__ import annotations

__version__ = "1.0.0"
