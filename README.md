# Valeroy AI

Valeroy AI is a local-first **terminal** agent runtime. There is no Electron app
and no window chrome: a status line sits at the top, the conversation fills the
middle, and the chatbox is centred along the bottom. Type `/` as the first
character to open a dropdown of every command.

A local **gateway** runs as its own background process and owns every outbound
provider call and the unlocked credential vault. The terminal UI is just a
client. If you end the gateway process (Task Manager, or `valeroy gateway
stop`), the frontend can no longer reach it and stops being usable — by design.

## Install

```powershell
# 1. Build the native layers (Rust core is required; C/C++/Go are optional).
powershell -ExecutionPolicy Bypass -File scripts\build.ps1

# 2. Install the CLI (gives you the `valeroy` command).
pip install -e .
```

No third-party Python packages are needed — the frontend and the Python gateway
use only the standard library.

## Use

```powershell
valeroy setup          # create your account and enable providers (first run)
valeroy                 # start the gateway and open the app
```

`valeroy` with no account runs setup automatically. Other commands:

| Command | What it does |
| --- | --- |
| `valeroy` | Start the gateway (if needed) and open the app |
| `valeroy setup` | Run the setup wizard |
| `valeroy setup status` | Print setup state (never shows keys) |
| `valeroy setup reset` | Back up and clear setup state |
| `valeroy gateway status` | Show gateway health |
| `valeroy gateway stop` | Stop the background gateway |
| `valeroy gateway restart` | Restart the background gateway |
| `valeroy doctor` | Report which native layers are active |

## Setup

`valeroy setup` is a terminal wizard with scrolling option menus (Up/Down to
move, Space to toggle a choice, Enter to confirm; the row under the cursor is
bright yellow). It:

1. Creates your account — custom **username and password, with confirmation**.
2. Lets you enable one **or more** providers (OpenRouter, Costruter, Opencode,
   Novita, and ~20 more) and stores an API key for each.
3. Optionally fetches the model list from a provider and sets a starting model.

Keys are sealed with a data key that is itself wrapped by your password; the
gateway is the only process that ever decrypts them to reach a provider.

## Commands (type `/` in the chatbox)

- **Models & providers:** `/model`, `/models` (add a custom model + key),
  `/provider`, `/providers`, `/keys`
- **Sessions & agents:** `/sessions`, `/new`, `/agent`, `/agents` (describe an
  agent in words and the model writes its instructions), `/resume`, `/delete`,
  `/history`, `/export`
- **Generation:** `/humanize`, `/animate` (image→video; no Valeroy wordmark on
  output), `/image`, `/summarize`, `/translate`, `/explain`, `/review`,
  `/refactor`, `/test`, `/commit`, `/search`
- **App:** `/theme`, `/status`, `/tokens`, `/gateway`, `/setup`, `/passwd`,
  `/clear`, `/help`, `/doctor`, `/quit`

You can also create an agent without the command — just ask in the chatbox
("make an agent called Scribe that takes meeting notes…") and Valeroy builds it.

## Architecture

```
frontend/valeroy_tui/   Python TUI: app loop, chatbox, dropdown, setup wizard, CLI
frontend/cpp/           C++ render accelerator (diffed cell grid)
backend/core/           Rust  - the state engine (accounts, vault, sessions, agents)
backend/gateway/        Go    - the gateway daemon (preferred when built)
backend/python/         Python- the gateway (always-available fallback) + providers
backend/catalog/        C++   - the provider catalog + model-list normalizer
backend/chash/          C     - PBKDF2 and constant-time comparison
```

Every native layer has a pure-Python fallback, so Valeroy runs on a machine with
no compiler — it just uses the native path wherever it has been built. Run
`valeroy doctor` (or `/doctor`) to see which path is live.

**Languages:** frontend — C++ and Python; backend — C++, C, Go, Rust and Python.

## Development

```powershell
# Run without installing, straight from the tree:
$env:PYTHONPATH = "backend\python;frontend"
python -m valeroy_tui            # the app
python -m valeroy_tui setup      # the wizard
cargo test --manifest-path backend\core\Cargo.toml
```
