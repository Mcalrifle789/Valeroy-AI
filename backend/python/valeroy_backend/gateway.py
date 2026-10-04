"""The Valeroy gateway.

A local HTTP daemon on 127.0.0.1 that owns every outbound provider call and the
unlocked credential vault. It runs as its own background process: the TUI is a
client. Kill the gateway and the frontend loses its connection and stops being
usable, which is the behaviour the spec describes.

The Go implementation in ``backend/gateway`` serves the same API and is used in
preference when it has been built; this one is the always-available path.

Endpoints
---------
GET  /health              liveness, pid, uptime, version
GET  /state               redacted state (account, providers, sessions, agents)
GET  /commands            the command catalog for the ``/`` dropdown
GET  /catalog             the provider catalog
POST /login               unlock the vault; the data key stays in memory only
POST /logout              forget the data key
GET  /models?provider=id  provider model list, normalized and cached
POST /chat                streaming chat completion (newline-delimited JSON)
POST /command             run a model-backed command
POST /shutdown            stop the gateway
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import commands, native, providers
from .providers import ProviderConfig, ProviderError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17637
VERSION = "1.0.0"
MAX_BODY_BYTES = 8 * 1024 * 1024


class Vault:
    """Holds the unlocked data key for the life of the process.

    The key is never written to disk by the gateway and never leaves it: the
    frontend authenticates with a separate gateway token.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data_key: str | None = None
        self._username: str | None = None
        self._token: str | None = None
        self._unlocked_at: float = 0.0

    def unlock(self, password: str) -> dict[str, Any]:
        payload = native.core("account", "unlock", "--password", "-", stdin=password + "\n")
        with self._lock:
            self._data_key = payload["data_key"]
            self._username = payload.get("username") or ""
            self._token = payload.get("gateway_token")
            self._unlocked_at = time.time()
        return {"username": self._username, "token": self._token}

    def lock(self) -> None:
        with self._lock:
            self._data_key = None
            self._username = None
            self._token = None
            self._unlocked_at = 0.0

    @property
    def unlocked(self) -> bool:
        with self._lock:
            return self._data_key is not None

    @property
    def data_key(self) -> str:
        with self._lock:
            if self._data_key is None:
                raise PermissionError("the vault is locked; POST /login first")
            return self._data_key

    @property
    def username(self) -> str | None:
        with self._lock:
            return self._username

    def check_token(self, token: str | None) -> bool:
        with self._lock:
            if self._token is None:
                return False
            if not token:
                return False
            return native.consttime_equal(token.encode(), self._token.encode())

    def info(self) -> dict[str, Any]:
        with self._lock:
            return {
                "unlocked": self._data_key is not None,
                "username": self._username or "",
                "unlocked_at": int(self._unlocked_at),
            }


class GatewayState:
    """Shared gateway state: the vault, caches and counters."""

    def __init__(self) -> None:
        self.vault = Vault()
        self.started_at = time.time()
        self.model_cache: dict[str, list[dict[str, Any]]] = {}
        self.cache_lock = threading.Lock()
        self.requests_served = 0
        self.tokens_this_run = 0
        self.last_error: str | None = None
        self.shutdown_event = threading.Event()

    def provider_config(self, provider_id: str) -> ProviderConfig:
        """Build a live provider config, decrypting the key just in time."""
        key_payload = native.core(
            "provider", "key", "--id", provider_id, "--data-key", self.vault.data_key
        )
        state = native.core("state", "show")["state"]
        base_url = None
        for entry in state.get("providers", []):
            if entry.get("id") == provider_id:
                base_url = entry.get("base_url")
                break
        return ProviderConfig.from_catalog(provider_id, key_payload["key"], base_url)

    def custom_model_config(self, model_id: str) -> ProviderConfig | None:
        """Config for a model registered through ``/models``."""
        state = native.core("state", "show")["state"]
        for entry in state.get("custom_models", []):
            if entry.get("id") == model_id:
                key_payload = native.core(
                    "model", "key", "--id", model_id, "--data-key", self.vault.data_key
                )
                return ProviderConfig(
                    id="custom",
                    api_key=key_payload["key"],
                    base_url=str(entry.get("base_url", "")).rstrip("/"),
                    kind="multi",
                )
        return None

    def resolve_target(self, provider_id: str | None,
                       model_id: str | None) -> tuple[ProviderConfig, str]:
        """Pick the provider config and model to use for a request."""
        state = native.core("state", "show")["state"]
        model = model_id or state.get("active_model")
        provider = provider_id or state.get("active_provider")

        if not model:
            raise ValueError(
                "no model selected - use /model to pick one"
            )

        if provider in (None, "", "custom"):
            custom = self.custom_model_config(str(model))
            if custom is not None:
                return custom, str(model)

        if not provider:
            raise ValueError("no provider selected - use /provider to pick one")
        return self.provider_config(str(provider)), str(model)


