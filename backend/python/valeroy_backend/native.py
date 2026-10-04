"""Bindings to the Valeroy native layers, with pure-Python fallbacks.

The C, C++ and Rust components are the real implementations. This module loads
them when they have been built and transparently falls back to Python when they
have not, so the app runs on a machine with no compiler while still using the
native path everywhere it is available.

Call :func:`status` to see which path is live.
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
import platform
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable

# --------------------------------------------------------------------------- #
# Locating build artifacts
# --------------------------------------------------------------------------- #

def repo_root() -> Path:
    """Project root, resolved from this file's location."""
    return Path(__file__).resolve().parents[3]


def native_dir() -> Path:
    override = os.environ.get("VALEROY_NATIVE_DIR")
    if override:
        return Path(override)
    return repo_root() / "build" / "native"


def _shared_lib_name(stem: str) -> str:
    system = platform.system()
    if system == "Windows":
        return f"{stem}.dll"
    if system == "Darwin":
        return f"lib{stem}.dylib"
    return f"lib{stem}.so"


def _load(stem: str) -> ctypes.CDLL | None:
    candidate = native_dir() / _shared_lib_name(stem)
    if not candidate.exists():
        return None
    try:
        return ctypes.CDLL(str(candidate))
    except OSError:
        return None


def core_binary() -> Path | None:
    """Path to the Rust ``valeroy-core`` executable, if it has been built."""
    override = os.environ.get("VALEROY_CORE_BIN")
    if override and Path(override).exists():
        return Path(override)

    exe = "valeroy-core.exe" if platform.system() == "Windows" else "valeroy-core"
    for profile in ("release", "debug"):
        candidate = repo_root() / "backend" / "core" / "target" / profile / exe
        if candidate.exists():
            return candidate
    return None


# --------------------------------------------------------------------------- #
# C hashing layer
# --------------------------------------------------------------------------- #

_hash_lib = _load("valeroy_hash")

if _hash_lib is not None:
    try:
        _hash_lib.vh_pbkdf2_sha256.argtypes = [
            ctypes.c_char_p, ctypes.c_size_t,
            ctypes.c_char_p, ctypes.c_size_t,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
        ]
        _hash_lib.vh_pbkdf2_sha256.restype = ctypes.c_int
        _hash_lib.vh_consttime_equal.argtypes = [
            ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t
        ]
        _hash_lib.vh_consttime_equal.restype = ctypes.c_int
    except AttributeError:
        _hash_lib = None


def pbkdf2_sha256(password: str, salt: bytes, iterations: int, dklen: int = 32) -> bytes:
    """PBKDF2-HMAC-SHA256 via the C layer, falling back to hashlib."""
    if _hash_lib is not None and len(salt) <= 128:
        out = (ctypes.c_uint8 * dklen)()
        rc = _hash_lib.vh_pbkdf2_sha256(
            password.encode("utf-8"), len(password.encode("utf-8")),
            salt, len(salt), iterations, out, dklen,
        )
        if rc == 0:
            return bytes(out)
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen)


def consttime_equal(a: bytes, b: bytes) -> bool:
    """Timing-safe comparison."""
    if len(a) != len(b):
        return False
    if _hash_lib is not None:
        buf_a = (ctypes.c_uint8 * len(a)).from_buffer_copy(a)
        buf_b = (ctypes.c_uint8 * len(b)).from_buffer_copy(b)
        return _hash_lib.vh_consttime_equal(buf_a, buf_b, len(a)) == 1
    return hmac.compare_digest(a, b)


# --------------------------------------------------------------------------- #
# C++ provider catalog
# --------------------------------------------------------------------------- #

_catalog_lib = _load("valeroy_catalog")

if _catalog_lib is not None:
    try:
        _catalog_lib.vcat_catalog_json.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
        _catalog_lib.vcat_catalog_json.restype = ctypes.c_int
        _catalog_lib.vcat_normalize_models.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t
        ]
        _catalog_lib.vcat_normalize_models.restype = ctypes.c_int
        _catalog_lib.vcat_version.restype = ctypes.c_char_p
    except AttributeError:
        _catalog_lib = None


