// Provider adapters, mirroring backend/python/valeroy_backend/providers.py.
// One OpenAI-compatible surface plus the Anthropic special case covers every
// provider in the catalog. Standard library only.
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"time"
)

const userAgent = "Valeroy-AI/1.0 (+https://github.com/Mcalrifle789/Valeroy-AI)"

type providerEntry struct {
	ID        string `json:"id"`
	Label     string `json:"label"`
	BaseURL   string `json:"base_url"`
	ModelsPath string `json:"models_path"`
	AuthStyle string `json:"auth_style"`
	AuthField string `json:"auth_field"`
	Kind      string `json:"kind"`
	Docs      string `json:"docs"`
}

// catalog mirrors FALLBACK_CATALOG in native.py. Kept in sync by the parity test.
var catalog = []providerEntry{
	{"anthropic", "Anthropic", "https://api.anthropic.com/v1", "/models", "x-api-key", "x-api-key", "chat", "https://docs.anthropic.com"},
	{"cerebras", "Cerebras", "https://api.cerebras.ai/v1", "/models", "bearer", "Authorization", "chat", "https://inference-docs.cerebras.ai"},
	{"cohere", "Cohere", "https://api.cohere.com/v1", "/models", "bearer", "Authorization", "chat", "https://docs.cohere.com"},
	{"costruter", "Costruter", "https://api.costruter.com/v1", "/models", "bearer", "Authorization", "multi", "https://costruter.com/docs"},
	{"deepinfra", "DeepInfra", "https://api.deepinfra.com/v1/openai", "/models", "bearer", "Authorization", "multi", "https://deepinfra.com/docs"},
	{"deepseek", "DeepSeek", "https://api.deepseek.com/v1", "/models", "bearer", "Authorization", "chat", "https://api-docs.deepseek.com"},
	{"fal", "fal.ai", "https://fal.run", "/models", "query", "fal_key", "video", "https://fal.ai/docs"},
	{"fireworks", "Fireworks AI", "https://api.fireworks.ai/inference/v1", "/models", "bearer", "Authorization", "multi", "https://docs.fireworks.ai"},
	{"google", "Google AI Studio", "https://generativelanguage.googleapis.com/v1beta", "/models", "query", "key", "multi", "https://ai.google.dev/docs"},
	{"groq", "Groq", "https://api.groq.com/openai/v1", "/models", "bearer", "Authorization", "chat", "https://console.groq.com/docs"},
	{"hyperbolic", "Hyperbolic", "https://api.hyperbolic.xyz/v1", "/models", "bearer", "Authorization", "multi", "https://docs.hyperbolic.xyz"},
	{"lmstudio", "LM Studio (local)", "http://127.0.0.1:1234/v1", "/models", "bearer", "Authorization", "chat", "https://lmstudio.ai/docs"},
	{"mistral", "Mistral AI", "https://api.mistral.ai/v1", "/models", "bearer", "Authorization", "chat", "https://docs.mistral.ai"},
	{"novita", "Novita AI", "https://api.novita.ai/v3/openai", "/models", "bearer", "Authorization", "multi", "https://novita.ai/docs"},
	{"ollama", "Ollama (local)", "http://127.0.0.1:11434/v1", "/models", "bearer", "Authorization", "chat", "https://ollama.com/docs"},
	{"openai", "OpenAI", "https://api.openai.com/v1", "/models", "bearer", "Authorization", "multi", "https://platform.openai.com/docs"},
	{"opencode", "Opencode", "https://opencode.ai/api/v1", "/models", "bearer", "Authorization", "chat", "https://opencode.ai/docs"},
	{"openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "/models", "bearer", "Authorization", "multi", "https://openrouter.ai/docs"},
	{"perplexity", "Perplexity", "https://api.perplexity.ai", "/models", "bearer", "Authorization", "chat", "https://docs.perplexity.ai"},
	{"replicate", "Replicate", "https://api.replicate.com/v1", "/models", "bearer", "Authorization", "video", "https://replicate.com/docs"},
	{"runway", "Runway", "https://api.dev.runwayml.com/v1", "/models", "bearer", "Authorization", "video", "https://docs.dev.runwayml.com"},
	{"sambanova", "SambaNova", "https://api.sambanova.ai/v1", "/models", "bearer", "Authorization", "chat", "https://docs.sambanova.ai"},
	{"together", "Together AI", "https://api.together.xyz/v1", "/models", "bearer", "Authorization", "multi", "https://docs.together.ai"},
	{"xai", "xAI", "https://api.x.ai/v1", "/models", "bearer", "Authorization", "multi", "https://docs.x.ai"},
}

func providerByID(id string) (providerEntry, bool) {
	for _, e := range catalog {
		if e.ID == id {
			return e, true
		}
	}
	return providerEntry{}, false
}

type providerConfig struct {
	id        string
	apiKey    string
	baseURL   string
	authStyle string
	authField string
	modelsPath string
	kind      string
}

func configFromCatalog(id, apiKey, baseURL string) (providerConfig, error) {
	entry, ok := providerByID(id)
	if !ok {
		if baseURL == "" {
			return providerConfig{}, fmt.Errorf("'%s' is not in the catalog; a base url is required", id)
		}
		return providerConfig{id: id, apiKey: apiKey, baseURL: strings.TrimRight(baseURL, "/"),
			authStyle: "bearer", authField: "Authorization", modelsPath: "/models", kind: "chat"}, nil
	}
	url := entry.BaseURL
	if baseURL != "" {
		url = baseURL
	}
	return providerConfig{id: id, apiKey: apiKey, baseURL: strings.TrimRight(url, "/"),
		authStyle: entry.AuthStyle, authField: entry.AuthField, modelsPath: entry.ModelsPath, kind: entry.Kind}, nil
}

func (c providerConfig) applyAuth(u string, headers map[string]string) string {
	switch c.authStyle {
	case "bearer":
		headers[c.authField] = "Bearer " + c.apiKey
	case "x-api-key":
		headers[c.authField] = c.apiKey
		if _, ok := headers["anthropic-version"]; !ok {
			headers["anthropic-version"] = "2023-06-01"
		}
	case "query":
		sep := "?"
		if strings.Contains(u, "?") {
			sep = "&"
		}
		u = u + sep + url.QueryEscape(c.authField) + "=" + url.QueryEscape(c.apiKey)
	default:
		headers[c.authField] = c.apiKey
	}
	return u
}

var httpClient = &http.Client{Timeout: 10 * time.Minute}

func (c providerConfig) do(path, method string, body []byte, stream bool) (*http.Response, error) {
	u := path
	if !strings.HasPrefix(path, "http") {
		u = c.baseURL + path
	}
	headers := map[string]string{"User-Agent": userAgent}
	if stream {
		headers["Accept"] = "text/event-stream"
	} else {
		headers["Accept"] = "application/json"
	}
	if body != nil {
		headers["Content-Type"] = "application/json"
	}
	u = c.applyAuth(u, headers)

	var reader io.Reader
	if body != nil {
		reader = strings.NewReader(string(body))
	}
	req, err := http.NewRequest(method, u, reader)
	if err != nil {
		return nil, err
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("cannot reach %s: %v", c.id, err)
	}
	if resp.StatusCode >= 400 {
		data, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		resp.Body.Close()
		return nil, fmt.Errorf("%s HTTP %d: %s", c.id, resp.StatusCode, strings.TrimSpace(string(data)))
	}
	return resp, nil
}

// listModels fetches and normalizes a provider's model list.
func listModels(c providerConfig) ([]map[string]any, error) {
	resp, err := c.do(c.modelsPath, "GET", nil, false)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	return normalizeModels(c.id, raw), nil
}

var listKeys = []string{"data", "models", "results", "items", "model_list"}
var idKeys = []string{"id", "name", "model", "slug", "model_name"}
var labelKeys = []string{"display_name", "displayName", "label", "title", "name", "id"}
var ctxKeys = []string{"context_length", "context_window", "max_context_length", "max_input_tokens", "inputTokenLimit"}

func stripNamespace(id string) string {
	if i := strings.LastIndex(id, "/"); i >= 0 {
		head := id[:i]
		if head == "models" || head == "accounts" {
			return id[i+1:]
		}
	}
	return id
}

func normalizeModels(providerID string, raw []byte) []map[string]any {
	var parsed any
	if err := json.Unmarshal(raw, &parsed); err != nil {
		return nil
	}
	var items []any
	switch v := parsed.(type) {
	case []any:
		items = v
	case map[string]any:
		for _, key := range listKeys {
			if lst, ok := v[key].([]any); ok {
				items = lst
				break
			}
		}
	}
	seen := map[string]map[string]any{}
	for _, item := range items {
		var id, label string
		var ctx int
		switch it := item.(type) {
		case string:
			id, label = it, it
		case map[string]any:
			for _, k := range idKeys {
				if s, ok := it[k].(string); ok && s != "" {
					id = s
					break
				}
			}
			for _, k := range labelKeys {
				if s, ok := it[k].(string); ok && s != "" {
					label = s
					break
				}
			}
			for _, k := range ctxKeys {
				if f, ok := it[k].(float64); ok {
					ctx = int(f)
					break
				}
			}
		default:
			continue
		}
		if id == "" {
			continue
		}
		id = stripNamespace(id)
		if label == "" {
			label = id
		}
		seen[id] = map[string]any{"id": id, "label": label, "context": ctx, "provider": providerID}
	}
	keys := make([]string, 0, len(seen))
	for k := range seen {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	out := make([]map[string]any, 0, len(keys))
	for _, k := range keys {
		out = append(out, seen[k])
	}
	return out
}

// streamChat streams a completion, invoking emit for each event.
func streamChat(c providerConfig, model string, messages []map[string]any, system string,
	maxTokens int, temperature float64, emit func(map[string]any)) error {

	path := "/chat/completions"
	var body map[string]any
	if c.id == "anthropic" {
		path = "/messages"
		filtered := []map[string]any{}
		for _, m := range messages {
			if m["role"] != "system" {
				filtered = append(filtered, m)
			}
		}
		body = map[string]any{"model": model, "max_tokens": maxTokens, "temperature": temperature,
			"stream": true, "messages": filtered}
		if system != "" {
			body["system"] = system
		}
	} else {
		full := []map[string]any{}
		if system != "" {
			full = append(full, map[string]any{"role": "system", "content": system})
		}
		full = append(full, messages...)
		body = map[string]any{"model": model, "messages": full, "max_tokens": maxTokens,
			"temperature": temperature, "stream": true}
	}
	encoded, _ := json.Marshal(body)
	resp, err := c.do(path, "POST", encoded, true)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	textLen := 0
	var usage map[string]int
	scanner := bufio.NewScanner(resp.Body)
	scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, ":") || !strings.HasPrefix(line, "data:") {
			continue
		}
		payload := strings.TrimSpace(line[5:])
		if payload == "[DONE]" {
			break
		}
		var event map[string]any
		if json.Unmarshal([]byte(payload), &event) != nil {
			continue
		}
		if errField, ok := event["error"]; ok && errField != nil {
			return fmt.Errorf("%v", errField)
		}
		if delta := extractDelta(c.id, event); delta != "" {
			textLen += len(delta)
			emit(map[string]any{"type": "delta", "text": delta})
		}
		if u := extractUsage(c.id, event); u != nil {
			usage = u
		}
	}
	if usage == nil {
		promptChars := len(system)
		for _, m := range messages {
			if s, ok := m["content"].(string); ok {
				promptChars += len(s)
			}
		}
		usage = map[string]int{"prompt": max1(promptChars / 4), "completion": max1(textLen / 4),
			"total": max1((promptChars + textLen) / 4), "estimated": 1}
	}
	emit(map[string]any{"type": "done", "usage": usage})
	return nil
}

