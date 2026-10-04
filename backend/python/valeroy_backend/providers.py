"""Provider HTTP adapters.

One small adapter surface covers every provider in the catalog:

* :func:`list_models`   - GET the provider's model list, normalized by the C++ layer
* :func:`stream_chat`   - POST a chat completion and yield text deltas
* :func:`submit_video`  - POST a video/animation job (used by ``/animate``)

Only the standard library is used, so Valeroy has no pip dependencies.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterator

from . import native

DEFAULT_TIMEOUT = 60.0
STREAM_TIMEOUT = 600.0
USER_AGENT = "Valeroy-AI/1.0 (+https://github.com/Mcalrifle789/Valeroy-AI)"


class ProviderError(RuntimeError):
    """A provider rejected the request or could not be reached."""

    def __init__(self, message: str, *, status: int | None = None, provider: str = ""):
        super().__init__(message)
        self.status = status
        self.provider = provider


@dataclass
class ProviderConfig:
    """Everything needed to talk to one provider."""

    id: str
    api_key: str
    base_url: str = ""
    auth_style: str = "bearer"
    auth_field: str = "Authorization"
    models_path: str = "/models"
    kind: str = "chat"
    extra_headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_catalog(cls, provider_id: str, api_key: str,
                     base_url: str | None = None) -> "ProviderConfig":
        entry = native.provider_by_id(provider_id)
        if entry is None:
            # Unknown provider: usable as long as the caller supplies a base url.
            if not base_url:
                raise ProviderError(
                    f"'{provider_id}' is not in the catalog; a base url is required",
                    provider=provider_id,
                )
            return cls(id=provider_id, api_key=api_key, base_url=base_url.rstrip("/"))
        return cls(
            id=provider_id,
            api_key=api_key,
            base_url=(base_url or entry["base_url"]).rstrip("/"),
            auth_style=entry.get("auth_style", "bearer"),
            auth_field=entry.get("auth_field", "Authorization"),
            models_path=entry.get("models_path", "/models"),
            kind=entry.get("kind", "chat"),
        )


# --------------------------------------------------------------------------- #
# Request plumbing
# --------------------------------------------------------------------------- #

def _apply_auth(config: ProviderConfig, url: str,
                headers: dict[str, str]) -> str:
    """Attach credentials per the provider's auth style. Returns the final URL."""
    style = config.auth_style
    if style == "bearer":
        headers[config.auth_field] = f"Bearer {config.api_key}"
    elif style == "x-api-key":
        headers[config.auth_field] = config.api_key
        # Anthropic also requires a version header.
        headers.setdefault("anthropic-version", "2023-06-01")
    elif style == "query":
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urllib.parse.quote(config.auth_field)}=" \
              f"{urllib.parse.quote(config.api_key)}"
    else:
        headers[config.auth_field] = config.api_key
    return url


def _request(config: ProviderConfig, path: str, *, method: str = "GET",
             body: dict[str, Any] | None = None,
             timeout: float = DEFAULT_TIMEOUT,
             stream: bool = False):
    url = path if path.startswith("http") else f"{config.base_url}{path}"
    headers = {
        "Accept": "text/event-stream" if stream else "application/json",
        "User-Agent": USER_AGENT,
        **config.extra_headers,
    }
    url = _apply_auth(config, url, headers)

    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            raw = exc.read().decode("utf-8", "replace")
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                error = parsed.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message") or error)
                elif error:
                    detail = str(error)
                else:
                    detail = str(parsed.get("message") or raw)[:300]
            else:
                detail = raw[:300]
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            detail = ""
        hint = {
            401: "the API key was rejected",
            403: "the API key lacks permission for this call",
            404: "the endpoint does not exist on this provider",
            429: "rate limited - slow down or check your plan",
        }.get(exc.code, "")
        parts = [p for p in (f"HTTP {exc.code}", hint, detail) if p]
        raise ProviderError(" - ".join(parts), status=exc.code, provider=config.id) from exc
    except urllib.error.URLError as exc:
        raise ProviderError(
            f"cannot reach {config.id}: {exc.reason}", provider=config.id
        ) from exc
    except TimeoutError as exc:
        raise ProviderError(f"{config.id} timed out", provider=config.id) from exc