# Mirrors backend/catalog/provider_catalog.cpp. Kept in sync by
# tests/test_parity.py, which fails the build if the two drift apart.
FALLBACK_CATALOG: list[dict[str, str]] = [
    {"id": "anthropic", "label": "Anthropic", "base_url": "https://api.anthropic.com/v1",
     "models_path": "/models", "auth_style": "x-api-key", "auth_field": "x-api-key",
     "kind": "chat", "docs": "https://docs.anthropic.com"},
    {"id": "cerebras", "label": "Cerebras", "base_url": "https://api.cerebras.ai/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "chat", "docs": "https://inference-docs.cerebras.ai"},
    {"id": "cohere", "label": "Cohere", "base_url": "https://api.cohere.com/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "chat", "docs": "https://docs.cohere.com"},
    {"id": "costruter", "label": "Costruter", "base_url": "https://api.costruter.com/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "multi", "docs": "https://costruter.com/docs"},
    {"id": "deepinfra", "label": "DeepInfra", "base_url": "https://api.deepinfra.com/v1/openai",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "multi", "docs": "https://deepinfra.com/docs"},
    {"id": "deepseek", "label": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "chat", "docs": "https://api-docs.deepseek.com"},
    {"id": "fal", "label": "fal.ai", "base_url": "https://fal.run",
     "models_path": "/models", "auth_style": "query", "auth_field": "fal_key",
     "kind": "video", "docs": "https://fal.ai/docs"},
    {"id": "fireworks", "label": "Fireworks AI",
     "base_url": "https://api.fireworks.ai/inference/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "multi", "docs": "https://docs.fireworks.ai"},
    {"id": "google", "label": "Google AI Studio",
     "base_url": "https://generativelanguage.googleapis.com/v1beta",
     "models_path": "/models", "auth_style": "query", "auth_field": "key",
     "kind": "multi", "docs": "https://ai.google.dev/docs"},
    {"id": "groq", "label": "Groq", "base_url": "https://api.groq.com/openai/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "chat", "docs": "https://console.groq.com/docs"},
    {"id": "hyperbolic", "label": "Hyperbolic", "base_url": "https://api.hyperbolic.xyz/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "multi", "docs": "https://docs.hyperbolic.xyz"},
    {"id": "lmstudio", "label": "LM Studio (local)", "base_url": "http://127.0.0.1:1234/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "chat", "docs": "https://lmstudio.ai/docs"},
    {"id": "mistral", "label": "Mistral AI", "base_url": "https://api.mistral.ai/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "chat", "docs": "https://docs.mistral.ai"},
    {"id": "novita", "label": "Novita AI", "base_url": "https://api.novita.ai/v3/openai",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "multi", "docs": "https://novita.ai/docs"},
    {"id": "ollama", "label": "Ollama (local)", "base_url": "http://127.0.0.1:11434/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "chat", "docs": "https://ollama.com/docs"},
    {"id": "openai", "label": "OpenAI", "base_url": "https://api.openai.com/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "multi", "docs": "https://platform.openai.com/docs"},
    {"id": "opencode", "label": "Opencode", "base_url": "https://opencode.ai/api/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "chat", "docs": "https://opencode.ai/docs"},
    {"id": "openrouter", "label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "multi", "docs": "https://openrouter.ai/docs"},
    {"id": "perplexity", "label": "Perplexity", "base_url": "https://api.perplexity.ai",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "chat", "docs": "https://docs.perplexity.ai"},
    {"id": "replicate", "label": "Replicate", "base_url": "https://api.replicate.com/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "video", "docs": "https://replicate.com/docs"},
    {"id": "runway", "label": "Runway", "base_url": "https://api.dev.runwayml.com/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "video", "docs": "https://docs.dev.runwayml.com"},
    {"id": "sambanova", "label": "SambaNova", "base_url": "https://api.sambanova.ai/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "chat", "docs": "https://docs.sambanova.ai"},
    {"id": "together", "label": "Together AI", "base_url": "https://api.together.xyz/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "multi", "docs": "https://docs.together.ai"},
    {"id": "xai", "label": "xAI", "base_url": "https://api.x.ai/v1",
     "models_path": "/models", "auth_style": "bearer", "auth_field": "Authorization",
     "kind": "multi", "docs": "https://docs.x.ai"},
]


def provider_catalog() -> list[dict[str, str]]:
    """Full provider catalog, from the C++ layer when available."""
    if _catalog_lib is not None:
        cap = 1 << 17
        buf = ctypes.create_string_buffer(cap)
        n = _catalog_lib.vcat_catalog_json(buf, cap)
        if n > 0:
            try:
                return json.loads(buf.value.decode("utf-8"))
            except json.JSONDecodeError:
                pass
    return list(FALLBACK_CATALOG)


def provider_by_id(provider_id: str) -> dict[str, str] | None:
    for entry in provider_catalog():
        if entry.get("id") == provider_id:
            return entry
    return None


_LIST_KEYS = ("data", "models", "results", "items", "model_list")
_ID_KEYS = ("id", "name", "model", "slug", "model_name")
_LABEL_KEYS = ("display_name", "displayName", "label", "title", "name", "id")
_CTX_KEYS = ("context_length", "context_window", "max_context_length",
             "max_input_tokens", "inputTokenLimit")


def _strip_namespace(model_id: str) -> str:
    head, _, tail = model_id.rpartition("/")
    if head in ("models", "accounts"):
        return tail
    return model_id


def _normalize_models_python(provider_id: str, raw: Any) -> list[dict[str, Any]]:
    """Fallback normalizer mirroring the C++ implementation."""
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return []

    items: Iterable[Any]
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        for key in _LIST_KEYS:
            value = raw.get(key)
            if isinstance(value, list):
                items = value
                break
        else:
            return []
    else:
        return []

    seen: dict[str, dict[str, Any]] = {}
    for item in items:
        if isinstance(item, str):
            model_id, label, context = item, item, 0
        elif isinstance(item, dict):
            model_id = next(
                (str(item[k]) for k in _ID_KEYS if isinstance(item.get(k), str) and item[k]),
                "",
            )
            label = next(
                (str(item[k]) for k in _LABEL_KEYS if isinstance(item.get(k), str) and item[k]),
                "",
            )
            context = 0
            for key in _CTX_KEYS:
                value = item.get(key)
                if isinstance(value, (int, float)):
                    context = int(value)
                    break
            if not context:
                nested = item.get("top_provider")
                if isinstance(nested, dict):
                    for key in ("context_length", "context_window"):
                        value = nested.get(key)
                        if isinstance(value, (int, float)):
                            context = int(value)
                            break
        else:
            continue

        if not model_id:
            continue
        model_id = _strip_namespace(model_id)
        seen[model_id] = {
            "id": model_id,
            "label": label or model_id,
            "context": context,
            "provider": provider_id,
        }

    return [seen[key] for key in sorted(seen)]


def normalize_models(provider_id: str, raw: Any) -> list[dict[str, Any]]:
    """Normalize a provider model-list payload into Valeroy's canonical shape."""
    if _catalog_lib is not None:
        text = raw if isinstance(raw, str) else json.dumps(raw)
        encoded = text.encode("utf-8")
        cap = max(1 << 16, len(encoded) * 3 + 1024)
        buf = ctypes.create_string_buffer(cap)
        n = _catalog_lib.vcat_normalize_models(
            provider_id.encode("utf-8"), encoded, buf, cap
        )
        if n > 0:
            try:
                return json.loads(buf.value.decode("utf-8"))
            except json.JSONDecodeError:
                pass
    return _normalize_models_python(provider_id, raw)


# --------------------------------------------------------------------------- #
# C++ render accelerator
# --------------------------------------------------------------------------- #

_render_lib = _load("vtui_render")

if _render_lib is not None:
    try:
        _render_lib.vr_display_width.argtypes = [ctypes.c_char_p]
        _render_lib.vr_display_width.restype = ctypes.c_int32
        _render_lib.vr_truncate.argtypes = [
            ctypes.c_char_p, ctypes.c_int32, ctypes.c_char_p, ctypes.c_size_t
        ]
        _render_lib.vr_truncate.restype = ctypes.c_int32
        _render_lib.vr_wrap.argtypes = [
            ctypes.c_char_p, ctypes.c_int32, ctypes.c_char_p, ctypes.c_size_t
        ]
        _render_lib.vr_wrap.restype = ctypes.c_int32
        _render_lib.vr_version.restype = ctypes.c_char_p
    except AttributeError:
        _render_lib = None


def _char_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    code = ord(ch)
    if code == 0 or code < 0x20 or 0x7F <= code < 0xA0:
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def display_width(text: str) -> int:
    """Terminal column count for `text`."""
    if _render_lib is not None:
        return int(_render_lib.vr_display_width(text.encode("utf-8")))
    return sum(_char_width(ch) for ch in text)


def truncate(text: str, max_cols: int) -> str:
    """Clip `text` to `max_cols` columns, adding an ellipsis when it had to cut."""
    if max_cols <= 0:
        return ""
    if _render_lib is not None:
        encoded = text.encode("utf-8")
        cap = len(encoded) + 16
        buf = ctypes.create_string_buffer(cap)
        if _render_lib.vr_truncate(encoded, max_cols, buf, cap) >= 0:
            return buf.value.decode("utf-8", "replace")

    if display_width(text) <= max_cols:
        return text
    budget = max_cols - 1
    out: list[str] = []
    used = 0
    for ch in text:
        w = _char_width(ch)
        if used + w > budget:
            break
        out.append(ch)
        used += w
    return "".join(out) + "…"


def wrap(text: str, width: int) -> list[str]:
    """Word-wrap `text` to `width` columns."""
    if width <= 0:
        return [text]
    if _render_lib is not None:
        encoded = text.encode("utf-8")
        cap = len(encoded) * 2 + 1024
        buf = ctypes.create_string_buffer(cap)
        if _render_lib.vr_wrap(encoded, width, buf, cap) >= 0:
            return buf.value.decode("utf-8", "replace").split("\n")

    lines: list[str] = []
    for paragraph in text.split("\n"):
        line: list[str] = []
        line_width = 0
        for word in paragraph.split():
            word_width = display_width(word)
            if line and line_width + 1 + word_width > width:
                lines.append(" ".join(line))
                line, line_width = [], 0
            if word_width > width:
                if line:
                    lines.append(" ".join(line))
                    line, line_width = [], 0
                chunk, chunk_width = "", 0
                for ch in word:
                    w = _char_width(ch)
                    if chunk_width + w > width:
                        lines.append(chunk)
                        chunk, chunk_width = "", 0
                    chunk += ch
                    chunk_width += w
                if chunk:
                    line, line_width = [chunk], chunk_width
                continue
            line.append(word)
            line_width += word_width + (1 if line_width else 0)
        lines.append(" ".join(line))
    return lines


# --------------------------------------------------------------------------- #
# Rust core bridge
# --------------------------------------------------------------------------- #

class CoreError(RuntimeError):
    """Raised when valeroy-core reports a failure."""


def core(*args: str, stdin: str | None = None, timeout: float = 30.0) -> dict[str, Any]:
    """Invoke valeroy-core and return its parsed JSON reply.

    Raises CoreError when the binary is missing or the command fails.
    """
    binary = core_binary()
    if binary is None:
        raise CoreError(
            "valeroy-core is not built. Run scripts/build.ps1 (or "
            "`cargo build --release` in backend/core)."
        )
    try:
        proc = subprocess.run(
            [str(binary), *args],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise CoreError(f"valeroy-core timed out after {timeout}s") from exc
    except OSError as exc:
        raise CoreError(f"cannot run valeroy-core: {exc}") from exc

    text = (proc.stdout or "").strip()
    if not text:
        raise CoreError((proc.stderr or "valeroy-core produced no output").strip())
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CoreError(f"valeroy-core returned unparseable output: {text[:200]}") from exc

    if not payload.get("ok"):
        raise CoreError(str(payload.get("error", "valeroy-core failed")))
    return payload


def core_available() -> bool:
    return core_binary() is not None


# --------------------------------------------------------------------------- #
# Diagnostics
# --------------------------------------------------------------------------- #

def status() -> dict[str, Any]:
    """Which implementation is live for each layer."""
    return {
        "native_dir": str(native_dir()),
        "hash": "c" if _hash_lib is not None else "python",
        "catalog": "c++" if _catalog_lib is not None else "python",
        "render": "c++" if _render_lib is not None else "python",
        "core": str(core_binary()) if core_binary() else None,
        "catalog_version": (
            _catalog_lib.vcat_version().decode() if _catalog_lib is not None else None
        ),
        "render_version": (
            _render_lib.vr_version().decode() if _render_lib is not None else None
        ),
        "python": sys.version.split()[0],
    }
