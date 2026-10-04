"""The Valeroy AI terminal application.

No panels, no boxes: a status line at the top, the conversation in the middle,
and the chatbox centred along the bottom, exactly as the spec describes. Typing
``/`` as the first character opens the command dropdown.

The app is a client. It reads state straight from ``valeroy-core`` (fast, local,
no secrets) and routes model work and provider calls through the gateway, which
is the only process that ever sees an API key.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from typing import Any

from valeroy_backend import commands, native

from . import prompts, setup_wizard, surface as surface_mod, theme as theme_mod
from .client import GatewayClient, GatewayError, spawn_gateway, stop_gateway
from .surface import BOLD, REVERSE
from .terminal import Terminal
from .theme import Theme
from .widgets import Chooser, Choice, Editor, Transcript

HEALTH_INTERVAL = 2.0
POLL_TIMEOUT = 0.05


def _config_path() -> str:
    paths = native.core("state", "path")
    return os.path.join(paths["home"], "frontend.json")


def _load_prefs() -> dict[str, Any]:
    try:
        with open(_config_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_prefs(prefs: dict[str, Any]) -> None:
    try:
        with open(_config_path(), "w", encoding="utf-8") as fh:
            json.dump(prefs, fh)
    except OSError:
        pass


class App:
    """Owns the screen, the input and the conversation."""

    def __init__(self, client: GatewayClient, data_key: str,
                 host: str, port: int) -> None:
        self.client = client
        self.data_key = data_key
        self.host = host
        self.port = port

        self.term = Terminal()
        self.surface = surface_mod.create(*self.term.size())
        self.editor = Editor()
        self.transcript = Transcript()
        self.chooser: Chooser | None = None
        self.chooser_kind = ""  # "command" | "model" | "provider" | "session" | "agent" | "theme"

        self.prefs = _load_prefs()
        self.theme: Theme = theme_mod.get(self.prefs.get("theme"))

        self.state: dict[str, Any] = {}
        self.messages: list[dict[str, str]] = []
        self.system = ""
        self.active_session: str | None = None

        self._events: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stream_msg = None
        self._busy = False
        self._health: dict[str, Any] | None = None
        self._health_checked = 0.0
        self._dirty = True
        self._running = True

    # -- lifecycle --------------------------------------------------------- #

    def run(self) -> int:
        self.refresh_state()
        self._ensure_session()
        self._load_active_transcript()
        self._health = self.client.health()

        with self.term:
            self.transcript.add(
                "note",
                f"Welcome back, {self._username()}. Type a message, or / for commands.",
            )
            while self._running:
                self._drain_events()
                self._poll_health()
                if self._dirty:
                    self.render()
                    self._dirty = False
                key = self.term.read_key(timeout=POLL_TIMEOUT)
                if key is not None:
                    self._handle_key(key)
        return 0

    # -- state ------------------------------------------------------------- #

    def refresh_state(self) -> None:
        try:
            self.state = native.core("state", "show")["state"]
        except native.CoreError as exc:
            self.state = {}
            self.transcript.add("error", f"cannot read state: {exc}")
        self.system = self._agent_instructions()
        self._dirty = True

    def _username(self) -> str:
        return (self.state.get("account") or {}).get("username") or "there"

    def _agent_instructions(self) -> str:
        active = self.state.get("active_agent")
        for agent in self.state.get("agents", []):
            if agent.get("id") == active:
                return str(agent.get("instructions") or "")
        return ""

    def _ensure_session(self) -> None:
        self.active_session = self.state.get("active_session")
        if not self.active_session:
            try:
                created = native.core("session", "new", "--title", "New session")
                self.active_session = created["id"]
                self.refresh_state()
            except native.CoreError as exc:
                self.transcript.add("error", f"cannot create a session: {exc}")

    def _load_active_transcript(self) -> None:
        self.messages = []
        if not self.active_session:
            return
        try:
            rows = native.core("session", "transcript", "--id", self.active_session,
                               "--limit", "100")["messages"]
        except native.CoreError:
            return
        for row in rows:
            role = row.get("role", "")
            content = str(row.get("content", ""))
            if role in ("user", "assistant"):
                self.messages.append({"role": role, "content": content})
                self.transcript.add(role, content)

    # -- rendering --------------------------------------------------------- #

    def render(self) -> None:
        cols, rows = self.term.size()
        self.surface.resize(cols, rows)
        th = self.theme
        self.surface.clear()
        self.surface.fill(0, 0, cols, rows, th.base)

        self._draw_status_bar(cols, th)

        # The chatbox is a centred strip two rows tall near the bottom.
        box_width = min(max(40, cols - 8), 110)
        box_x = (cols - box_width) // 2
        box_y = rows - 2
        footer_y = rows - 1

        transcript_top = 2
        transcript_height = max(1, box_y - 1 - transcript_top)
        self._draw_transcript(transcript_top, transcript_height, cols, th)

        self._draw_chatbox(box_x, box_y, box_width, th)
        self._draw_footer(footer_y, cols, th)

        # The command dropdown floats just above the chatbox.
        if self.chooser is not None and self.chooser.active:
            self._draw_chooser(box_x, box_y, box_width, transcript_top, th)

        self.term.write(self.surface.flush())
        self.term.flush()

    def _draw_status_bar(self, cols: int, th: Theme) -> None:
        self.surface.fill(0, 0, cols, 1, th.surface)
        self.surface.put(1, 0, "✦ valeroy", fg=th.accent, bg=th.surface, attr=BOLD)

        model = self.state.get("active_model") or "no model"
        provider = self.state.get("active_provider") or ""
        label = f"{provider}:{model}" if provider and model != "no model" else model

        usage = self.state.get("usage") or {}
        tokens = int(usage.get("total_tokens") or 0)

        connected = self._health is not None
        dot = "●" if connected else "○"
        dot_fg = th.ok if connected else th.error
        gw = "gateway up" if connected else "gateway down"
        impl = (self._health or {}).get("implementation", "")
        if impl:
            gw += f" ({impl})"

        right = f"{label}   {tokens:,} tok   "
        x = cols - native.display_width(right) - native.display_width(gw) - 3
        self.surface.put(max(12, x), 0, right, fg=th.text, bg=th.surface)
        self.surface.put(cols - native.display_width(gw) - 3, 0, dot,
                         fg=dot_fg, bg=th.surface, attr=BOLD)
        self.surface.put(cols - native.display_width(gw) - 1, 0, gw,
                         fg=th.muted, bg=th.surface)

    def _draw_transcript(self, top: int, height: int, cols: int, th: Theme) -> None:
        margin = 2
        width = cols - margin * 2
        rows = self.transcript.visible_rows(width, height, th)
        for i, (text, fg, attr) in enumerate(rows):
            if text:
                self.surface.put(margin, top + i, text, fg=fg, bg=th.base, attr=attr)
        if self.transcript.scroll > 0:
            tag = f"↑ {self.transcript.scroll} more"
            self.surface.put(cols - margin - len(tag), top, tag, fg=th.muted, bg=th.base)

    def _draw_chatbox(self, x: int, y: int, width: int, th: Theme) -> None:
        self.surface.fill(x, y, width, 1, th.surface)
        marker = "  › "
        self.surface.put(x, y, marker, fg=th.accent, bg=th.surface, attr=BOLD)
        field_x = x + native.display_width(marker)
        field_w = width - native.display_width(marker) - 1

        text, cursor_col = self.editor.visible(field_w)
        self.surface.put(field_x, y, text or "", fg=th.text, bg=th.surface)
        if not text:
            self.surface.put(field_x, y, "Message Valeroy…  (/ for commands)",
                             fg=th.muted, bg=th.surface)
        # Caret.
        caret_x = field_x + cursor_col
        under = text[cursor_col] if cursor_col < len(text) else " "
        self.surface.put(caret_x, y, under, fg=th.surface, bg=th.accent, attr=REVERSE)

    def _draw_footer(self, y: int, cols: int, th: Theme) -> None:
        if self._busy:
            hint = "  working…  Esc to dismiss overlays"
        elif self.chooser is not None and self.chooser.active:
            hint = "  ↑/↓ move · Enter select · Tab complete · Esc close"
        else:
            hint = "  Enter send · ↑/↓ history · PgUp/PgDn scroll · /help · /quit"
        self.surface.put(0, y, native.truncate(hint, cols), fg=th.muted, bg=th.base)

    def _draw_chooser(self, box_x: int, box_y: int, width: int,
                      min_top: int, th: Theme) -> None:
        chooser = self.chooser
        assert chooser is not None
        height = chooser.height()
        y = box_y - 1 - height
        if y < min_top:
            y = min_top
        chooser.draw(self.surface, box_x, y, width, th)

    # -- event pump -------------------------------------------------------- #

    def _poll_health(self) -> None:
        now = time.monotonic()
        if now - self._health_checked < HEALTH_INTERVAL:
            return
        self._health_checked = now
        previous = self._health is not None
        self._health = self.client.health()
        if (self._health is not None) != previous:
            self._dirty = True

    def _drain_events(self) -> None:
        drained = False
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            drained = True
            self._handle_event(event)
        if drained:
            self._dirty = True

    def _handle_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "delta" and self._stream_msg is not None:
            self._stream_msg.text += event["text"]
        elif kind == "done" and self._stream_msg is not None:
            usage = event.get("usage") or {}
            total = int(usage.get("total") or 0)
            if total:
                self._stream_msg.meta = f"{total} tokens"
            self.messages.append({"role": "assistant", "content": self._stream_msg.text})
        elif kind == "error":
            if self._stream_msg is not None:
                self._stream_msg.streaming = False
            self.transcript.add("error", str(event.get("error")))
        elif kind == "note":
            self.transcript.add("note", str(event.get("text")))
        elif kind == "command_result":
            self.transcript.add("assistant", str(event.get("text")),
                                 meta=event.get("meta", ""))
        elif kind == "models_ready":
            self._open_model_chooser(event["provider"], event["models"])
        elif kind == "_end":
            self._busy = False
            if self._stream_msg is not None:
                self._stream_msg.streaming = False
                self._stream_msg = None
            self.refresh_state()

    # -- input ------------------------------------------------------------- #

    def _handle_key(self, key) -> None:
        name = key.name
        self._dirty = True

        if name == "ctrl-c":
            self.stop()
            return
        if name == "ctrl-l":
            self.surface.invalidate()
            return

        # Overlay navigation takes priority when the dropdown is open.
        if self.chooser is not None and self.chooser.active:
            if name == "up":
                self.chooser.move(-1)
                return
            if name == "down":
                self.chooser.move(1)
                return
            if name == "escape":
                self._close_chooser()
                return
            if name == "tab":
                self._complete_from_chooser()
                return
            if name == "enter":
                if self.chooser_kind == "command":
                    self._submit()
                else:
                    self._pick_from_chooser()
                return
            # fall through: typing narrows the command dropdown

        if name == "enter":
            self._submit()
        elif name == "backspace":
            self.editor.backspace()
            self._sync_command_dropdown()
        elif name == "delete":
            self.editor.delete()
            self._sync_command_dropdown()
        elif name == "left":
            self.editor.left()
        elif name == "right":
            self.editor.right()
        elif name == "home":
            self.editor.home()
        elif name == "end":
            self.editor.end()
        elif name == "up":
            self.editor.history_prev()
            self._sync_command_dropdown()
        elif name == "down":
            self.editor.history_next()
            self._sync_command_dropdown()
        elif name == "page-up":
            self.transcript.scroll += 5
        elif name == "page-down":
            self.transcript.scroll = max(0, self.transcript.scroll - 5)
        elif name == "escape":
            self.editor.clear()
            self._close_chooser()
        elif name == "ctrl-w":
            self.editor.delete_word()
            self._sync_command_dropdown()
        elif name == "ctrl-u":
            self.editor.clear()
            self._close_chooser()
        elif key.is_char:
            self.editor.insert(key.char)
            self._sync_command_dropdown()

    def _sync_command_dropdown(self) -> None:
        """Open/refresh the command dropdown while the line starts with '/'."""
        text = self.editor.text
        if text.startswith("/") and " " not in text:
            matches = commands.complete(text)
            choices = [
                Choice(value=c.name, label=c.slash, detail=c.summary, badge=c.category)
                for c in matches
            ]
            if self.chooser is None or self.chooser_kind != "command":
                self.chooser = Chooser("commands", choices, max_visible=8,
                                       footer="Tab complete · Enter run")
                self.chooser_kind = "command"
            else:
                self.chooser.all_choices = choices
                self.chooser.set_choices(choices)
        elif self.chooser_kind == "command":
            self._close_chooser()

    def _close_chooser(self) -> None:
        self.chooser = None
        self.chooser_kind = ""

    def _complete_from_chooser(self) -> None:
        choice = self.chooser.current if self.chooser else None
        if choice is None:
            return
        if self.chooser_kind == "command":
            self.editor.text = f"/{choice.value} "
            self.editor.cursor = len(self.editor.text)
            command = commands.BY_NAME.get(choice.value)
            if command and not command.arg_hint and command.handler != "model":
                self._submit()
            else:
                self._close_chooser()

    def _pick_from_chooser(self) -> None:
        choice = self.chooser.current if self.chooser else None
        kind = self.chooser_kind
        self._close_chooser()
        if choice is None:
            return
        if kind == "model":
            self._apply_model(choice.value, choice.data)
        elif kind == "provider":
            self._apply_provider(choice.value)
        elif kind == "session":
            self._apply_session(choice.value)
        elif kind == "agent":
            self._apply_agent(choice.value)
        elif kind == "theme":
            self._apply_theme(choice.value)

    # -- submit ------------------------------------------------------------ #

    def _submit(self) -> None:
        line = self.editor.text.strip()
        if not line:
            return
        self.editor.remember(line)
        self.editor.clear()
        self._close_chooser()

        if line.startswith("/"):
            command, args = commands.parse(line)
            if command is None:
                self.transcript.add("error", f"unknown command: {line.split()[0]}")
                return
            self._dispatch(command.name, args)
            return

        # Natural-language agent creation, per the spec.
        intent = commands.detect_agent_request(line)
        if intent is not None:
            self.transcript.add("user", line)
            self._run_command_async("agents", f"{intent['name']} -- {intent['description']}")
            return

        self._send_chat(line)

    # -- chat -------------------------------------------------------------- #

    def _send_chat(self, text: str) -> None:
        if not self.state.get("active_model"):
            self.transcript.add("error",
                                 "No model selected. Use /model to pick one, "
                                 "or /provider to choose a provider first.")
            return
        self.messages.append({"role": "user", "content": text})
        self.transcript.add("user", text)
        self._stream_msg = self.transcript.add("assistant", "", streaming=True)
        self._busy = True
        payload = list(self.messages)
        threading.Thread(target=self._chat_worker, args=(payload,), daemon=True).start()

    def _chat_worker(self, messages: list[dict[str, str]]) -> None:
        try:
            for event in self.client.chat(messages, session=self.active_session,
                                           system=self.system):
                self._events.put(event)
        except GatewayError as exc:
            self._events.put({"type": "error", "error": str(exc)})
        finally:
            self._events.put({"type": "_end"})

    # -- command dispatch -------------------------------------------------- #

    MODEL_BACKED = {
        "humanize", "animate", "image", "summarize", "translate",
        "explain", "review", "refactor", "test", "commit", "search", "agents",
    }

    def _dispatch(self, name: str, args: str) -> None:
        if name in self.MODEL_BACKED:
            self.transcript.add("user", f"/{name} {args}".rstrip())
            self._run_command_async(name, args)
            return

        handler = getattr(self, f"_cmd_{name}", None)
        if handler is None:
            self.transcript.add("note", f"/{name} is not available in this build.")
            return
        try:
            handler(args)
        except (native.CoreError, GatewayError) as exc:
            self.transcript.add("error", str(exc))

    def _run_command_async(self, name: str, args: str) -> None:
        self._busy = True

        def worker() -> None:
            try:
                result = self.client.run_command(name, args)
                if name == "animate":
                    job = result.get("job") or {}
                    outputs = result.get("outputs") or []
                    text = "Animation job submitted (no Valeroy watermark)."
                    if outputs:
                        text += "\n" + "\n".join(outputs)
                    else:
                        text += f"\njob id: {job.get('id') or job.get('request_id') or '?'}"
                    self._events.put({"type": "command_result", "text": text})
                elif name == "agents":
                    agent = result.get("agent") or {}
                    self._events.put({
                        "type": "note",
                        "text": f"Created agent '{agent.get('name')}'. "
                                f"Switch to it with /agent {agent.get('name')}.",
                    })
                else:
                    self._events.put({"type": "command_result",
                                      "text": result.get("text", "(no output)")})
            except GatewayError as exc:
                self._events.put({"type": "error", "error": str(exc)})
            finally:
                self._events.put({"type": "_end"})

        threading.Thread(target=worker, daemon=True).start()

    # ---- model / provider ---- #

    def _cmd_model(self, args: str) -> None:
        provider = self.state.get("active_provider")
        if args.strip():
            self._apply_model(args.strip(), None)
            return
        if not provider:
            self.transcript.add("error", "Pick a provider first with /provider.")
            return
        self.transcript.add("note", f"Fetching models from {provider}…")
        self._busy = True

        def worker() -> None:
            try:
                models = self.client.models(provider)
                self._events.put({"type": "models_ready", "provider": provider,
                                  "models": models})
            except GatewayError as exc:
                self._events.put({"type": "error", "error": str(exc)})
            finally:
                self._events.put({"type": "_end"})

        threading.Thread(target=worker, daemon=True).start()

    def _open_model_chooser(self, provider: str, models: list[dict[str, Any]]) -> None:
        if not models:
            self.transcript.add("note", f"{provider} returned no models.")
            return
        choices = [
            Choice(value=m["id"], label=m.get("label", m["id"]),
                   detail=f"ctx {m['context']:,}" if m.get("context") else "",
                   data=provider)
            for m in models
        ]
        self.chooser = Chooser(f"models · {provider}", choices, max_visible=12,
                               footer="Enter select · Esc cancel")
        self.chooser_kind = "model"

    def _apply_model(self, model_id: str, provider: Any) -> None:
        args = ["model", "select", "--id", model_id]
        provider = provider or self.state.get("active_provider")
        if provider:
            args += ["--provider", str(provider)]
        native.core(*args)
        self.refresh_state()
        self.transcript.add("note", f"Model set to {model_id}.")

    def _cmd_provider(self, args: str) -> None:
        providers = self.state.get("providers", [])
        if args.strip():
            self._apply_provider(args.strip())
            return
        if not providers:
            self.transcript.add("note",
                                 "No providers enabled. Use /providers to add one.")
            return
        choices = [
            Choice(value=p["id"], label=p["id"],
                   detail=f"key {p.get('key_fingerprint', '')}",
                   badge="active" if p["id"] == self.state.get("active_provider") else "")
            for p in providers
        ]
        self.chooser = Chooser("providers", choices, max_visible=10,
                               footer="Enter select · Esc cancel")
        self.chooser_kind = "provider"

    def _apply_provider(self, provider_id: str) -> None:
        native.core("provider", "select", "--id", provider_id)
        self.refresh_state()
        self.transcript.add("note",
                             f"Provider set to {provider_id}. Use /model to pick a model.")

    def _cmd_providers(self, args: str) -> None:
        """Enable a new provider and key it (drops out of the full-screen view)."""
        catalog = native.provider_catalog()
        enabled = {p["id"] for p in self.state.get("providers", [])}
        available = [e for e in catalog if e["id"] not in enabled]
        if not available:
            self.transcript.add("note", "Every catalog provider is already enabled.")
            return

        def flow() -> None:
            items = [prompts.Item(e["id"], e.get("label", e["id"]),
                                  detail=e.get("kind", "")) for e in available]
            pick = prompts.select_one("Enable which provider?", items)
            if pick is None:
                return
            key = prompts.ask_secret(f"API key for {pick.label}")
            native.core("provider", "enable", "--id", pick.value, "--key", "-",
                        "--data-key", self.data_key, stdin=key + "\n")
            prompts.ok(f"{pick.label} enabled.")
            time.sleep(0.6)

        self._suspend(flow)
        self.refresh_state()
        self.transcript.add("note", "Provider list updated.")

    def _cmd_keys(self, args: str) -> None:
        providers = self.state.get("providers", [])
        if not providers:
            self.transcript.add("note", "No API keys stored yet.")
            return
        lines = [f"{p['id']}: key {p.get('key_fingerprint', '????????')}"
                 for p in providers]
        self.transcript.add("note", "Stored keys (fingerprints only):\n" + "\n".join(lines))

    def _cmd_models(self, args: str) -> None:
        """Register a custom model with its own API key, per the spec."""
        def flow() -> None:
            model_id = prompts.ask_line("Custom model id (e.g. my-model)")
            base_url = prompts.ask_line("Base URL (OpenAI-compatible)")
            key = prompts.ask_secret("API key for this model")
            native.core("model", "add", "--id", model_id, "--base-url", base_url,
                        "--key", "-", "--data-key", self.data_key, stdin=key + "\n")
            native.core("model", "select", "--id", model_id)
            prompts.ok(f"Custom model '{model_id}' added and selected.")
            time.sleep(0.6)

        self._suspend(flow)
        self.refresh_state()

    # ---- sessions / agents ---- #

    def _cmd_sessions(self, args: str) -> None:
        sessions = self.state.get("sessions", [])
        if not sessions:
            self.transcript.add("note", "No sessions yet. /new creates one.")
            return
        choices = [
            Choice(value=s["id"], label=s.get("title", s["id"]),
                   detail=f"{int(s.get('message_count', 0))} msgs",
                   badge="active" if s["id"] == self.active_session else "")
            for s in sorted(sessions, key=lambda s: s.get("updated_at", 0), reverse=True)
        ]
        self.chooser = Chooser("sessions", choices, max_visible=12,
                               footer="Enter open · Esc cancel")
        self.chooser_kind = "session"

    def _apply_session(self, session_id: str) -> None:
        native.core("session", "switch", "--id", session_id)
        self.refresh_state()
        self.active_session = session_id
        self.transcript.clear()
        self._load_active_transcript()
        self.transcript.add("note", "Switched session.")

    def _cmd_new(self, args: str) -> None:
        created = native.core("session", "new", "--title", args.strip() or "New session")
        self.refresh_state()
        self.active_session = created["id"]
        self.messages = []
        self.transcript.clear()
        self.transcript.add("note", "Started a new session.")

    def _cmd_delete(self, args: str) -> None:
        if not self.active_session:
            self.transcript.add("note", "No active session to delete.")
            return
        native.core("session", "delete", "--id", self.active_session)
        self.active_session = None
        self.messages = []
        self.transcript.clear()
        self.refresh_state()
        self._ensure_session()
        self.transcript.add("note", "Session deleted; started a fresh one.")

    def _cmd_resume(self, args: str) -> None:
        sessions = self.state.get("sessions", [])
        if not sessions:
            self.transcript.add("note", "No sessions to resume.")
            return
        newest = max(sessions, key=lambda s: s.get("updated_at", 0))
        self._apply_session(newest["id"])

    def _cmd_history(self, args: str) -> None:
        if not self.active_session:
            self.transcript.add("note", "No active session.")
            return
        limit = 0
        if args.strip().isdigit():
            limit = int(args.strip())
        rows = native.core("session", "transcript", "--id", self.active_session,
                           "--limit", str(limit))["messages"]
        if not rows:
            self.transcript.add("note", "This session has no messages yet.")
            return
        self.transcript.add("note", f"— {len(rows)} messages in this session —")

    def _cmd_agent(self, args: str) -> None:
        agents = self.state.get("agents", [])
        if args.strip():
            self._apply_agent(args.strip())
            return
        if not agents:
            self.transcript.add("note",
                                 "No agents yet. Create one with /agents or just ask.")
            return
        choices = [
            Choice(value=a["id"], label=a.get("name", a["id"]),
                   detail=native.truncate(a.get("description", ""), 48),
                   badge="active" if a["id"] == self.state.get("active_agent") else "")
            for a in agents
        ]
        self.chooser = Chooser("agents", choices, max_visible=10,
                               footer="Enter switch · Esc cancel")
        self.chooser_kind = "agent"

    def _apply_agent(self, needle: str) -> None:
        result = native.core("agent", "switch", "--id", needle)
        self.refresh_state()
        self.transcript.add("note", f"Active agent: {result.get('id')}.")

    # ---- app ---- #

    def _cmd_theme(self, args: str) -> None:
        if args.strip():
            self._apply_theme(args.strip())
            return
        choices = [
            Choice(value=t.name, label=t.label,
                   badge="current" if t.name == self.theme.name else "")
            for t in theme_mod.THEMES
        ]
        self.chooser = Chooser("themes", choices, max_visible=12,
                               footer="Enter apply · Esc cancel")
        self.chooser_kind = "theme"

    def _apply_theme(self, name: str) -> None:
        self.theme = theme_mod.get(name)
        self.prefs["theme"] = self.theme.name
        _save_prefs(self.prefs)
        self.surface.invalidate()
        self.transcript.add("note", f"Theme: {self.theme.label}.")

    def _cmd_status(self, args: str) -> None:
        health = self._health or {}
        model = self.state.get("active_model") or "none"
        provider = self.state.get("active_provider") or "none"
        usage = self.state.get("usage") or {}
        lines = [
            f"gateway:  {'up' if health else 'down'}"
            + (f" ({health.get('implementation')}, pid {health.get('pid')})" if health else ""),
            f"provider: {provider}",
            f"model:    {model}",
            f"tokens:   {int(usage.get('total_tokens', 0)):,} total "
            f"({int(health.get('tokens_this_run', 0)):,} this run)",
            f"native:   core={bool(native.core_available())}, "
            f"render={surface_mod.backend()}",
        ]
        self.transcript.add("note", "\n".join(lines))

    def _cmd_tokens(self, args: str) -> None:
        usage = self.state.get("usage") or {}
        self.transcript.add(
            "note",
            f"Tokens — total {int(usage.get('total_tokens', 0)):,}, "
            f"prompt {int(usage.get('prompt_tokens', 0)):,}, "
            f"completion {int(usage.get('completion_tokens', 0)):,}, "
            f"requests {int(usage.get('requests', 0)):,}.",
        )

    def _cmd_gateway(self, args: str) -> None:
        if args.strip() == "restart":
            # A fresh gateway starts locked, so the vault must be unlocked again.
            def flow() -> None:
                prompts.note("Restarting the gateway…")
                stop_gateway(self.host, self.port)
                time.sleep(0.6)
                try:
                    spawn_gateway(self.host, self.port)
                except GatewayError as exc:
                    prompts.error(str(exc))
                    time.sleep(1.0)
                    return
                password = prompts.ask_secret("Unlock the restarted gateway (password)")
                try:
                    self.client.login(password)
                    prompts.ok("Gateway restarted and unlocked.")
                except GatewayError as exc:
                    prompts.error(str(exc))
                time.sleep(0.6)

            self._suspend(flow)
            self._health = self.client.health()
            return
        health = self._health
        if health:
            self.transcript.add("note",
                                 f"Gateway up — {health.get('implementation')} "
                                 f"pid {health.get('pid')}, "
                                 f"uptime {health.get('uptime')}s.")
        else:
            self.transcript.add("error", "Gateway is not responding.")

    def _cmd_mcp(self, args: str) -> None:
        self.transcript.add(
            "note",
            "MCP integrations are configured per provider. This build wires the "
            "provider/model path; MCP tiles from the old UI are not yet ported.",
        )

    def _cmd_setup(self, args: str) -> None:
        self._suspend(setup_wizard.run)
        self.refresh_state()
        self.transcript.add("note", "Setup finished. State reloaded.")

    def _cmd_passwd(self, args: str) -> None:
        def flow() -> None:
            current = prompts.ask_secret("Current password")
            new = prompts.ask_secret("New password", confirm=True)
            native.core("account", "passwd", "--current", "-", "--password", "-",
                        "--confirm", "-", stdin=f"{current}\n{new}\n{new}\n")
            prompts.ok("Password changed.")
            time.sleep(0.6)

        self._suspend(flow)

    def _cmd_clear(self, args: str) -> None:
        self.transcript.clear()

    def _cmd_help(self, args: str) -> None:
        if args.strip():
            command = commands.BY_NAME.get(args.strip().lstrip("/"))
            if command is None:
                self.transcript.add("error", f"no such command: {args.strip()}")
                return
            self.transcript.add("note", f"{command.usage}\n  {command.summary}")
            return
        by_cat: dict[str, list[str]] = {}
        for command in commands.COMMANDS:
            by_cat.setdefault(command.category, []).append(f"/{command.name}")
        lines = [f"{cat}: {'  '.join(cmds)}" for cat, cmds in by_cat.items()]
        self.transcript.add("note", "Commands —\n" + "\n".join(lines))

    def _cmd_doctor(self, args: str) -> None:
        status = native.status()
        self.transcript.add(
            "note",
            "Native layers —\n"
            f"  core:    {status.get('core') or 'not built (python fallback)'}\n"
            f"  hashing: {status.get('hash')}\n"
            f"  catalog: {status.get('catalog')}\n"
            f"  render:  {status.get('render')}\n"
            f"  python:  {status.get('python')}",
        )

    def _cmd_pwd(self, args: str) -> None:
        self.transcript.add("note", os.getcwd())

    def _cmd_cd(self, args: str) -> None:
        target = args.strip() or os.path.expanduser("~")
        try:
            os.chdir(target)
            self.transcript.add("note", f"cwd: {os.getcwd()}")
        except OSError as exc:
            self.transcript.add("error", str(exc))

    def _cmd_export(self, args: str) -> None:
        if not self.active_session:
            self.transcript.add("note", "No active session to export.")
            return
        rows = native.core("session", "transcript", "--id", self.active_session)["messages"]
        path = args.strip() or f"valeroy-session-{self.active_session}.md"
        try:
            with open(path, "w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(f"### {row.get('role')}\n\n{row.get('content')}\n\n")
            self.transcript.add("note", f"Exported {len(rows)} messages to {path}.")
        except OSError as exc:
            self.transcript.add("error", str(exc))

    def _cmd_quit(self, args: str) -> None:
        self.stop()

    # -- helpers ----------------------------------------------------------- #

    def _suspend(self, func) -> None:
        """Leave the full-screen UI, run a plain-terminal flow, then return."""
        self.term.leave()
        try:
            func()
        except KeyboardInterrupt:
            pass
        except (native.CoreError, GatewayError) as exc:
            prompts.error(str(exc))
            time.sleep(0.8)
        finally:
            self.term.enter()
            self.surface.invalidate()
            self._dirty = True

    def stop(self) -> None:
        self._running = False