# --------------------------------------------------------------------------- #
# Model discovery
# --------------------------------------------------------------------------- #

def list_models(config: ProviderConfig,
                timeout: float = DEFAULT_TIMEOUT) -> list[dict[str, Any]]:
    """Fetch and normalize the provider's model list.

    This is what populates the ``/model`` picker: every model the provider
    exposes for the supplied key.
    """
    with _request(config, config.models_path, timeout=timeout) as response:
        raw = response.read().decode("utf-8", "replace")
    return native.normalize_models(config.id, raw)


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #

def _anthropic_body(model: str, messages: list[dict[str, str]],
                    system: str, max_tokens: int, temperature: float,
                    stream: bool) -> dict[str, Any]:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": stream,
        **({"system": system} if system else {}),
        "messages": [m for m in messages if m.get("role") != "system"],
    }


def _openai_body(model: str, messages: list[dict[str, str]],
                 system: str, max_tokens: int, temperature: float,
                 stream: bool) -> dict[str, Any]:
    full = ([{"role": "system", "content": system}] if system else []) + messages
    return {
        "model": model,
        "messages": full,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": stream,
    }


def _extract_delta(provider_id: str, event: dict[str, Any]) -> str:
    """Pull the text increment out of one streaming event."""
    if provider_id == "anthropic":
        if event.get("type") == "content_block_delta":
            delta = event.get("delta") or {}
            return str(delta.get("text") or "")
        return ""

    choices = event.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0] or {}
        delta = choice.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str):
                return content
            # Some providers send a list of content parts.
            if isinstance(content, list):
                return "".join(
                    str(part.get("text", ""))
                    for part in content
                    if isinstance(part, dict)
                )
        message = choice.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
    return ""


def _extract_usage(provider_id: str, event: dict[str, Any]) -> dict[str, int]:
    usage = event.get("usage")
    if not isinstance(usage, dict):
        return {}
    if provider_id == "anthropic":
        prompt = int(usage.get("input_tokens") or 0)
        completion = int(usage.get("output_tokens") or 0)
    else:
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))
    if not (prompt or completion or total):
        return {}
    return {"prompt": prompt, "completion": completion, "total": total}


