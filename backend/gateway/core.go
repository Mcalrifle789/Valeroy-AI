// Core bridge: every state change goes through the valeroy-core binary so there
// is one implementation of the account, vault, session and agent rules shared
// with the Python gateway.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

// coreBinary locates valeroy-core, honouring VALEROY_CORE_BIN.
func coreBinary() (string, error) {
	if override := os.Getenv("VALEROY_CORE_BIN"); override != "" {
		if _, err := os.Stat(override); err == nil {
			return override, nil
		}
	}
	exe := "valeroy-core"
	if runtime.GOOS == "windows" {
		exe = "valeroy-core.exe"
	}
	// This binary lives in build/native; the core lives in backend/core/target.
	self, err := os.Executable()
	if err != nil {
		return "", err
	}
	root := filepath.Dir(filepath.Dir(filepath.Dir(self))) // build/native/.. -> repo root
	for _, profile := range []string{"release", "debug"} {
		candidate := filepath.Join(root, "backend", "core", "target", profile, exe)
		if _, err := os.Stat(candidate); err == nil {
			return candidate, nil
		}
	}
	return "", fmt.Errorf("valeroy-core not found; build it with cargo build --release")
}

// core runs valeroy-core and returns its parsed JSON reply.
func core(stdin string, args ...string) (map[string]any, error) {
	bin, err := coreBinary()
	if err != nil {
		return nil, err
	}
	ctx := exec.Command(bin, args...)
	if stdin != "" {
		ctx.Stdin = strings.NewReader(stdin)
	}
	var out, errBuf bytes.Buffer
	ctx.Stdout = &out
	ctx.Stderr = &errBuf
	ctx.Env = os.Environ()

	done := make(chan error, 1)
	if err := ctx.Start(); err != nil {
		return nil, fmt.Errorf("cannot run valeroy-core: %w", err)
	}
	go func() { done <- ctx.Wait() }()
	select {
	case <-time.After(30 * time.Second):
		_ = ctx.Process.Kill()
		return nil, fmt.Errorf("valeroy-core timed out")
	case err := <-done:
		text := strings.TrimSpace(out.String())
		if text == "" {
			msg := strings.TrimSpace(errBuf.String())
			if msg == "" {
				msg = "valeroy-core produced no output"
			}
			return nil, fmt.Errorf("%s", msg)
		}
		var payload map[string]any
		if jerr := json.Unmarshal([]byte(text), &payload); jerr != nil {
			return nil, fmt.Errorf("valeroy-core returned unparseable output")
		}
		if ok, _ := payload["ok"].(bool); !ok {
			if msg, _ := payload["error"].(string); msg != "" {
				return nil, fmt.Errorf("%s", msg)
			}
			return nil, fmt.Errorf("valeroy-core failed")
		}
		_ = err // non-zero exit already surfaces via ok=false above
		return payload, nil
	}
}

func coreAvailable() bool {
	_, err := coreBinary()
	return err == nil
}
