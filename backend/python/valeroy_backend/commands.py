"""The Valeroy command catalog and the handlers that need a model.

The catalog is the single source of truth for the ``/`` dropdown in the TUI and
for the gateway's ``/command`` endpoint. Commands carried over from the original
Valeroy build are kept; the spec's new commands are added alongside them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from . import providers
from .providers import ProviderConfig, ProviderError


@dataclass(frozen=True)
class Command:
    """One slash command as the dropdown and dispatcher see it."""

    name: str
    summary: str
    usage: str = ""
    category: str = "general"
    # "ui"    - the TUI handles it locally (pickers, panels, toggles)
    # "core"  - state change through valeroy-core
    # "model" - needs a live model call through the gateway
    handler: str = "ui"
    needs_model: bool = False
    arg_hint: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def slash(self) -> str:
        return f"/{self.name}"


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #

COMMANDS: tuple[Command, ...] = (
    # ---- models and providers (spec section 2) ----
    Command("model", "Switch the active model", "/model [model-id]", "models",
            handler="ui", arg_hint="model"),
    Command("models", "Add a custom model with its own API key",
            "/models [model-id] [base-url]", "models", handler="ui",
            arg_hint="model"),
    Command("provider", "Switch or inspect the active provider", "/provider [id]",
            "models", handler="ui", arg_hint="provider"),
    Command("providers", "Enable, disable and key providers", "/providers",
            "models", handler="ui"),
    Command("keys", "Review stored API keys (fingerprints only)", "/keys",
            "models", handler="ui"),

    # ---- sessions and agents (spec section 2) ----
    Command("sessions", "Switch between sessions across all agents", "/sessions",
            "sessions", handler="ui"),
    Command("new", "Create a new session", "/new [title]", "sessions",
            handler="core", arg_hint="text"),
    Command("agent", "Switch the active agent", "/agent [name]", "agents",
            handler="ui", arg_hint="agent"),
    Command("agents", "Create a custom Valeroy agent from a description",
            "/agents [name] -- [description]", "agents", handler="model",
            needs_model=True, arg_hint="text"),
    Command("rename", "Rename the current session", "/rename <title>", "sessions",
            handler="core", arg_hint="text"),
    Command("delete", "Delete the current session", "/delete", "sessions",
            handler="core"),
    Command("resume", "Reopen the most recent session", "/resume", "sessions",
            handler="core"),
    Command("history", "Show the transcript of the current session", "/history [n]",
            "sessions", handler="ui"),
    Command("export", "Write the current session to a file", "/export [path]",
            "sessions", handler="core", arg_hint="file"),

    # ---- generation (spec section 2) ----
    Command("humanize", "Rewrite text so it reads as human-written",
            "/humanize <text>", "generate", handler="model", needs_model=True,
            arg_hint="text"),
    Command("animate", "Animate one or more images into video",
            "/animate <prompt> [--image path ...]", "generate", handler="model",
            needs_model=True, arg_hint="file"),
    Command("image", "Generate an image", "/image <prompt>", "generate",
            handler="model", needs_model=True, arg_hint="text"),
    Command("summarize", "Summarize text, a file, or the session",
            "/summarize [path]", "generate", handler="model", needs_model=True,
            arg_hint="file"),
    Command("translate", "Translate text into another language",
            "/translate <lang> <text>", "generate", handler="model",
            needs_model=True, arg_hint="text"),
    Command("explain", "Explain code or a concept", "/explain <topic>", "generate",
            handler="model", needs_model=True, arg_hint="text"),
    Command("review", "Review code for bugs and clarity", "/review [path]",
            "generate", handler="model", needs_model=True, arg_hint="file"),
    Command("refactor", "Suggest a refactor for a file", "/refactor <path>",
            "generate", handler="model", needs_model=True, arg_hint="file"),
    Command("test", "Write tests for a file", "/test <path>", "generate",
            handler="model", needs_model=True, arg_hint="file"),
    Command("commit", "Draft a commit message from staged changes", "/commit",
            "generate", handler="model", needs_model=True),

    # ---- workspace ----
    Command("files", "Browse files attached to this session", "/files", "workspace"),
    Command("attach", "Attach a file to the conversation", "/attach <path>",
            "workspace", handler="core", arg_hint="file"),
    Command("detach", "Remove an attached file", "/detach <path>", "workspace",
            handler="core", arg_hint="file"),
    Command("cd", "Change the working directory", "/cd <path>", "workspace",
            handler="core", arg_hint="file"),
    Command("pwd", "Show the working directory", "/pwd", "workspace"),
    Command("search", "Search the web", "/search <query>", "workspace",
            handler="model", needs_model=True, arg_hint="text"),

    # ---- app ----
    Command("theme", "Cycle or pick a theme", "/theme [name]", "app",
            handler="ui", arg_hint="theme"),
    Command("status", "Show gateway, model and token status", "/status", "app"),
    Command("tokens", "Show token usage for this session and overall", "/tokens",
            "app"),
    Command("gateway", "Inspect or restart the gateway", "/gateway [restart]",
            "app", handler="ui"),
    Command("mcp", "Manage MCP integrations", "/mcp", "app", handler="ui",
            arg_hint="mcp"),
    Command("setup", "Re-run the setup wizard", "/setup", "app", handler="ui"),
    Command("passwd", "Change your account password", "/passwd", "app",
            handler="ui"),
    Command("approve", "Approve the pending permission request", "/approve", "app"),
    Command("deny", "Deny the pending permission request", "/deny", "app"),
    Command("clear", "Clear the transcript view", "/clear", "app"),
    Command("banner", "Show, hide or toggle the logo banner", "/banner [on|off]",
            "app", handler="ui", arg_hint="on|off"),
    Command("help", "List every command", "/help [command]", "app",
            arg_hint="command"),
    Command("doctor", "Report which native layers are active", "/doctor", "app"),
    Command("quit", "Leave Valeroy", "/quit", "app", aliases=("exit",)),
)

BY_NAME: dict[str, Command] = {}
for _command in COMMANDS:
    BY_NAME[_command.name] = _command
    for _alias in _command.aliases:
        BY_NAME[_alias] = _command

CATEGORIES: tuple[str, ...] = (
    "models", "sessions", "agents", "generate", "workspace", "app", "general",
)


def lookup(name: str) -> Command | None:
    return BY_NAME.get(name.lstrip("/").split()[0] if name.strip() else "")


def complete(prefix: str) -> list[Command]:
    """Commands matching a typed ``/`` prefix, best match first.

    Drives the dropdown menu that opens when ``/`` is the first character in the
    chatbox.
    """
    needle = prefix.lstrip("/").lower()
    if not needle:
        return list(COMMANDS)

    starts: list[Command] = []
    contains: list[Command] = []
    fuzzy: list[Command] = []
    for command in COMMANDS:
        name = command.name.lower()
        if name.startswith(needle):
            starts.append(command)
        elif needle in name:
            contains.append(command)
        elif _subsequence(needle, name) or needle in command.summary.lower():
            fuzzy.append(command)
    return starts + contains + fuzzy


def _subsequence(needle: str, haystack: str) -> bool:
    it = iter(haystack)
    return all(ch in it for ch in needle)


def parse(line: str) -> tuple[Command | None, str]:
    """Split a chatbox line into a command and its argument text."""
    text = line.strip()
    if not text.startswith("/"):
        return None, text
    head, _, rest = text[1:].partition(" ")
    return BY_NAME.get(head.lower()), rest.strip()


# --------------------------------------------------------------------------- #
# Model-backed handlers
# --------------------------------------------------------------------------- #

HUMANIZE_SYSTEM = """\
You rewrite text so it reads as though a person wrote it.

