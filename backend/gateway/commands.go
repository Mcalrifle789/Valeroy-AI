// Command catalog, mirroring backend/python/valeroy_backend/commands.py. It is
// the source of truth for the gateway's /commands endpoint; the frontend also
// carries its own copy for the dropdown.
package main

import "strings"

type command struct {
	Name      string `json:"name"`
	Summary   string `json:"summary"`
	Usage     string `json:"usage"`
	Category  string `json:"category"`
	Handler   string `json:"handler"`
	NeedsModel bool  `json:"needs_model"`
	ArgHint   string `json:"arg_hint"`
}

var commandCatalog = []command{
	{"model", "Switch the active model", "/model [model-id]", "models", "ui", false, "model"},
	{"models", "Add a custom model with its own API key", "/models [model-id] [base-url]", "models", "ui", false, "model"},
	{"provider", "Switch or inspect the active provider", "/provider [id]", "models", "ui", false, "provider"},
	{"providers", "Enable, disable and key providers", "/providers", "models", "ui", false, ""},
	{"keys", "Review stored API keys (fingerprints only)", "/keys", "models", "ui", false, ""},
	{"sessions", "Switch between sessions across all agents", "/sessions", "sessions", "ui", false, ""},
	{"new", "Create a new session", "/new [title]", "sessions", "core", false, "text"},
	{"agent", "Switch the active agent", "/agent [name]", "agents", "ui", false, "agent"},
	{"agents", "Create a custom Valeroy agent from a description", "/agents [name] -- [description]", "agents", "model", true, "text"},
	{"rename", "Rename the current session", "/rename <title>", "sessions", "core", false, "text"},
	{"delete", "Delete the current session", "/delete", "sessions", "core", false, ""},
	{"resume", "Reopen the most recent session", "/resume", "sessions", "core", false, ""},
	{"history", "Show the transcript of the current session", "/history [n]", "sessions", "ui", false, ""},
	{"export", "Write the current session to a file", "/export [path]", "sessions", "core", false, "file"},
	{"humanize", "Rewrite text so it reads as human-written", "/humanize <text>", "generate", "model", true, "text"},
	{"animate", "Animate one or more images into video", "/animate <prompt> [--image path ...]", "generate", "model", true, "file"},
	{"image", "Generate an image", "/image <prompt>", "generate", "model", true, "text"},
	{"summarize", "Summarize text, a file, or the session", "/summarize [path]", "generate", "model", true, "file"},
	{"translate", "Translate text into another language", "/translate <lang> <text>", "generate", "model", true, "text"},
	{"explain", "Explain code or a concept", "/explain <topic>", "generate", "model", true, "text"},
	{"review", "Review code for bugs and clarity", "/review [path]", "generate", "model", true, "file"},
	{"refactor", "Suggest a refactor for a file", "/refactor <path>", "generate", "model", true, "file"},
	{"test", "Write tests for a file", "/test <path>", "generate", "model", true, "file"},
	{"commit", "Draft a commit message from staged changes", "/commit", "generate", "model", true, ""},
	{"files", "Browse files attached to this session", "/files", "workspace", "ui", false, ""},
	{"attach", "Attach a file to the conversation", "/attach <path>", "workspace", "core", false, "file"},
	{"detach", "Remove an attached file", "/detach <path>", "workspace", "core", false, "file"},
	{"cd", "Change the working directory", "/cd <path>", "workspace", "core", false, "file"},
	{"pwd", "Show the working directory", "/pwd", "workspace", "ui", false, ""},
	{"search", "Search the web", "/search <query>", "workspace", "model", true, "text"},
	{"theme", "Cycle or pick a theme", "/theme [name]", "app", "ui", false, "theme"},
	{"status", "Show gateway, model and token status", "/status", "app", "ui", false, ""},
	{"tokens", "Show token usage for this session and overall", "/tokens", "app", "ui", false, ""},
	{"gateway", "Inspect or restart the gateway", "/gateway [restart]", "app", "ui", false, ""},
	{"mcp", "Manage MCP integrations", "/mcp", "app", "ui", false, "mcp"},
	{"setup", "Re-run the setup wizard", "/setup", "app", "ui", false, ""},
	{"passwd", "Change your account password", "/passwd", "app", "ui", false, ""},
	{"approve", "Approve the pending permission request", "/approve", "app", "ui", false, ""},
	{"deny", "Deny the pending permission request", "/deny", "app", "ui", false, ""},
	{"clear", "Clear the transcript view", "/clear", "app", "ui", false, ""},
	{"help", "List every command", "/help [command]", "app", "ui", false, "command"},
	{"doctor", "Report which native layers are active", "/doctor", "app", "ui", false, ""},
	{"quit", "Leave Valeroy", "/quit", "app", "ui", false, ""},
}

func commandByName(name string) (command, bool) {
	for _, c := range commandCatalog {
		if c.Name == name {
			return c, true
		}
	}
	return command{}, false
}

const humanizeSystem = `You rewrite text so it reads as though a person wrote it.

Rules:
- Keep the original meaning, facts and approximate length.
- Vary sentence length. Mix short sentences with longer ones.
- Prefer plain words over inflated ones. Cut filler and hedging.
- Remove the telltale signs of generated prose.
- Keep contractions where they fit naturally.
- Do not add commentary, headings, or explanation. Return only the rewrite.`

const agentSystem = `You turn a short description of an assistant into its operating instructions.

Write the instructions in second person, addressed to the agent ("You are ...").
Cover: what the agent is for, how it should behave, its tone, what it should
prioritize, and what it should refuse or escalate. Be specific and concrete.
Return only the instructions, 120-300 words, no headings or preamble.`

var taskSystems = map[string]string{
	"summarize": "Summarize the input tightly. Lead with the point.",
	"translate": "Translate the input. Return only the translation.",
	"explain":   "Explain clearly and concretely. No filler.",
	"review":    "Review this code. List concrete problems and fixes, most severe first.",
	"refactor":  "Propose a refactor. Show the changed code.",
	"test":      "Write thorough tests for this code, including edge cases.",
	"commit":    "Write one clear commit message. Imperative mood, no fluff.",
	"image":     "Describe the requested image in vivid, concrete visual detail.",
	"search":    "Answer the question directly, flagging anything you are unsure of.",
}

// splitAgentsArgs splits "Name -- description" / "Name: description" / "description".
func splitAgentsArgs(raw string) (string, string) {
	text := strings.TrimSpace(raw)
	if text == "" {
		return "", ""
	}
	for _, sep := range []string{"--", ":", " - "} {
		if i := strings.Index(text, sep); i >= 0 {
			name := strings.TrimSpace(text[:i])
			desc := strings.TrimSpace(text[i+len(sep):])
			if name != "" && desc != "" {
				return name, desc
			}
		}
	}
	if len(strings.Fields(text)) <= 3 {
		return text, ""
	}
	return "", text
}