def stream_chat(config: ProviderConfig, model: str,
                messages: list[dict[str, str]], *,
                system: str = "",
                max_tokens: int = 4096,
                temperature: float = 0.7,
                timeout: float = STREAM_TIMEOUT) -> Iterator[dict[str, Any]]:
    """Stream a chat completion.

    Yields ``{"type": "delta", "text": ...}`` for each increment, then one
    ``{"type": "done", "usage": {...}}``. Usage is estimated when the provider
    does not report it.
    """
    if config.id == "anthropic":
        path, build = "/messages", _anthropic_body
    else:
        path, build = "/chat/completions", _openai_body

    body = build(model, messages, system, max_tokens, temperature, True)

    text_length = 0
    usage: dict[str, int] = {}
    try:
        with _request(config, path, method="POST", body=body,
                      timeout=timeout, stream=True) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                if isinstance(event, dict) and event.get("error"):
                    error = event["error"]
                    message = (
                        error.get("message") if isinstance(error, dict) else str(error)
                    )
                    raise ProviderError(str(message), provider=config.id)

                delta = _extract_delta(config.id, event)
                if delta:
                    text_length += len(delta)
                    yield {"type": "delta", "text": delta}

                found = _extract_usage(config.id, event)
                if found:
                    usage = found
    except ProviderError:
        raise

    if not usage:
        # ~4 characters per token is close enough for a live counter.
        prompt_chars = sum(len(m.get("content", "")) for m in messages) + len(system)
        usage = {
            "prompt": max(1, prompt_chars // 4),
            "completion": max(1, text_length // 4),
            "total": max(1, (prompt_chars + text_length) // 4),
            "estimated": 1,
        }

    yield {"type": "done", "usage": usage}


def complete(config: ProviderConfig, model: str, prompt: str, *,
             system: str = "", max_tokens: int = 2048,
             temperature: float = 0.7) -> str:
    """Non-streaming single-turn completion. Used by /humanize and /agents."""
    chunks: list[str] = []
    for event in stream_chat(
        config, model, [{"role": "user", "content": prompt}],
        system=system, max_tokens=max_tokens, temperature=temperature,
    ):
        if event["type"] == "delta":
            chunks.append(event["text"])
    return "".join(chunks).strip()


# --------------------------------------------------------------------------- #
# Video / animation
# --------------------------------------------------------------------------- #

VIDEO_CAPABLE = {"fal", "replicate", "runway", "novita", "openai", "google"}


def submit_video(config: ProviderConfig, model: str, prompt: str, *,
                 images: list[str] | None = None,
                 duration_seconds: int = 5,
                 aspect_ratio: str = "16:9",
                 timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Submit an animation job.

    Returns the provider's job record. ``/animate`` polls it with
    :func:`poll_video`. No Valeroy wordmark is applied to the output.
    """
    images = images or []
    if config.id == "replicate":
        path = "/predictions"
        body = {
            "input": {
                "prompt": prompt,
                "num_frames": max(1, duration_seconds * 8),
                "aspect_ratio": aspect_ratio,
                **({"image": images[0]} if images else {}),
                **({"images": images} if len(images) > 1 else {}),
            }
        }
        if "/" in model:
            body["version"] = model
        else:
            path = f"/models/{model}/predictions"
    elif config.id == "runway":
        path = "/image_to_video" if images else "/text_to_video"
        body = {
            "model": model,
            "promptText": prompt,
            "duration": duration_seconds,
            "ratio": aspect_ratio,
            **({"promptImage": images[0]} if images else {}),
        }
    elif config.id == "fal":
        path = f"/{model}"
        body = {
            "prompt": prompt,
            "duration": duration_seconds,
            "aspect_ratio": aspect_ratio,
            **({"image_url": images[0]} if images else {}),
            **({"image_urls": images} if len(images) > 1 else {}),
        }
    else:
        # OpenAI-compatible video endpoint.
        path = "/videos"
        body = {
            "model": model,
            "prompt": prompt,
            "seconds": duration_seconds,
            "size": aspect_ratio,
            **({"input_reference": images[0]} if images else {}),
        }

    with _request(config, path, method="POST", body=body, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def poll_video(config: ProviderConfig, job: dict[str, Any],
               timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Re-read a submitted video job. Returns the provider's current record."""
    job_id = job.get("id") or job.get("request_id") or job.get("name")
    if not job_id:
        return job

    url = None
    urls = job.get("urls")
    if isinstance(urls, dict) and urls.get("get"):
        url = str(urls["get"])
    elif job.get("status_url"):
        url = str(job["status_url"])

    path = url or (
        f"/predictions/{job_id}" if config.id == "replicate"
        else f"/tasks/{job_id}" if config.id == "runway"
        else f"/videos/{job_id}"
    )
    with _request(config, path, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def video_output_urls(job: dict[str, Any]) -> list[str]:
    """Pull finished asset URLs out of a provider job record."""
    found: list[str] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 6 or len(found) > 16:
            return
        if isinstance(node, str):
            lowered = node.lower()
            if lowered.startswith("http") and any(
                lowered.split("?")[0].endswith(ext)
                for ext in (".mp4", ".webm", ".mov", ".gif")
            ):
                found.append(node)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
        elif isinstance(node, dict):
            for key in ("output", "video", "videos", "assets", "url", "uri",
                        "download_url", "result", "data"):
                if key in node:
                    walk(node[key], depth + 1)
            # Fall back to a broad sweep if the named keys found nothing.
            if not found:
                for value in node.values():
                    walk(value, depth + 1)

    walk(job)
    seen: set[str] = set()
    return [u for u in found if not (u in seen or seen.add(u))]