Rules:
- Keep the original meaning, facts and approximate length.
- Vary sentence length. Mix short sentences with longer ones.
- Prefer plain words over inflated ones. Cut filler and hedging.
- Remove the telltale signs of generated prose: no "delve", "tapestry",
  "it is important to note", "in conclusion", "furthermore", no three-item
  lists in every sentence, no symmetrical paragraph lengths.
- Keep contractions where they fit naturally.
- Do not add commentary, headings, or explanation. Return only the rewrite.
"""

AGENT_SYSTEM = """\
You turn a short description of an assistant into its operating instructions.

Write the instructions in second person, addressed to the agent ("You are ...").
Cover: what the agent is for, how it should behave, its tone, what it should
prioritize, and what it should refuse or escalate. Be specific and concrete.
Return only the instructions, 120-300 words, no headings or preamble.
"""


def humanize(config: ProviderConfig, model: str, text: str) -> str:
    """Rewrite `text` to read as human-written. Backs ``/humanize``."""
    if not text.strip():
        raise ValueError("/humanize needs some text to rewrite")
    return providers.complete(
        config, model, text, system=HUMANIZE_SYSTEM,
        max_tokens=max(512, len(text) // 2), temperature=0.85,
    )


def build_agent(config: ProviderConfig, model: str, name: str,
                description: str) -> dict[str, str]:
    """Turn a description into a full agent definition. Backs ``/agents``.

    The spec allows this to be reached either through ``/agents`` or by simply
    asking the model to create an agent in the chatbox; both land here.
    """
    if not name.strip():
        raise ValueError("an agent needs a name")
    if not description.strip():
        raise ValueError("an agent needs a description of what it does")

    prompt = (
        f"Agent name: {name.strip()}\n"
        f"Description of what it does: {description.strip()}\n\n"
        "Write this agent's operating instructions."
    )
    instructions = providers.complete(
        config, model, prompt, system=AGENT_SYSTEM, max_tokens=900, temperature=0.6
    )
    if not instructions:
        raise ProviderError("the model returned no instructions for the agent")
    return {
        "name": name.strip(),
        "description": description.strip(),
        "instructions": instructions,
    }


# Natural-language agent creation, so "make me an agent called Scribe that
# takes meeting notes" works without the /agents command.
_AGENT_INTENT = re.compile(
    r"""\b(?:make|create|build|set\s*up|add)\b
        [^.;\n]{0,40}?\bagent\b
        (?:[^.;\n]{0,30}?\b(?:called|named)\s+
           (?P<name>"[^"]{1,64}"|'[^']{1,64}'|[\w][\w .-]{0,63}?))?
        \s*(?:\bthat\b|\bwhich\b|\bto\b|[:,-])\s*
        (?P<description>.+)""",
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


def detect_agent_request(text: str) -> dict[str, str] | None:
    """Spot a plain-language request to create an agent.

    Returns ``{"name": ..., "description": ...}`` or None.
    """
    match = _AGENT_INTENT.search(text.strip())
    if not match:
        return None
    name = (match.group("name") or "").strip().strip("\"'")
    description = (match.group("description") or "").strip()
    if not description:
        return None
    if not name:
        # Derive a name from the first few words of the description.
        words = re.findall(r"[A-Za-z0-9]+", description)[:2]
        name = " ".join(w.capitalize() for w in words) or "New Agent"
    return {"name": name, "description": description}


def split_agents_args(raw: str) -> tuple[str, str]:
    """Split ``/agents`` arguments into a name and a description.

    Accepts ``Name -- description``, ``Name: description`` or just a
    description.
    """
    text = raw.strip()
    if not text:
        return "", ""
    for separator in ("--", ":", " - "):
        if separator in text:
            name, _, description = text.partition(separator)
            if name.strip() and description.strip():
                return name.strip(), description.strip()
    words = text.split()
    if len(words) <= 3:
        return text, ""
    return "", text


def animate(config: ProviderConfig, model: str, prompt: str,
            images: list[str] | None = None, *,
            duration_seconds: int = 5,
            aspect_ratio: str = "16:9") -> dict[str, Any]:
    """Submit an animation job. Backs ``/animate``.

    Only video-capable providers are accepted. No Valeroy wordmark is applied
    to generated video, per the spec.
    """
    if not prompt.strip() and not images:
        raise ValueError("/animate needs a prompt or at least one image")
    if config.kind not in ("video", "multi") and config.id not in providers.VIDEO_CAPABLE:
        raise ProviderError(
            f"{config.id} does not expose video models; /animate needs one of: "
            + ", ".join(sorted(providers.VIDEO_CAPABLE))
        )
    job = providers.submit_video(
        config, model, prompt, images=images or [],
        duration_seconds=duration_seconds, aspect_ratio=aspect_ratio,
    )
    return {"job": job, "watermark": False}


HANDLERS: dict[str, Callable[..., Any]] = {
    "humanize": humanize,
    "agents": build_agent,
    "animate": animate,
}


def catalog_payload() -> list[dict[str, Any]]:
    """Catalog as JSON, for the gateway's ``/commands`` endpoint."""
    return [
        {
            "name": c.name,
            "summary": c.summary,
            "usage": c.usage or c.slash,
            "category": c.category,
            "handler": c.handler,
            "needs_model": c.needs_model,
            "arg_hint": c.arg_hint,
            "aliases": list(c.aliases),
        }
        for c in COMMANDS
    ]