func max1(n int) int {
	if n < 1 {
		return 1
	}
	return n
}

func extractDelta(providerID string, event map[string]any) string {
	if providerID == "anthropic" {
		if event["type"] == "content_block_delta" {
			if d, ok := event["delta"].(map[string]any); ok {
				if t, ok := d["text"].(string); ok {
					return t
				}
			}
		}
		return ""
	}
	choices, ok := event["choices"].([]any)
	if !ok || len(choices) == 0 {
		return ""
	}
	choice, _ := choices[0].(map[string]any)
	if delta, ok := choice["delta"].(map[string]any); ok {
		if s, ok := delta["content"].(string); ok {
			return s
		}
	}
	if msg, ok := choice["message"].(map[string]any); ok {
		if s, ok := msg["content"].(string); ok {
			return s
		}
	}
	return ""
}

var videoCapable = map[string]bool{"fal": true, "replicate": true, "runway": true,
	"novita": true, "openai": true, "google": true}

// submitVideo posts an animation job. No Valeroy wordmark is applied, per spec.
func submitVideo(c providerConfig, model, prompt string, images []string,
	durationSeconds int, aspectRatio string) (map[string]any, error) {
	var path string
	var body map[string]any
	switch c.id {
	case "replicate":
		path = "/predictions"
		input := map[string]any{"prompt": prompt, "num_frames": max1(durationSeconds * 8),
			"aspect_ratio": aspectRatio}
		if len(images) > 0 {
			input["image"] = images[0]
		}
		if len(images) > 1 {
			input["images"] = images
		}
		body = map[string]any{"input": input}
		if strings.Contains(model, "/") {
			body["version"] = model
		} else {
			path = "/models/" + model + "/predictions"
		}
	case "runway":
		if len(images) > 0 {
			path = "/image_to_video"
		} else {
			path = "/text_to_video"
		}
		body = map[string]any{"model": model, "promptText": prompt, "duration": durationSeconds,
			"ratio": aspectRatio}
		if len(images) > 0 {
			body["promptImage"] = images[0]
		}
	case "fal":
		path = "/" + model
		body = map[string]any{"prompt": prompt, "duration": durationSeconds, "aspect_ratio": aspectRatio}
		if len(images) > 0 {
			body["image_url"] = images[0]
		}
		if len(images) > 1 {
			body["image_urls"] = images
		}
	default:
		path = "/videos"
		body = map[string]any{"model": model, "prompt": prompt, "seconds": durationSeconds, "size": aspectRatio}
		if len(images) > 0 {
			body["input_reference"] = images[0]
		}
	}
	encoded, _ := json.Marshal(body)
	resp, err := c.do(path, "POST", encoded, false)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	var job map[string]any
	_ = json.Unmarshal(data, &job)
	return job, nil
}