STATE = GatewayState()


# --------------------------------------------------------------------------- #
# Runtime descriptor
# --------------------------------------------------------------------------- #

def runtime_file() -> Path:
    paths = native.core("state", "path")
    return Path(paths["runtime"]) / "gateway.json"


def write_runtime(host: str, port: int, token: str | None) -> None:
    record = {
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "version": VERSION,
        "implementation": "python",
        "started_at": int(STATE.started_at),
        "token": token,
    }
    path = runtime_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def clear_runtime() -> None:
    try:
        runtime_file().unlink()
    except OSError:
        pass


def read_runtime() -> dict[str, Any] | None:
    """Read the descriptor a running gateway left behind, if any."""
    try:
        path = runtime_file()
    except native.CoreError:
        return None
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def probe(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
          timeout: float = 0.5) -> bool:
    """True when something is accepting connections on the gateway port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    server_version = f"ValeroyGateway/{VERSION}"
    protocol_version = "HTTP/1.1"

    # -- plumbing ---------------------------------------------------------- #

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        if os.environ.get("VALEROY_GATEWAY_VERBOSE"):
            sys.stderr.write(f"[gateway] {fmt % args}\n")

    def _send(self, status: int, payload: dict[str, Any] | list[Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _fail(self, status: int, message: str) -> None:
        STATE.last_error = message
        self._send(status, {"ok": False, "error": message})

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("request body is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("request body must be a JSON object")
        return parsed

    def _require_local(self) -> bool:
        """Refuse anything that did not come from this machine."""
        peer = self.client_address[0] if self.client_address else ""
        if peer in ("127.0.0.1", "::1", "localhost"):
            return True
        self._fail(403, "the gateway only serves local clients")
        return False

    def _require_token(self) -> bool:
        """Endpoints touching secrets need the token issued at login."""
        header = self.headers.get("Authorization") or ""
        token = header[7:].strip() if header.lower().startswith("bearer ") else header.strip()
        if STATE.vault.check_token(token):
            return True
        self._fail(401, "a valid gateway token is required; log in first")
        return False

    # -- routing ----------------------------------------------------------- #

    def do_GET(self) -> None:  # noqa: N802
        if not self._require_local():
            return
        STATE.requests_served += 1
        route = urlparse(self.path)
        query = parse_qs(route.query)

        try:
            if route.path == "/health":
                self._send(200, {
                    "ok": True,
                    "version": VERSION,
                    "implementation": "python",
                    "pid": os.getpid(),
                    "uptime": round(time.time() - STATE.started_at, 1),
                    "vault": STATE.vault.info(),
                    "requests_served": STATE.requests_served,
                    "tokens_this_run": STATE.tokens_this_run,
                    "native": native.status(),
                })
            elif route.path == "/state":
                self._send(200, {"ok": True, "state": native.core("state", "show")["state"]})
            elif route.path == "/commands":
                self._send(200, {"ok": True, "commands": commands.catalog_payload()})
            elif route.path == "/catalog":
                self._send(200, {"ok": True, "providers": native.provider_catalog()})
            elif route.path == "/models":
                self._handle_models(query)
            else:
                self._fail(404, f"no such endpoint: {route.path}")
        except native.CoreError as exc:
            self._fail(500, str(exc))
        except PermissionError as exc:
            self._fail(401, str(exc))
        except Exception as exc:  # pragma: no cover - last-resort guard
            self._fail(500, f"{type(exc).__name__}: {exc}")
            if os.environ.get("VALEROY_GATEWAY_VERBOSE"):
                traceback.print_exc()

    def do_POST(self) -> None:  # noqa: N802
        if not self._require_local():
            return
        STATE.requests_served += 1
        route = urlparse(self.path)

        try:
            body = self._read_json()
            if route.path == "/login":
                self._handle_login(body)
            elif route.path == "/logout":
                STATE.vault.lock()
                self._send(200, {"ok": True})
            elif route.path == "/chat":
                if not self._require_token():
                    return
                self._handle_chat(body)
            elif route.path == "/command":
                if not self._require_token():
                    return
                self._handle_command(body)
            elif route.path == "/shutdown":
                if not self._require_token():
                    return
                self._send(200, {"ok": True, "stopping": True})
                STATE.shutdown_event.set()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self._fail(404, f"no such endpoint: {route.path}")
        except ValueError as exc:
            self._fail(400, str(exc))
        except PermissionError as exc:
            self._fail(401, str(exc))
        except native.CoreError as exc:
            self._fail(500, str(exc))
        except ProviderError as exc:
            self._fail(502, str(exc))
        except Exception as exc:  # pragma: no cover - last-resort guard
            self._fail(500, f"{type(exc).__name__}: {exc}")
            if os.environ.get("VALEROY_GATEWAY_VERBOSE"):
                traceback.print_exc()

    # -- handlers ---------------------------------------------------------- #

    def _handle_login(self, body: dict[str, Any]) -> None:
        password = body.get("password")
        if not isinstance(password, str) or not password:
            raise ValueError("a password is required")
        try:
            result = STATE.vault.unlock(password)
        except native.CoreError as exc:
            # Wrong password is expected traffic, not a server fault.
            self._fail(401, str(exc))
            return
        record = read_runtime() or {}
        write_runtime(
            record.get("host", DEFAULT_HOST),
            int(record.get("port", DEFAULT_PORT)),
            result["token"],
        )
        self._send(200, {"ok": True, **result})

    def _handle_models(self, query: dict[str, list[str]]) -> None:
        provider_id = (query.get("provider") or [""])[0]
        refresh = (query.get("refresh") or ["0"])[0] not in ("0", "", "false")
        if not provider_id:
            raise ValueError("?provider=<id> is required")

        if not refresh:
            with STATE.cache_lock:
                cached = STATE.model_cache.get(provider_id)
            if cached is not None:
                self._send(200, {
                    "ok": True, "provider": provider_id,
                    "models": cached, "cached": True,
                })
                return

        config = STATE.provider_config(provider_id)
        models = providers.list_models(config)
        with STATE.cache_lock:
            STATE.model_cache[provider_id] = models

        # Persist so the picker still works before the first fetch next launch.
        try:
            native.core("model", "cache", "--provider", provider_id,
                        stdin=json.dumps(models))
        except native.CoreError:
            pass

        self._send(200, {
            "ok": True, "provider": provider_id,
            "models": models, "cached": False,
        })

    def _handle_chat(self, body: dict[str, Any]) -> None:
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a non-empty array")
        for message in messages:
            if not isinstance(message, dict) or "role" not in message:
                raise ValueError("each message needs a role and content")

        config, model = STATE.resolve_target(body.get("provider"), body.get("model"))
        session_id = body.get("session")
        system = str(body.get("system") or "")

        # Newline-delimited JSON: one event per line, flushed as it arrives.
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def emit(event: dict[str, Any]) -> None:
            line = (json.dumps(event) + "\n").encode("utf-8")
            self.wfile.write(f"{len(line):X}\r\n".encode())
            self.wfile.write(line)
            self.wfile.write(b"\r\n")
            self.wfile.flush()

        collected: list[str] = []
        try:
            emit({"type": "start", "model": model, "provider": config.id})
            for event in providers.stream_chat(
                config, model, messages, system=system,
                max_tokens=int(body.get("max_tokens") or 4096),
                temperature=float(body.get("temperature") or 0.7),
            ):
                if event["type"] == "delta":
                    collected.append(event["text"])
                elif event["type"] == "done":
                    usage = event.get("usage") or {}
                    STATE.tokens_this_run += int(usage.get("total") or 0)
                    self._persist_turn(session_id, messages, collected, usage)
                emit(event)
        except ProviderError as exc:
            emit({"type": "error", "error": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ValueError):
                pass

    def _persist_turn(self, session_id: Any, messages: list[dict[str, Any]],
                      collected: list[str], usage: dict[str, Any]) -> None:
        """Record the exchange so /sessions and token counts stay accurate."""
        if not isinstance(session_id, str) or not session_id:
            return
        try:
            last_user = next(
                (m for m in reversed(messages) if m.get("role") == "user"), None
            )
            if last_user:
                native.core(
                    "session", "append", "--id", session_id, "--role", "user",
                    "--tokens", str(int(usage.get("prompt") or 0)),
                    stdin=str(last_user.get("content", "")),
                )
            native.core(
                "session", "append", "--id", session_id, "--role", "assistant",
                "--tokens", str(int(usage.get("completion") or 0)),
                stdin="".join(collected),
            )
        except native.CoreError:
            pass

    def _handle_command(self, body: dict[str, Any]) -> None:
        name = str(body.get("command") or "").lstrip("/")
        command = commands.BY_NAME.get(name)
        if command is None:
            raise ValueError(f"unknown command: /{name}")
        if command.handler != "model":
            raise ValueError(f"/{name} is handled by the frontend, not the gateway")

        args = str(body.get("args") or "")
        config, model = STATE.resolve_target(body.get("provider"), body.get("model"))

        if name == "humanize":
            text = commands.humanize(config, model, args)
            self._send(200, {"ok": True, "command": name, "text": text})
            return

        if name == "agents":
            agent_name, description = commands.split_agents_args(args)
            if not description:
                raise ValueError(
                    "describe what the agent does, e.g. "
                    "/agents Scribe -- takes meeting notes and extracts action items"
                )
            if not agent_name:
                agent_name = (description.split()[0:2] and
                              " ".join(w.capitalize() for w in description.split()[:2]))
            definition = commands.build_agent(config, model, agent_name, description)
            created = native.core(
                "agent", "create",
                "--name", definition["name"],
                "--description", definition["description"],
                "--stdin",
                stdin=definition["instructions"],
            )
            self._send(200, {
                "ok": True, "command": name,
                "agent": {**definition, "id": created.get("id")},
            })
            return

        if name == "animate":
            images = body.get("images")
            images = [str(i) for i in images] if isinstance(images, list) else []
            result = commands.animate(
                config, model, args, images,
                duration_seconds=int(body.get("duration") or 5),
                aspect_ratio=str(body.get("aspect_ratio") or "16:9"),
            )
            job = result["job"]
            self._send(200, {
                "ok": True, "command": name, "job": job,
                "watermark": False,
                "outputs": providers.video_output_urls(job),
            })
            return

        # Everything else model-backed is a prompt with a task-specific preamble.
        system = {
            "summarize": "Summarize the input tightly. Lead with the point.",
            "translate": "Translate the input. Return only the translation.",
            "explain": "Explain clearly and concretely. No filler.",
            "review": "Review this code. List concrete problems and fixes, most severe first.",
            "refactor": "Propose a refactor. Show the changed code.",
            "test": "Write thorough tests for this code, including edge cases.",
            "commit": "Write one clear commit message. Imperative mood, no fluff.",
            "image": "Describe the requested image in vivid, concrete visual detail.",
            "search": "Answer the question directly, flagging anything you are unsure of.",
        }.get(name, "")
        text = providers.complete(config, model, args, system=system)
        self._send(200, {"ok": True, "command": name, "text": text})


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> int:
    """Run the gateway until it is shut down. Returns a process exit code."""
    if not native.core_available():
        sys.stderr.write(
            "[gateway] valeroy-core is not built. "
            "Run scripts/build.ps1 first.\n"
        )
        return 2

    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        sys.stderr.write(f"[gateway] cannot bind {host}:{port}: {exc}\n")
        return 1

    server.daemon_threads = True
    write_runtime(host, port, None)
    sys.stderr.write(
        f"[gateway] Valeroy gateway {VERSION} listening on http://{host}:{port} "
        f"(pid {os.getpid()})\n"
    )
    sys.stderr.flush()

    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        STATE.vault.lock()
        clear_runtime()
        sys.stderr.write("[gateway] stopped\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    host, port = DEFAULT_HOST, DEFAULT_PORT
    i = 0
    while i < len(argv):
        if argv[i] in ("--host", "-H") and i + 1 < len(argv):
            host = argv[i + 1]
            i += 2
        elif argv[i] in ("--port", "-p") and i + 1 < len(argv):
            try:
                port = int(argv[i + 1])
            except ValueError:
                sys.stderr.write("[gateway] --port must be a number\n")
                return 2
            i += 2
        else:
            i += 1
    return serve(host, port)


if __name__ == "__main__":
    raise SystemExit(main())
