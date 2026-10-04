"""The ``valeroy`` command line.

    valeroy                     start the gateway (if needed) and open the app
    valeroy setup               run the setup wizard
    valeroy setup status        print setup state (no secrets)
    valeroy setup reset         back up and clear setup state
    valeroy gateway status      show gateway health
    valeroy gateway stop        stop the background gateway
    valeroy gateway restart     restart the background gateway
    valeroy doctor              report which native layers are active
    valeroy version             print the version

Starting the app spawns the gateway as its own background process and keeps it
running after the app exits, so the next launch is instant. Kill that process
(Task Manager, or ``valeroy gateway stop``) and the frontend can no longer
reach it - which is the behaviour the spec describes.
"""

from __future__ import annotations

import sys

from valeroy_backend import native


def _force_utf8() -> None:
    """The TUI draws box/arrow glyphs; a cp1252 console would mangle them."""
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

from . import __version__, prompts, setup_wizard
from .app import App
from .client import GatewayClient, GatewayError, spawn_gateway, stop_gateway
from valeroy_backend.gateway import DEFAULT_HOST, DEFAULT_PORT


def _needs_setup() -> bool:
    status = native.core("setup", "status")
    return not (status.get("account_exists") and status.get("setup_complete"))


def _login(client: GatewayClient) -> str | None:
    """Prompt for the password, unlock the gateway and the local data key.

    Returns the data-key hex on success, or None if the user gave up.
    """
    for attempt in range(3):
        password = prompts.ask_secret("Password")
        try:
            # The local data key lets the app seal new provider/model keys
            # mid-session; the gateway holds its own copy for provider calls.
            unlocked = native.core("account", "unlock", "--password", "-",
                                   stdin=password + "\n")
            client.login(password)
            return str(unlocked["data_key"])
        except (native.CoreError, GatewayError) as exc:
            remaining = 2 - attempt
            prompts.error(str(exc) + (f" ({remaining} tries left)" if remaining else ""))
    return None


def _run_app() -> int:
    if not native.core_available():
        prompts.error("valeroy-core is not built. Run scripts/build.ps1 first.")
        return 2

    if _needs_setup():
        prompts.note("No account yet - running first-time setup.\n")
        code = setup_wizard.run()
        if code != 0:
            return code
        print()

    prompts.banner("Starting Valeroy…")
    client = GatewayClient(DEFAULT_HOST, DEFAULT_PORT)
    try:
        process, impl = spawn_gateway(DEFAULT_HOST, DEFAULT_PORT)
    except GatewayError as exc:
        prompts.error(f"could not start the gateway: {exc}")
        return 1
    prompts.ok(f"Gateway {'already running' if impl == 'already-running' else impl}.")

    data_key = _login(client)
    if data_key is None:
        prompts.error("Could not unlock. Exiting.")
        return 1

    app = App(client, data_key, DEFAULT_HOST, DEFAULT_PORT)
    try:
        app.run()
    except KeyboardInterrupt:
        pass

    prompts.note(
        "\nValeroy closed. The gateway is still running in the background.\n"
        "Stop it with: valeroy gateway stop"
    )
    return 0


def _gateway_command(args: list[str]) -> int:
    action = args[0] if args else "status"
    client = GatewayClient(DEFAULT_HOST, DEFAULT_PORT)
    if action == "status":
        health = client.health()
        if health:
            prompts.ok(f"Gateway up — {health.get('implementation')} "
                       f"pid {health.get('pid')}, uptime {health.get('uptime')}s.")
        else:
            prompts.error("Gateway is not running.")
        return 0
    if action == "stop":
        prompts.ok("Gateway stopped.") if stop_gateway(DEFAULT_HOST, DEFAULT_PORT) \
            else prompts.note("Gateway was not running.")
        return 0
    if action == "restart":
        stop_gateway(DEFAULT_HOST, DEFAULT_PORT)
        try:
            _, impl = spawn_gateway(DEFAULT_HOST, DEFAULT_PORT)
            prompts.ok(f"Gateway restarted ({impl}). Run `valeroy` to unlock it.")
        except GatewayError as exc:
            prompts.error(str(exc))
            return 1
        return 0
    prompts.error(f"unknown gateway action: {action}")
    return 2


def _doctor() -> int:
    status = native.status()
    prompts.banner("Valeroy native layers")
    print(f"  core:    {status.get('core') or 'not built (python fallback)'}")
    print(f"  hashing: {status.get('hash')}")
    print(f"  catalog: {status.get('catalog')} {status.get('catalog_version') or ''}")
    print(f"  render:  {status.get('render')} {status.get('render_version') or ''}")
    print(f"  python:  {status.get('python')}")
    return 0


HELP = __doc__


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv:
        return _run_app()

    command, rest = argv[0], argv[1:]
    if command in ("-h", "--help", "help"):
        print(HELP)
        return 0
    if command in ("-v", "--version", "version"):
        print(f"valeroy {__version__}")
        return 0
    if command == "setup":
        action = rest[0] if rest else ""
        if action == "status":
            return setup_wizard.print_status()
        if action == "reset":
            return setup_wizard.reset()
        if action in ("", "run"):
            return setup_wizard.run()
        prompts.error(f"unknown setup action: {action}")
        return 2
    if command == "gateway":
        return _gateway_command(rest)
    if command == "doctor":
        return _doctor()

    prompts.error(f"unknown command: {command}\n")
    print(HELP)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