// videoOutputURLs pulls finished asset URLs out of a provider job record.
func videoOutputURLs(job map[string]any) []string {
	found := []string{}
	var walk func(node any, depth int)
	walk = func(node any, depth int) {
		if depth > 6 || len(found) > 16 {
			return
		}
		switch v := node.(type) {
		case string:
			low := strings.ToLower(v)
			base := strings.SplitN(low, "?", 2)[0]
			if strings.HasPrefix(low, "http") {
				for _, ext := range []string{".mp4", ".webm", ".mov", ".gif"} {
					if strings.HasSuffix(base, ext) {
						found = append(found, v)
						break
					}
				}
			}
		case []any:
			for _, item := range v {
				walk(item, depth+1)
			}
		case map[string]any:
			for _, key := range []string{"output", "video", "videos", "assets", "url", "uri",
				"download_url", "result", "data"} {
				if sub, ok := v[key]; ok {
					walk(sub, depth+1)
				}
			}
			if len(found) == 0 {
				for _, val := range v {
					walk(val, depth+1)
				}
			}
		}
	}
	walk(job, 0)
	seen := map[string]bool{}
	out := []string{}
	for _, u := range found {
		if !seen[u] {
			seen[u] = true
			out = append(out, u)
		}
	}
	return out
}

func complete(c providerConfig, model, prompt, system string, maxTokens int) (string, error) {
	var sb strings.Builder
	err := streamChat(c, model, []map[string]any{{"role": "user", "content": prompt}},
		system, maxTokens, 0.7, func(ev map[string]any) {
			if ev["type"] == "delta" {
				sb.WriteString(ev["text"].(string))
			}
		})
	return strings.TrimSpace(sb.String()), err
}

func extractUsage(providerID string, event map[string]any) map[string]int {
	u, ok := event["usage"].(map[string]any)
	if !ok {
		return nil
	}
	num := func(k string) int {
		if f, ok := u[k].(float64); ok {
			return int(f)
		}
		return 0
	}
	var prompt, completion int
	if providerID == "anthropic" {
		prompt, completion = num("input_tokens"), num("output_tokens")
	} else {
		prompt, completion = num("prompt_tokens"), num("completion_tokens")
	}
	total := num("total_tokens")
	if total == 0 {
		total = prompt + completion
	}
	if prompt == 0 && completion == 0 && total == 0 {
		return nil
	}
	return map[string]int{"prompt": prompt, "completion": completion, "total": total}
}
