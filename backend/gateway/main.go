// valeroy-gateway - the Go implementation of the Valeroy gateway.
//
// A local HTTP daemon on 127.0.0.1 that owns every outbound provider call and
// the unlocked credential vault. It runs as its own background process; the TUI
// is a client. Kill it and the frontend loses its connection, which is the
// behaviour the spec describes.
//
// It serves the same API as backend/python/valeroy_backend/gateway.py and is
// preferred over the Python build when present (see frontend client).
package main

import (
	"crypto/subtle"
	"encoding/json"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

const version = "1.0.0"

type vault struct {
	mu       sync.Mutex
	dataKey  string
	username string
	token    string
	unlocked int64
}

func (v *vault) unlock(password string) (map[string]any, error) {
	payload, err := core(password+"\n", "account", "unlock", "--password", "-")
	if err != nil {
		return nil, err
	}
	v.mu.Lock()
	defer v.mu.Unlock()
	v.dataKey, _ = payload["data_key"].(string)
	v.username, _ = payload["username"].(string)
	v.token, _ = payload["gateway_token"].(string)
	v.unlocked = time.Now().Unix()
	return map[string]any{"username": v.username, "token": v.token}, nil
}

func (v *vault) lock() {
	v.mu.Lock()
	defer v.mu.Unlock()
	v.dataKey, v.username, v.token, v.unlocked = "", "", "", 0
}

func (v *vault) key() (string, bool) {
	v.mu.Lock()
	defer v.mu.Unlock()
	return v.dataKey, v.dataKey != ""
}

func (v *vault) checkToken(token string) bool {
	v.mu.Lock()
	defer v.mu.Unlock()
	if v.token == "" || token == "" {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(token), []byte(v.token)) == 1
}

func (v *vault) info() map[string]any {
	v.mu.Lock()
	defer v.mu.Unlock()
	return map[string]any{"unlocked": v.dataKey != "", "username": v.username, "unlocked_at": v.unlocked}
}

type server struct {
	host, port  string
	vault       *vault
	started     time.Time
	mu          sync.Mutex
	modelCache  map[string][]map[string]any
	requests    int64
	tokensRun   int64
	httpServer  *http.Server
}

// ---- runtime descriptor ---------------------------------------------------

func (s *server) runtimeFile() (string, error) {
	paths, err := core("", "state", "path")
	if err != nil {
		return "", err
	}
	runtime, _ := paths["runtime"].(string)
	return filepath.Join(runtime, "gateway.json"), nil
}

func (s *server) writeRuntime(token string) {
	path, err := s.runtimeFile()
	if err != nil {
		return
	}
	_ = os.MkdirAll(filepath.Dir(path), 0o700)
	record := map[string]any{"pid": os.Getpid(), "host": s.host, "port": s.port,
		"version": version, "implementation": "go", "started_at": s.started.Unix(), "token": token}
	data, _ := json.Marshal(record)
	_ = os.WriteFile(path, data, 0o600)
}

func (s *server) clearRuntime() {
	if path, err := s.runtimeFile(); err == nil {
		_ = os.Remove(path)
	}
}

// ---- helpers --------------------------------------------------------------

func sendJSON(w http.ResponseWriter, status int, payload any) {
	data, _ := json.Marshal(payload)
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_, _ = w.Write(data)
}

func fail(w http.ResponseWriter, status int, msg string) {
	sendJSON(w, status, map[string]any{"ok": false, "error": msg})
}

func isLocal(r *http.Request) bool {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	return host == "127.0.0.1" || host == "::1" || host == "localhost"
}

func (s *server) requireToken(w http.ResponseWriter, r *http.Request) bool {
	header := r.Header.Get("Authorization")
	token := strings.TrimSpace(strings.TrimPrefix(header, "Bearer "))
	if s.vault.checkToken(token) {
		return true
	}
	fail(w, 401, "a valid gateway token is required; log in first")
	return false
}

func readBody(r *http.Request) (map[string]any, error) {
	var body map[string]any
	if r.Body == nil {
		return map[string]any{}, nil
	}
	dec := json.NewDecoder(r.Body)
	if err := dec.Decode(&body); err != nil {
		if err.Error() == "EOF" {
			return map[string]any{}, nil
		}
		return nil, fmt.Errorf("request body is not valid JSON")
	}
	return body, nil
}

func stateShow() (map[string]any, error) {
	payload, err := core("", "state", "show")
	if err != nil {
		return nil, err
	}
	st, _ := payload["state"].(map[string]any)
	return st, nil
}

// resolveTarget picks the provider config and model for a request.
func (s *server) resolveTarget(providerID, modelID string) (providerConfig, string, error) {
	dataKey, ok := s.vault.key()
	if !ok {
		return providerConfig{}, "", fmt.Errorf("the vault is locked; POST /login first")
	}
	st, err := stateShow()
	if err != nil {
		return providerConfig{}, "", err
	}
	model := modelID
	if model == "" {
		model, _ = st["active_model"].(string)
	}
	provider := providerID
	if provider == "" {
		provider, _ = st["active_provider"].(string)
	}
	if model == "" {
		return providerConfig{}, "", fmt.Errorf("no model selected - use /model to pick one")
	}

	if provider == "" || provider == "custom" {
		if customs, ok := st["custom_models"].([]any); ok {
			for _, item := range customs {
				entry, _ := item.(map[string]any)
				if entry["id"] == model {
					keyPayload, err := core("", "model", "key", "--id", model, "--data-key", dataKey)
					if err != nil {
						return providerConfig{}, "", err
					}
					base, _ := entry["base_url"].(string)
					apiKey, _ := keyPayload["key"].(string)
					return providerConfig{id: "custom", apiKey: apiKey,
						baseURL: strings.TrimRight(base, "/"), authStyle: "bearer",
						authField: "Authorization", modelsPath: "/models", kind: "multi"}, model, nil
				}
			}
		}
	}
	if provider == "" {
		return providerConfig{}, "", fmt.Errorf("no provider selected - use /provider to pick one")
	}
	keyPayload, err := core("", "provider", "key", "--id", provider, "--data-key", dataKey)
	if err != nil {
		return providerConfig{}, "", err
	}
	var baseURL string
	if providers, ok := st["providers"].([]any); ok {
		for _, item := range providers {
			entry, _ := item.(map[string]any)
			if entry["id"] == provider {
				baseURL, _ = entry["base_url"].(string)
			}
		}
	}
	apiKey, _ := keyPayload["key"].(string)
	config, err := configFromCatalog(provider, apiKey, baseURL)
	return config, model, err
}

// ---- handlers -------------------------------------------------------------

func (s *server) handle(w http.ResponseWriter, r *http.Request) {
	if !isLocal(r) {
		fail(w, 403, "the gateway only serves local clients")
		return
	}
	s.mu.Lock()
	s.requests++
	s.mu.Unlock()

	switch {
	case r.Method == "GET" && r.URL.Path == "/health":
		s.handleHealth(w)
	case r.Method == "GET" && r.URL.Path == "/state":
		st, err := stateShow()
		if err != nil {
			fail(w, 500, err.Error())
			return
		}
		sendJSON(w, 200, map[string]any{"ok": true, "state": st})
	case r.Method == "GET" && r.URL.Path == "/commands":
		sendJSON(w, 200, map[string]any{"ok": true, "commands": commandCatalog})
	case r.Method == "GET" && r.URL.Path == "/catalog":
		sendJSON(w, 200, map[string]any{"ok": true, "providers": catalog})
	case r.Method == "GET" && r.URL.Path == "/models":
		s.handleModels(w, r)
	case r.Method == "POST" && r.URL.Path == "/login":
		s.handleLogin(w, r)
	case r.Method == "POST" && r.URL.Path == "/logout":
		s.vault.lock()
		sendJSON(w, 200, map[string]any{"ok": true})
	case r.Method == "POST" && r.URL.Path == "/chat":
		if s.requireToken(w, r) {
			s.handleChat(w, r)
		}
	case r.Method == "POST" && r.URL.Path == "/command":
		if s.requireToken(w, r) {
			s.handleCommand(w, r)
		}
	case r.Method == "POST" && r.URL.Path == "/shutdown":
		if s.requireToken(w, r) {
			sendJSON(w, 200, map[string]any{"ok": true, "stopping": true})
			go func() { time.Sleep(200 * time.Millisecond); _ = s.httpServer.Close() }()
		}
	default:
		fail(w, 404, "no such endpoint: "+r.URL.Path)
	}
}

func (s *server) handleHealth(w http.ResponseWriter) {
	s.mu.Lock()
	requests, tokens := s.requests, s.tokensRun
	s.mu.Unlock()
	sendJSON(w, 200, map[string]any{
		"ok": true, "version": version, "implementation": "go", "pid": os.Getpid(),
		"uptime": time.Since(s.started).Seconds(), "vault": s.vault.info(),
		"requests_served": requests, "tokens_this_run": tokens,
		"native": map[string]any{"core": coreAvailable()},
	})
}

func (s *server) handleLogin(w http.ResponseWriter, r *http.Request) {
	body, err := readBody(r)
	if err != nil {
		fail(w, 400, err.Error())
		return
	}
	password, _ := body["password"].(string)
	if password == "" {
		fail(w, 400, "a password is required")
		return
	}
	result, err := s.vault.unlock(password)
	if err != nil {
		fail(w, 401, err.Error())
		return
	}
	s.writeRuntime(result["token"].(string))
	result["ok"] = true
	sendJSON(w, 200, result)
}

func (s *server) handleModels(w http.ResponseWriter, r *http.Request) {
	provider := r.URL.Query().Get("provider")
	refresh := r.URL.Query().Get("refresh")
	if provider == "" {
		fail(w, 400, "?provider=<id> is required")
		return
	}
	if refresh == "" || refresh == "0" || refresh == "false" {
		s.mu.Lock()
		cached, ok := s.modelCache[provider]
		s.mu.Unlock()
		if ok {
			sendJSON(w, 200, map[string]any{"ok": true, "provider": provider, "models": cached, "cached": true})
			return
		}
	}
	config, _, err := s.resolveTarget(provider, "placeholder")
	if err != nil {
		// resolveTarget needs a model; fetch the key directly instead.
		dataKey, ok := s.vault.key()
		if !ok {
			fail(w, 401, "the vault is locked; POST /login first")
			return
		}
		keyPayload, kerr := core("", "provider", "key", "--id", provider, "--data-key", dataKey)
		if kerr != nil {
			fail(w, 500, kerr.Error())
			return
		}
		config, err = configFromCatalog(provider, keyPayload["key"].(string), "")
		if err != nil {
			fail(w, 500, err.Error())
			return
		}
	}
	models, err := listModels(config)
	if err != nil {
		fail(w, 502, err.Error())
		return
	}
	s.mu.Lock()
	s.modelCache[provider] = models
	s.mu.Unlock()
	if data, mErr := json.Marshal(models); mErr == nil {
		_, _ = core(string(data), "model", "cache", "--provider", provider)
	}
	sendJSON(w, 200, map[string]any{"ok": true, "provider": provider, "models": models, "cached": false})
}

func (s *server) handleChat(w http.ResponseWriter, r *http.Request) {
	body, err := readBody(r)
	if err != nil {
		fail(w, 400, err.Error())
		return
	}
	rawMessages, ok := body["messages"].([]any)
	if !ok || len(rawMessages) == 0 {
		fail(w, 400, "messages must be a non-empty array")
		return
	}
	messages := make([]map[string]any, 0, len(rawMessages))
	for _, m := range rawMessages {
		mm, _ := m.(map[string]any)
		if mm == nil || mm["role"] == nil {
			fail(w, 400, "each message needs a role and content")
			return
		}
		messages = append(messages, mm)
	}
	providerID, _ := body["provider"].(string)
	modelID, _ := body["model"].(string)
	config, model, err := s.resolveTarget(providerID, modelID)
	if err != nil {
		fail(w, 400, err.Error())
		return
	}
	system, _ := body["system"].(string)
	session, _ := body["session"].(string)
	maxTokens := 4096
	if v, ok := body["max_tokens"].(float64); ok {
		maxTokens = int(v)
	}
	temperature := 0.7
	if v, ok := body["temperature"].(float64); ok {
		temperature = v
	}

	w.Header().Set("Content-Type", "application/x-ndjson")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(200)
	flusher, _ := w.(http.Flusher)
	emit := func(event map[string]any) {
		data, _ := json.Marshal(event)
		_, _ = w.Write(append(data, '\n'))
		if flusher != nil {
			flusher.Flush()
		}
	}

	var collected strings.Builder
	emit(map[string]any{"type": "start", "model": model, "provider": config.id})
	err = streamChat(config, model, messages, system, maxTokens, temperature, func(event map[string]any) {
		if event["type"] == "delta" {
			collected.WriteString(event["text"].(string))
		} else if event["type"] == "done" {
			if usage, ok := event["usage"].(map[string]int); ok {
				s.mu.Lock()
				s.tokensRun += int64(usage["total"])
				s.mu.Unlock()
			}
			s.persistTurn(session, messages, collected.String(), event["usage"])
		}
		emit(event)
	})
	if err != nil {
		emit(map[string]any{"type": "error", "error": err.Error()})
	}
}

func (s *server) persistTurn(session string, messages []map[string]any, reply string, usage any) {
	if session == "" {
		return
	}
	u, _ := usage.(map[string]int)
	var lastUser string
	for i := len(messages) - 1; i >= 0; i-- {
		if messages[i]["role"] == "user" {
			lastUser, _ = messages[i]["content"].(string)
			break
		}
	}
	if lastUser != "" {
		_, _ = core(lastUser, "session", "append", "--id", session, "--role", "user",
			"--tokens", strconv.Itoa(u["prompt"]))
	}
	_, _ = core(reply, "session", "append", "--id", session, "--role", "assistant",
		"--tokens", strconv.Itoa(u["completion"]))
}

func (s *server) handleCommand(w http.ResponseWriter, r *http.Request) {
	body, err := readBody(r)
	if err != nil {
		fail(w, 400, err.Error())
		return
	}
	name := strings.TrimPrefix(strings.TrimSpace(fmt.Sprintf("%v", body["command"])), "/")
	cmd, ok := commandByName(name)
	if !ok {
		fail(w, 400, "unknown command: /"+name)
		return
	}
	if cmd.Handler != "model" {
		fail(w, 400, "/"+name+" is handled by the frontend, not the gateway")
		return
	}
	args, _ := body["args"].(string)
	providerID, _ := body["provider"].(string)
	modelID, _ := body["model"].(string)
	config, model, err := s.resolveTarget(providerID, modelID)
	if err != nil {
		fail(w, 400, err.Error())
		return
	}

	switch name {
	case "humanize":
		if strings.TrimSpace(args) == "" {
			fail(w, 400, "/humanize needs some text to rewrite")
			return
		}
		text, err := complete(config, model, args, humanizeSystem, max1(len(args)/2))
		if err != nil {
			fail(w, 502, err.Error())
			return
		}
		sendJSON(w, 200, map[string]any{"ok": true, "command": name, "text": text})
	case "agents":
		agentName, description := splitAgentsArgs(args)
		if description == "" {
			fail(w, 400, "describe what the agent does, e.g. /agents Scribe -- takes meeting notes")
			return
		}
		if agentName == "" {
			fields := strings.Fields(description)
			if len(fields) > 2 {
				fields = fields[:2]
			}
			agentName = strings.Title(strings.Join(fields, " "))
		}
		prompt := fmt.Sprintf("Agent name: %s\nDescription of what it does: %s\n\nWrite this agent's operating instructions.",
			agentName, description)
		instructions, err := complete(config, model, prompt, agentSystem, 900)
		if err != nil {
			fail(w, 502, err.Error())
			return
		}
		created, err := core(instructions, "agent", "create", "--name", agentName,
			"--description", description, "--stdin")
		if err != nil {
			fail(w, 500, err.Error())
			return
		}
		sendJSON(w, 200, map[string]any{"ok": true, "command": name,
			"agent": map[string]any{"name": agentName, "description": description,
				"instructions": instructions, "id": created["id"]}})
	case "animate":
		var images []string
		if arr, ok := body["images"].([]any); ok {
			for _, i := range arr {
				images = append(images, fmt.Sprintf("%v", i))
			}
		}
		if config.kind != "video" && config.kind != "multi" && !videoCapable[config.id] {
			fail(w, 502, config.id+" does not expose video models")
			return
		}
		job, err := submitVideo(config, model, args, images, 5, "16:9")
		if err != nil {
			fail(w, 502, err.Error())
			return
		}
		sendJSON(w, 200, map[string]any{"ok": true, "command": name, "job": job,
			"watermark": false, "outputs": videoOutputURLs(job)})
	default:
		text, err := complete(config, model, args, taskSystems[name], 2048)
		if err != nil {
			fail(w, 502, err.Error())
			return
		}
		sendJSON(w, 200, map[string]any{"ok": true, "command": name, "text": text})
	}
}

// ---- entry point ----------------------------------------------------------

func main() {
	host := flag.String("host", "127.0.0.1", "bind host")
	port := flag.Int("port", 17637, "bind port")
	flag.Parse()

	if !coreAvailable() {
		fmt.Fprintln(os.Stderr, "[gateway] valeroy-core is not built. Run scripts/build.ps1 first.")
		os.Exit(2)
	}

	s := &server{host: *host, port: strconv.Itoa(*port), vault: &vault{},
		started: time.Now(), modelCache: map[string][]map[string]any{}}

	addr := net.JoinHostPort(*host, strconv.Itoa(*port))
	mux := http.NewServeMux()
	mux.HandleFunc("/", s.handle)
	s.httpServer = &http.Server{Addr: addr, Handler: mux}

	s.writeRuntime("")
	fmt.Fprintf(os.Stderr, "[gateway] Valeroy gateway %s listening on http://%s (pid %d)\n",
		version, addr, os.Getpid())

	err := s.httpServer.ListenAndServe()
	s.vault.lock()
	s.clearRuntime()
	if err != nil && err != http.ErrServerClosed {
		fmt.Fprintf(os.Stderr, "[gateway] %v\n", err)
		os.Exit(1)
	}
	fmt.Fprintln(os.Stderr, "[gateway] stopped")
}
