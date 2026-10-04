"""The ``valeroy setup`` wizard.

Setup runs before the gateway is involved: it drives ``valeroy-core`` directly
to create the account, seal provider keys with the account's data key, and pick
a starting provider and model. Nothing here talks to a provider except the
optional "fetch models" step, and that failure is non-fatal so setup still
completes offline.

Spec coverage (section 1):
  * custom username and password, with password confirmation
  * choose which providers to enable (OpenRouter, Costruter, Opencode, Novita …)
  * more than one provider may be enabled, each with its own API key
  * keys are stored so the gateway can read them to reach the provider
"""

from __future__ import annotations

from typing import Any

from valeroy_backend import native

from . import prompts
from .prompts import Item


def _core(*args: str, stdin: str | None = None) -> dict[str, Any]:
    return native.core(*args, stdin=stdin)


def _account_step() -> str:
    """Create (or replace) the account. Returns the unlocked data-key hex."""
    prompts.banner("1. Your account")
    prompts.note("Pick a username and a password. You'll confirm the password.")

    status = _core("account", "exists")
    force = False
    if status.get("exists"):
        existing = status.get("username") or "your account"
        prompts.note(f"An account already exists ({existing}).")
        if not prompts.ask_yes_no("Replace it? Existing provider keys will be lost",
                                   default=False):
            # Keep the existing account: just unlock it to continue setup.
            password = prompts.ask_secret("Enter your current password")
            unlocked = _core("account", "unlock", "--password", "-",
                             stdin=password + "\n")
            prompts.ok(f"Signed in as {unlocked.get('username', existing)}")
            return str(unlocked["data_key"])
        force = True

    while True:
        username = prompts.ask_line("Username", default=status.get("username") or "")
        password = prompts.ask_secret(
            "Password (min 8 chars, with a digit or symbol)", confirm=True
        )
        args = ["account", "create", "--username", username,
                "--password", "-", "--confirm", "-"]
        if force:
            args.append("--force")
        try:
            _core(*args, stdin=f"{password}\n{password}\n")
        except native.CoreError as exc:
            prompts.error(str(exc))
            continue
        prompts.ok(f"Account created for {username}")
        unlocked = _core("account", "unlock", "--password", "-", stdin=password + "\n")
        return str(unlocked["data_key"])


def _provider_step(data_key: str) -> list[str]:
    """Let the user enable providers and key each one. Returns enabled ids."""
    prompts.banner("\n2. Model providers")
    prompts.note("Choose the providers you want to use. You can enable more than one.")

    catalog = native.provider_catalog()
    items = [
        Item(entry["id"], entry.get("label", entry["id"]),
             detail=f"{entry.get('kind', 'chat')} · {entry.get('base_url', '')}")
        for entry in catalog
    ]
    chosen = prompts.select_many(
        "Select providers to enable (Space to toggle):", items,
    )
    if not chosen:
        prompts.note("No providers selected. You can add them later with /providers.")
        return []

    enabled: list[str] = []
    for item in chosen:
        prompts.banner(f"\n   {item.label}")
        key = prompts.ask_secret(f"   API key for {item.label}")
        try:
            _core("provider", "enable", "--id", item.value,
                  "--key", "-", "--data-key", data_key, stdin=key + "\n")
        except native.CoreError as exc:
            prompts.error(f"could not store the key: {exc}")
            continue
        prompts.ok(f"{item.label} enabled")
        enabled.append(item.value)
    return enabled


def _active_model_step(data_key: str, enabled: list[str]) -> None:
    """Optionally choose the starting provider and model."""
    if not enabled:
        return
    prompts.banner("\n3. Starting model")

    if len(enabled) == 1:
        provider = enabled[0]
    else:
        pick = prompts.select_one(
            "Which provider should Valeroy start on?",
            [Item(p, p) for p in enabled],
        )
        if pick is None:
            prompts.note("Skipped. Use /provider and /model later.")
            return
        provider = pick.value

    _core("provider", "select", "--id", provider)

    if not prompts.ask_yes_no(f"Fetch the model list from {provider} now?", default=True):
        prompts.note("Skipped. Use /model once Valeroy is running.")
        return

    try:
        from valeroy_backend import providers
        key = _core("provider", "key", "--id", provider, "--data-key", data_key)["key"]
        config = providers.ProviderConfig.from_catalog(provider, key)
        models = providers.list_models(config)
    except Exception as exc:  # network/provider errors are non-fatal here
        prompts.error(f"could not fetch models ({exc}). Use /model later.")
        return

    if not models:
        prompts.note("The provider returned no models. Use /model later.")
        return

    # Cache the list so /model works instantly on first launch.
    try:
        import json
        _core("model", "cache", "--provider", provider, stdin=json.dumps(models))
    except native.CoreError:
        pass

    pick = prompts.select_one(
        f"Pick a starting model ({len(models)} available):",
        [Item(m["id"], m.get("label", m["id"]),
              detail=f"ctx {m['context']}" if m.get("context") else "")
         for m in models],
    )
    if pick is None:
        prompts.note("No model selected. Use /model later.")
        return
    _core("model", "select", "--id", pick.value, "--provider", provider)
    prompts.ok(f"Starting model set to {pick.label}")


def run() -> int:
    """Run the full wizard. Returns a process exit code."""
    if not native.core_available():
        prompts.error("valeroy-core is not built. Run scripts/build.ps1 first.")
        return 2

    prompts.banner("┌─ Valeroy AI setup ─────────────────────────────────────┐")
    prompts.note("This sets up your account and providers. Ctrl-C to abort.\n")

    try:
        data_key = _account_step()
        enabled = _provider_step(data_key)
        _active_model_step(data_key, enabled)
        _core("setup", "complete")
    except KeyboardInterrupt:
        prompts.error("\nSetup aborted. Nothing after the last ✓ was saved.")
        return 130
    except native.CoreError as exc:
        prompts.error(str(exc))
        return 1

    prompts.banner("\n└─ Setup complete ───────────────────────────────────────┘")
    prompts.ok("Run `valeroy` to start the app.")
    return 0


def print_status() -> int:
    """Back ``valeroy setup status``: show state without revealing secrets."""
    try:
        status = _core("setup", "status")
    except native.CoreError as exc:
        prompts.error(str(exc))
        return 1
    prompts.banner("Valeroy setup status")
    print(f"  account:        {'yes' if status.get('account_exists') else 'no'}")
    print(f"  username:       {status.get('username') or '—'}")
    print(f"  setup complete: {'yes' if status.get('setup_complete') else 'no'}")
    providers = status.get("providers") or []
    if providers:
        print("  providers:")
        for entry in providers:
            fp = entry.get("key_fingerprint") or "????????"
            print(f"    · {entry['id']:<14} key {fp}")
    else:
        print("  providers:      none")
    return 0


def reset() -> int:
    """Back ``valeroy setup reset``: back up and clear state."""
    if not prompts.ask_yes_no(
        "Reset Valeroy? Your account and provider keys will be cleared "
        "(a backup is kept)", default=False
    ):
        prompts.note("Reset cancelled.")
        return 0
    try:
        result = _core("state", "reset")
    except native.CoreError as exc:
        prompts.error(str(exc))
        return 1
    backup = result.get("backup")
    if backup:
        prompts.ok(f"State cleared. Backup written to:\n  {backup}")
    else:
        prompts.ok("Nothing to reset - no state on disk yet.")
    return 0
