"""Gateway client and supervisor.

The frontend never calls a provider directly. It talks to the gateway, which
runs as its own background process. This module both speaks the gateway's HTTP
API and knows how to start and stop that process.

If the gateway dies, :meth:`GatewayClient.health` starts failing and the TUI
shows a disconnected state, which is the behaviour the spec calls for.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator

from valeroy_backend import native
from valeroy_backend.gateway import DEFAULT_HOST, DEFAULT_PORT

IS_WINDOWS = platform.system() == "Windows"


class GatewayError(RuntimeError):
    """The gateway refused a request or could not be reached."""


class GatewayClient:
    """Thin HTTP client for the local Valeroy gateway."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self.token: str | None = None
        self.username: str | None = None

    @property
    def base(self) -> str:
        return f"http://{self.host}:{self.port}"

    # -- plumbing ---------------------------------------------------------- #

    def _open(self, path: str, *, method: str = "GET",
              body: dict[str, Any] | None = None,
              timeout: float = 30.0, stream: bool = False):
        url = f"{self.base}{path}"
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                payload = json.loads(exc.read().decode("utf-8", "replace"))
                detail = str(payload.get("error") or "")
            except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                pass
            raise GatewayError(detail or f"gateway returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise GatewayError(f"gateway is not reachable: {exc.reason}") from exc
        except TimeoutError as exc:
            raise GatewayError("gateway timed out") from exc

    def _json(self, path: str, *, method: str = "GET",
              body: dict[str, Any] | None = None,
              timeout: float = 30.0) -> dict[str, Any]:
        with self._open(path, method=method, body=body, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GatewayError("gateway returned unparseable output") from exc
        if not payload.get("ok"):
            raise GatewayError(str(payload.get("error") or "gateway request failed"))
        return payload

    # -- endpoints --------------------------------------------------------- #

    def health(self, timeout: float = 2.0) -> dict[str, Any] | None:
        """Gateway status, or None when it is not answering."""
        try:
            return self._json("/health", timeout=timeout)
        except GatewayError:
            return None

    def login(self, password: str) -> dict[str, Any]:
        payload = self._json("/login", method="POST", body={"password": password})
        self.token = payload.get("token")
        self.username = payload.get("username")
        return payload

    def logout(self) -> None:
        try:
            self._json("/logout", method="POST", body={})
        except GatewayError:
            pass
        self.token = None

    def state(self) -> dict[str, Any]:
        return self._json("/state")["state"]

    def catalog(self) -> list[dict[str, Any]]:
        return self._json("/catalog")["providers"]

    def commands(self) -> list[dict[str, Any]]:
        return self._json("/commands")["commands"]

    def models(self, provider: str, refresh: bool = False) -> list[dict[str, Any]]:
        suffix = "&refresh=1" if refresh else ""
        return self._json(
            f"/models?provider={urllib.parse.quote(provider)}{suffix}", timeout=60.0
        )["models"]

    def run_command(self, command: str, args: str = "", **extra: Any) -> dict[str, Any]:
        return self._json(
            "/command", method="POST",
            body={"command": command, "args": args, **extra},
            timeout=300.0,
        )

    def chat(self, messages: list[dict[str, str]], *,
             session: str | None = None,
             system: str = "",
             model: str | None = None,
             provider: str | None = None,
             max_tokens: int = 4096,
             temperature: float = 0.7) -> Iterator[dict[str, Any]]:
        """Stream a chat completion, yielding the gateway's events."""
        body: dict[str, Any] = {
            "messages": messages,
            "system": system,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if session:
            body["session"] = session
        if model:
            body["model"] = model
        if provider:
            body["provider"] = provider

        with self._open("/chat", method="POST", body=body,
                        timeout=600.0, stream=True) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def shutdown(self) -> bool:
        try:
            self._json("/shutdown", method="POST", body={}, timeout=5.0)
            return True
        except GatewayError:
            return False


# --------------------------------------------------------------------------- #
# Process supervision
# --------------------------------------------------------------------------- #

def _python_executable() -> str:
    """Interpreter to launch the gateway with.

    Prefer the windowless build on Windows so the background process does not
    flash a console window.
    """
    if IS_WINDOWS:
        candidate = Path(sys.executable).with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _gateway_environment() -> dict[str, str]:
    env = dict(os.environ)
    root = Path(__file__).resolve().parents[2]
    paths = [str(root / "backend" / "python"), str(root / "frontend")]
    existing = env.get("PYTHONPATH", "")
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def go_gateway_binary() -> Path | None:
    """The compiled Go gateway, when it has been built."""
    override = os.environ.get("VALEROY_GATEWAY_BIN")
    if override and Path(override).exists():
        return Path(override)
    exe = "valeroy-gateway.exe" if IS_WINDOWS else "valeroy-gateway"
    candidate = Path(__file__).resolve().parents[2] / "build" / "native" / exe
    return candidate if candidate.exists() else None


def spawn_gateway(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                  wait_seconds: float = 12.0) -> tuple[subprocess.Popen | None, str]:
    """Start the gateway as a detached background process.

    Returns (process, implementation). `process` is None when an already-running
    gateway was found. Prefers the Go build and falls back to Python.
    """
    client = GatewayClient(host, port)
    if client.health(timeout=1.0) is not None:
        return None, "already-running"

    log_dir = Path(native.core("state", "path")["logs"])
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "gateway.log"
    log_handle = open(log_path, "ab", buffering=0)  # noqa: SIM115 - owned by child

    go_binary = go_gateway_binary()
    if go_binary is not None:
        command = [str(go_binary), "--host", host, "--port", str(port)]
        implementation = "go"
    else:
        command = [
            _python_executable(), "-u", "-m", "valeroy_backend.gateway",
            "--host", host, "--port", str(port),
        ]
        implementation = "python"

    kwargs: dict[str, Any] = {
        "stdout": log_handle,
        "stderr": log_handle,
        "stdin": subprocess.DEVNULL,
        "env": _gateway_environment(),
        "cwd": str(Path(__file__).resolve().parents[2]),
    }
    if IS_WINDOWS:
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: survives the parent and
        # shows up in Task Manager as its own process, per the spec.
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True

    process = subprocess.Popen(command, **kwargs)  # noqa: S603

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if client.health(timeout=0.6) is not None:
            return process, implementation
        if process.poll() is not None:
            tail = ""
            try:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-600:]
            except OSError:
                pass
            raise GatewayError(
                f"the gateway exited immediately (code {process.returncode}).\n{tail}"
            )
        time.sleep(0.25)

    raise GatewayError(
        f"the gateway did not become ready within {wait_seconds:.0f}s. "
        f"See {log_path}."
    )


def stop_gateway(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    """Ask a running gateway to stop. Needs a token, so logs in is not required
    if one was already issued."""
    from valeroy_backend import gateway as gateway_module

    record = gateway_module.read_runtime()
    client = GatewayClient(host, port)
    if record and record.get("token"):
        client.token = str(record["token"])
    return client.shutdown()
