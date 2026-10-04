//! Valeroy state store: accounts, providers, sessions, agents, usage.
//!
//! Everything lives in one `state.json` under the Valeroy home directory, plus
//! one transcript file per session. Provider API keys are never written in the
//! clear: each is sealed with a data key that is itself wrapped by a key derived
//! from the account password.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::crypto::{
    consttime_eq, from_hex, hmac_sha256, pbkdf2_sha256, open as vault_open, seal as vault_seal,
    sha256, to_hex,
};
use crate::json::Json;

pub const PBKDF2_ITERATIONS: u32 = 210_000;
pub const SCHEMA_VERSION: u64 = 1;

pub type Result<T> = std::result::Result<T, String>;

/* ------------------------------------------------------------------ *
 * Paths
 * ------------------------------------------------------------------ */

/// Resolve the Valeroy home directory.
///
/// `VALEROY_HOME` wins when set, otherwise `%APPDATA%\Valeroy AI` on Windows
/// and `$XDG_DATA_HOME/valeroy` (or `~/.local/share/valeroy`) elsewhere.
pub fn home_dir() -> PathBuf {
    if let Ok(explicit) = std::env::var("VALEROY_HOME") {
        if !explicit.trim().is_empty() {
            return PathBuf::from(explicit);
        }
    }
    if cfg!(windows) {
        if let Ok(appdata) = std::env::var("APPDATA") {
            return PathBuf::from(appdata).join("Valeroy AI");
        }
    }
    if let Ok(xdg) = std::env::var("XDG_DATA_HOME") {
        if !xdg.trim().is_empty() {
            return PathBuf::from(xdg).join("valeroy");
        }
    }
    if let Ok(home) = std::env::var("HOME") {
        return PathBuf::from(home).join(".local/share/valeroy");
    }
    PathBuf::from(".valeroy")
}

pub fn state_path() -> PathBuf {
    home_dir().join("state.json")
}

pub fn sessions_dir() -> PathBuf {
    home_dir().join("sessions")
}

pub fn logs_dir() -> PathBuf {
    home_dir().join("logs")
}

pub fn runtime_dir() -> PathBuf {
    home_dir().join("runtime")
}

fn ensure_dirs() -> Result<()> {
    for dir in [home_dir(), sessions_dir(), logs_dir(), runtime_dir()] {
        fs::create_dir_all(&dir)
            .map_err(|e| format!("cannot create {}: {}", dir.display(), e))?;
    }
    Ok(())
}

/* ------------------------------------------------------------------ *
 * Randomness
 * ------------------------------------------------------------------ */

#[cfg(windows)]
#[link(name = "bcrypt")]
extern "system" {
    fn BCryptGenRandom(
        h_algorithm: *mut core::ffi::c_void,
        pb_buffer: *mut u8,
        cb_buffer: u32,
        dw_flags: u32,
    ) -> i32;
}

/// Cryptographically secure random bytes.
pub fn random_bytes(n: usize) -> Result<Vec<u8>> {
    let mut buf = vec![0u8; n];

    #[cfg(windows)]
    {
        const BCRYPT_USE_SYSTEM_PREFERRED_RNG: u32 = 0x0000_0002;
        let status = unsafe {
            BCryptGenRandom(
                core::ptr::null_mut(),
                buf.as_mut_ptr(),
                buf.len() as u32,
                BCRYPT_USE_SYSTEM_PREFERRED_RNG,
            )
        };
        if status != 0 {
            return Err(format!("BCryptGenRandom failed with status {status}"));
        }
        return Ok(buf);
    }

    #[cfg(not(windows))]
    {
        use std::io::Read;
        let mut f = fs::File::open("/dev/urandom")
            .map_err(|e| format!("cannot open /dev/urandom: {e}"))?;
        f.read_exact(&mut buf)
            .map_err(|e| format!("cannot read /dev/urandom: {e}"))?;
        Ok(buf)
    }
}

pub fn new_id(prefix: &str) -> Result<String> {
    let bytes = random_bytes(8)?;
    Ok(format!("{}_{}", prefix, to_hex(&bytes)))
}

pub fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/* ------------------------------------------------------------------ *
 * State
 * ------------------------------------------------------------------ */

pub struct Store {
    pub root: Json,
}

impl Store {
    /// Load state from disk, creating a fresh skeleton when absent.
    pub fn load() -> Result<Store> {
        ensure_dirs()?;
        let path = state_path();
        if !path.exists() {
            return Ok(Store {
                root: Store::skeleton(),
            });
        }
        let text = fs::read_to_string(&path)
            .map_err(|e| format!("cannot read {}: {}", path.display(), e))?;
        let root = Json::parse(&text)
            .ok_or_else(|| format!("{} is not valid JSON", path.display()))?;
        if !matches!(root, Json::Obj(_)) {
            return Err(format!("{} is not a JSON object", path.display()));
        }
        Ok(Store { root })
    }

    fn skeleton() -> Json {
        let mut root = Json::obj();
        root.set("schema", Json::Num(SCHEMA_VERSION as f64));
        root.set("created_at", Json::Num(now_secs() as f64));
        root.set("setup_complete", Json::Bool(false));
        root.set("account", Json::Null);
        root.set("providers", Json::obj());
        root.set("custom_models", Json::Arr(Vec::new()));
        root.set("model_cache", Json::obj());
        root.set("sessions", Json::Arr(Vec::new()));
        root.set("agents", Json::Arr(Vec::new()));
        root.set("active_session", Json::Null);
        root.set("active_agent", Json::Null);
        root.set("active_provider", Json::Null);
        root.set("active_model", Json::Null);
        root.set("usage", {
            let mut usage = Json::obj();
            usage.set("total_tokens", Json::Num(0.0));
            usage.set("prompt_tokens", Json::Num(0.0));
            usage.set("completion_tokens", Json::Num(0.0));
            usage.set("requests", Json::Num(0.0));
            usage
        });
        root
    }

    /// Write state atomically: temp file then rename, so a crash mid-write
    /// cannot leave a truncated state.json behind.
    pub fn save(&self) -> Result<()> {
        ensure_dirs()?;
        let path = state_path();
        let tmp = path.with_extension("json.tmp");
        let text = self.root.dump();
        {
            let mut f = fs::File::create(&tmp)
                .map_err(|e| format!("cannot create {}: {}", tmp.display(), e))?;
            f.write_all(text.as_bytes())
                .map_err(|e| format!("cannot write {}: {}", tmp.display(), e))?;
            f.sync_all().ok();
        }
        // Windows rename fails when the destination exists.
        if path.exists() {
            fs::remove_file(&path).ok();
        }
        fs::rename(&tmp, &path)
            .map_err(|e| format!("cannot replace {}: {}", path.display(), e))?;
        restrict_permissions(&path);
        Ok(())
    }

    /* -------------------------- account -------------------------- */

    pub fn has_account(&self) -> bool {
        !matches!(self.root.get("account"), None | Some(Json::Null))
    }

    pub fn username(&self) -> Option<&str> {
        self.root.get("account")?.str_field("username")
    }

    /// Create the account: derive a verifier from the password and wrap a fresh
    /// random data key with a separate password-derived key.
    pub fn create_account(&mut self, username: &str, password: &str) -> Result<()> {
        let username = username.trim();
        if username.is_empty() {
            return Err("username cannot be empty".into());
        }
        if username.chars().count() > 64 {
            return Err("username cannot exceed 64 characters".into());
        }
        if let Some(bad) = username.chars().find(|c| c.is_control()) {
            return Err(format!("username contains an invalid character: {bad:?}"));
        }
        validate_password(password)?;

        let salt = random_bytes(16)?;
        let verifier = pbkdf2_sha256(password.as_bytes(), &salt, PBKDF2_ITERATIONS, 32);

        // Data key protects provider secrets and survives password changes.
        let data_key = random_bytes(32)?;
        let wrap_salt = random_bytes(16)?;
        let wrap_key_bytes = pbkdf2_sha256(password.as_bytes(), &wrap_salt, PBKDF2_ITERATIONS, 32);
        let mut wrap_key = [0u8; 32];
        wrap_key.copy_from_slice(&wrap_key_bytes);
        let nonce_bytes = random_bytes(12)?;
        let mut nonce = [0u8; 12];
        nonce.copy_from_slice(&nonce_bytes);
        let wrapped = vault_seal(&wrap_key, &nonce, &data_key);

        let mut account = Json::obj();
        account.set("username", Json::string(username));
        account.set("salt", Json::string(to_hex(&salt)));
        account.set("verifier", Json::string(to_hex(&verifier)));
        account.set("iterations", Json::Num(PBKDF2_ITERATIONS as f64));
        account.set("wrap_salt", Json::string(to_hex(&wrap_salt)));
        account.set("wrapped_data_key", Json::string(to_hex(&wrapped)));
        account.set("created_at", Json::Num(now_secs() as f64));
        self.root.set("account", account);
        Ok(())
    }

    /// Verify a password against the stored verifier.
    pub fn verify_password(&self, password: &str) -> Result<bool> {
        let account = self
            .root
            .get("account")
            .filter(|a| !matches!(a, Json::Null))
            .ok_or_else(|| "no account has been created yet".to_string())?;
        let salt_hex = account
            .str_field("salt")
            .ok_or_else(|| "account record is missing its salt".to_string())?;
        let verifier_hex = account
            .str_field("verifier")
            .ok_or_else(|| "account record is missing its verifier".to_string())?;
        let iterations = account
            .get("iterations")
            .and_then(|v| v.as_u64())
            .unwrap_or(PBKDF2_ITERATIONS as u64) as u32;

        let salt = from_hex(salt_hex).ok_or_else(|| "account salt is malformed".to_string())?;
        let expected =
            from_hex(verifier_hex).ok_or_else(|| "account verifier is malformed".to_string())?;
        let actual = pbkdf2_sha256(password.as_bytes(), &salt, iterations, expected.len());
        Ok(consttime_eq(&actual, &expected))
    }

    /// Unwrap the data key. Returns an error when the password is wrong.
    pub fn unlock(&self, password: &str) -> Result<[u8; 32]> {
        if !self.verify_password(password)? {
            return Err("incorrect password".into());
        }
        let account = self
            .root
            .get("account")
            .ok_or_else(|| "no account has been created yet".to_string())?;
        let wrap_salt_hex = account
            .str_field("wrap_salt")
            .ok_or_else(|| "account record is missing its wrap salt".to_string())?;
        let wrapped_hex = account
            .str_field("wrapped_data_key")
            .ok_or_else(|| "account record is missing its wrapped data key".to_string())?;
        let iterations = account
            .get("iterations")
            .and_then(|v| v.as_u64())
            .unwrap_or(PBKDF2_ITERATIONS as u64) as u32;

        let wrap_salt =
            from_hex(wrap_salt_hex).ok_or_else(|| "wrap salt is malformed".to_string())?;
        let wrapped =
            from_hex(wrapped_hex).ok_or_else(|| "wrapped data key is malformed".to_string())?;

        let wrap_key_bytes = pbkdf2_sha256(password.as_bytes(), &wrap_salt, iterations, 32);
        let mut wrap_key = [0u8; 32];
        wrap_key.copy_from_slice(&wrap_key_bytes);

        let data_key = vault_open(&wrap_key, &wrapped)
            .ok_or_else(|| "data key failed its integrity check".to_string())?;
        if data_key.len() != 32 {
            return Err("data key has the wrong length".into());
        }
        let mut out = [0u8; 32];
        out.copy_from_slice(&data_key);
        Ok(out)
    }

    /// Change the password, re-wrapping the existing data key so stored API
    /// keys stay readable.
    pub fn change_password(&mut self, current: &str, next: &str) -> Result<()> {
        let data_key = self.unlock(current)?;
        validate_password(next)?;

        let salt = random_bytes(16)?;
        let verifier = pbkdf2_sha256(next.as_bytes(), &salt, PBKDF2_ITERATIONS, 32);
        let wrap_salt = random_bytes(16)?;
        let wrap_key_bytes = pbkdf2_sha256(next.as_bytes(), &wrap_salt, PBKDF2_ITERATIONS, 32);
        let mut wrap_key = [0u8; 32];
        wrap_key.copy_from_slice(&wrap_key_bytes);
        let nonce_bytes = random_bytes(12)?;
        let mut nonce = [0u8; 12];
        nonce.copy_from_slice(&nonce_bytes);
        let wrapped = vault_seal(&wrap_key, &nonce, &data_key);

        if let Some(Json::Obj(account)) = self.root.get("account").cloned().as_mut() {
            account.insert("salt".into(), Json::string(to_hex(&salt)));
            account.insert("verifier".into(), Json::string(to_hex(&verifier)));
            account.insert("iterations".into(), Json::Num(PBKDF2_ITERATIONS as f64));
            account.insert("wrap_salt".into(), Json::string(to_hex(&wrap_salt)));
            account.insert("wrapped_data_key".into(), Json::string(to_hex(&wrapped)));
            account.insert("password_changed_at".into(), Json::Num(now_secs() as f64));
            self.root.set("account", Json::Obj(account.clone()));
            Ok(())
        } else {
            Err("no account has been created yet".into())
        }
    }

    /* -------------------------- providers -------------------------- */

    pub fn enable_provider(
        &mut self,
        id: &str,
        api_key: &str,
        data_key: &[u8; 32],
        base_url: Option<&str>,
    ) -> Result<()> {
        if id.trim().is_empty() {
            return Err("provider id cannot be empty".into());
        }
        let nonce_bytes = random_bytes(12)?;
        let mut nonce = [0u8; 12];
        nonce.copy_from_slice(&nonce_bytes);
        let sealed = vault_seal(data_key, &nonce, api_key.as_bytes());

        let mut entry = Json::obj();
        entry.set("id", Json::string(id));
        entry.set("enabled", Json::Bool(true));
        entry.set("sealed_key", Json::string(to_hex(&sealed)));
        entry.set("key_fingerprint", Json::string(fingerprint(api_key)));
        entry.set("added_at", Json::Num(now_secs() as f64));
        if let Some(url) = base_url {
            entry.set("base_url", Json::string(url));
        }

        let mut providers = self
            .root
            .get("providers")
            .cloned()
            .unwrap_or_else(Json::obj);
        if let Json::Obj(map) = &mut providers {
            map.insert(id.to_string(), entry);
        }
        self.root.set("providers", providers);
        Ok(())
    }

    pub fn disable_provider(&mut self, id: &str) -> Result<()> {
        let mut providers = self
            .root
            .get("providers")
            .cloned()
            .unwrap_or_else(Json::obj);
        let existed = if let Json::Obj(map) = &mut providers {
            map.remove(id).is_some()
        } else {
            false
        };
        if !existed {
            return Err(format!("provider '{id}' is not enabled"));
        }
        self.root.set("providers", providers);

        // Drop the selection if it pointed at the provider we just removed.
        if self.root.get("active_provider").and_then(|v| v.as_str()) == Some(id) {
            self.root.set("active_provider", Json::Null);
            self.root.set("active_model", Json::Null);
        }
        if let Some(Json::Obj(cache)) = self.root.get("model_cache").cloned().as_mut() {
            cache.remove(id);
            self.root.set("model_cache", Json::Obj(cache.clone()));
        }
        Ok(())
    }

    pub fn provider_ids(&self) -> Vec<String> {
        match self.root.get("providers") {
            Some(Json::Obj(map)) => map.keys().cloned().collect(),
            _ => Vec::new(),
        }
    }

    pub fn provider_key(&self, id: &str, data_key: &[u8; 32]) -> Result<String> {
        let entry = self
            .root
            .get("providers")
            .and_then(|p| p.get(id))
            .ok_or_else(|| format!("provider '{id}' is not enabled"))?;
        let sealed_hex = entry
            .str_field("sealed_key")
            .ok_or_else(|| format!("provider '{id}' has no stored key"))?;
        let sealed =
            from_hex(sealed_hex).ok_or_else(|| format!("provider '{id}' key is malformed"))?;
        let plain = vault_open(data_key, &sealed)
            .ok_or_else(|| format!("provider '{id}' key failed its integrity check"))?;
        String::from_utf8(plain).map_err(|_| format!("provider '{id}' key is not valid UTF-8"))
    }

    /// Redacted provider list, safe to hand to the frontend.
    pub fn providers_public(&self) -> Json {
        let mut out = Vec::new();
        if let Some(Json::Obj(map)) = self.root.get("providers") {
            for (id, entry) in map {
                let mut item = Json::obj();
                item.set("id", Json::string(id));
                item.set(
                    "enabled",
                    Json::Bool(entry.get("enabled").and_then(|v| v.as_bool()).unwrap_or(true)),
                );
                item.set("has_key", Json::Bool(entry.get("sealed_key").is_some()));
                item.set(
                    "key_fingerprint",
                    Json::string(entry.str_field("key_fingerprint").unwrap_or("")),
                );
                if let Some(url) = entry.str_field("base_url") {
                    item.set("base_url", Json::string(url));
                }
                item.set(
                    "added_at",
                    Json::Num(entry.get("added_at").and_then(|v| v.as_f64()).unwrap_or(0.0)),
                );
                out.push(item);
            }
        }
        Json::Arr(out)
    }

    pub fn cache_models(&mut self, provider: &str, models: Json) {
        let mut cache = self
            .root
            .get("model_cache")
            .cloned()
            .unwrap_or_else(Json::obj);
        if let Json::Obj(map) = &mut cache {
            let mut entry = Json::obj();
            entry.set("fetched_at", Json::Num(now_secs() as f64));
            entry.set("models", models);
            map.insert(provider.to_string(), entry);
        }
        self.root.set("model_cache", cache);
    }

    /* -------------------------- custom models -------------------------- */

    pub fn add_custom_model(
        &mut self,
        model_id: &str,
        label: &str,
        base_url: &str,
        api_key: &str,
        data_key: &[u8; 32],
    ) -> Result<String> {
        if model_id.trim().is_empty() {
            return Err("model id cannot be empty".into());
        }
        if base_url.trim().is_empty() {
            return Err("base url cannot be empty".into());
        }
        let nonce_bytes = random_bytes(12)?;
        let mut nonce = [0u8; 12];
        nonce.copy_from_slice(&nonce_bytes);
        let sealed = vault_seal(data_key, &nonce, api_key.as_bytes());

        let entry_id = new_id("cm")?;
        let mut entry = Json::obj();
        entry.set("entry_id", Json::string(&entry_id));
        entry.set("id", Json::string(model_id));
        entry.set(
            "label",
            Json::string(if label.trim().is_empty() { model_id } else { label }),
        );
        entry.set("base_url", Json::string(base_url));
        entry.set("provider", Json::string("custom"));
        entry.set("sealed_key", Json::string(to_hex(&sealed)));
        entry.set("key_fingerprint", Json::string(fingerprint(api_key)));
        entry.set("added_at", Json::Num(now_secs() as f64));

        let mut list = self
            .root
            .get("custom_models")
            .cloned()
            .unwrap_or_else(|| Json::Arr(Vec::new()));
        if let Some(items) = list.as_array_mut() {
            // Replace an existing entry with the same model id.
            items.retain(|item| item.str_field("id") != Some(model_id));
            items.push(entry);
        }
        self.root.set("custom_models", list);
        Ok(entry_id)
    }

    pub fn custom_model_key(&self, model_id: &str, data_key: &[u8; 32]) -> Result<String> {
        let list = self
            .root
            .get("custom_models")
            .and_then(|v| v.as_array())
            .ok_or_else(|| "no custom models are registered".to_string())?;
        let entry = list
            .iter()
            .find(|item| item.str_field("id") == Some(model_id))
            .ok_or_else(|| format!("custom model '{model_id}' is not registered"))?;
        let sealed_hex = entry
            .str_field("sealed_key")
            .ok_or_else(|| format!("custom model '{model_id}' has no stored key"))?;
        let sealed = from_hex(sealed_hex)
            .ok_or_else(|| format!("custom model '{model_id}' key is malformed"))?;
        let plain = vault_open(data_key, &sealed)
            .ok_or_else(|| format!("custom model '{model_id}' key failed its integrity check"))?;
        String::from_utf8(plain)
            .map_err(|_| format!("custom model '{model_id}' key is not valid UTF-8"))
    }

    pub fn custom_models_public(&self) -> Json {
        let mut out = Vec::new();
        if let Some(items) = self.root.get("custom_models").and_then(|v| v.as_array()) {
            for item in items {
                let mut safe = Json::obj();
                safe.set("id", Json::string(item.str_field("id").unwrap_or("")));
                safe.set("label", Json::string(item.str_field("label").unwrap_or("")));
                safe.set(
                    "base_url",
                    Json::string(item.str_field("base_url").unwrap_or("")),
                );
                safe.set("provider", Json::string("custom"));
                safe.set(
                    "key_fingerprint",
                    Json::string(item.str_field("key_fingerprint").unwrap_or("")),
                );
                out.push(safe);
            }
        }
        Json::Arr(out)
    }

    /* -------------------------- agents -------------------------- */

    pub fn create_agent(
        &mut self,
        name: &str,
        description: &str,
        instructions: &str,
    ) -> Result<String> {
        let name = name.trim();
        if name.is_empty() {
            return Err("agent name cannot be empty".into());
        }
        let id = new_id("agent")?;
        let mut agent = Json::obj();
        agent.set("id", Json::string(&id));
        agent.set("name", Json::string(name));
        agent.set("description", Json::string(description.trim()));
        agent.set("instructions", Json::string(instructions.trim()));
        agent.set("created_at", Json::Num(now_secs() as f64));

        let mut agents = self
            .root
            .get("agents")
            .cloned()
            .unwrap_or_else(|| Json::Arr(Vec::new()));
        if let Some(items) = agents.as_array_mut() {
            items.push(agent);
        }
        self.root.set("agents", agents);
        if matches!(self.root.get("active_agent"), None | Some(Json::Null)) {
            self.root.set("active_agent", Json::string(&id));
        }
        Ok(id)
    }

    pub fn resolve_agent(&self, needle: &str) -> Option<String> {
        let items = self.root.get("agents")?.as_array()?;
        items
            .iter()
            .find(|a| a.str_field("id") == Some(needle))
            .or_else(|| {
                items.iter().find(|a| {
                    a.str_field("name")
                        .map(|n| n.eq_ignore_ascii_case(needle))
                        .unwrap_or(false)
                })
            })
            .and_then(|a| a.str_field("id"))
            .map(|s| s.to_string())
    }

    pub fn delete_agent(&mut self, id: &str) -> Result<()> {
        let resolved = self
            .resolve_agent(id)
            .ok_or_else(|| format!("agent '{id}' does not exist"))?;
        let mut agents = self
            .root
            .get("agents")
            .cloned()
            .unwrap_or_else(|| Json::Arr(Vec::new()));
        if let Some(items) = agents.as_array_mut() {
            items.retain(|a| a.str_field("id") != Some(resolved.as_str()));
        }
        self.root.set("agents", agents);
        if self.root.get("active_agent").and_then(|v| v.as_str()) == Some(resolved.as_str()) {
            self.root.set("active_agent", Json::Null);
        }
        Ok(())
    }

    /* -------------------------- sessions -------------------------- */

    pub fn create_session(&mut self, title: &str, agent: Option<&str>) -> Result<String> {
        let id = new_id("ses")?;
        let agent_id = match agent {
            Some(a) => self
                .resolve_agent(a)
                .ok_or_else(|| format!("agent '{a}' does not exist"))?,
            None => self
                .root
                .get("active_agent")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
        };

        let mut session = Json::obj();
        session.set("id", Json::string(&id));
        session.set(
            "title",
            Json::string(if title.trim().is_empty() {
                "New session"
            } else {
                title.trim()
            }),
        );
        session.set("agent", Json::string(&agent_id));
        session.set("created_at", Json::Num(now_secs() as f64));
        session.set("updated_at", Json::Num(now_secs() as f64));
        session.set("message_count", Json::Num(0.0));
        session.set("tokens", Json::Num(0.0));

        let mut sessions = self
            .root
            .get("sessions")
            .cloned()
            .unwrap_or_else(|| Json::Arr(Vec::new()));
        if let Some(items) = sessions.as_array_mut() {
            items.push(session);
        }
        self.root.set("sessions", sessions);
        self.root.set("active_session", Json::string(&id));

        let transcript = sessions_dir().join(format!("{id}.jsonl"));
        fs::File::create(&transcript)
            .map_err(|e| format!("cannot create {}: {}", transcript.display(), e))?;
        Ok(id)
    }

    pub fn session_exists(&self, id: &str) -> bool {
        self.root
            .get("sessions")
            .and_then(|v| v.as_array())
            .map(|items| items.iter().any(|s| s.str_field("id") == Some(id)))
            .unwrap_or(false)
    }

    pub fn delete_session(&mut self, id: &str) -> Result<()> {
        if !self.session_exists(id) {
            return Err(format!("session '{id}' does not exist"));
        }
        let mut sessions = self
            .root
            .get("sessions")
            .cloned()
            .unwrap_or_else(|| Json::Arr(Vec::new()));
        if let Some(items) = sessions.as_array_mut() {
            items.retain(|s| s.str_field("id") != Some(id));
        }
        self.root.set("sessions", sessions);
        if self.root.get("active_session").and_then(|v| v.as_str()) == Some(id) {
            self.root.set("active_session", Json::Null);
        }
        fs::remove_file(sessions_dir().join(format!("{id}.jsonl"))).ok();
        Ok(())
    }

    /// Append one message to a session transcript and update its counters.
    pub fn append_message(
        &mut self,
        session_id: &str,
        role: &str,
        content: &str,
        tokens: u64,
    ) -> Result<()> {
        if !self.session_exists(session_id) {
            return Err(format!("session '{session_id}' does not exist"));
        }
        let mut record = Json::obj();
        record.set("ts", Json::Num(now_secs() as f64));
        record.set("role", Json::string(role));
        record.set("content", Json::string(content));
        record.set("tokens", Json::Num(tokens as f64));

        let path = sessions_dir().join(format!("{session_id}.jsonl"));
        let mut f = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
            .map_err(|e| format!("cannot open {}: {}", path.display(), e))?;
        writeln!(f, "{}", record.dump())
            .map_err(|e| format!("cannot write {}: {}", path.display(), e))?;

        let mut sessions = self
            .root
            .get("sessions")
            .cloned()
            .unwrap_or_else(|| Json::Arr(Vec::new()));
        if let Some(items) = sessions.as_array_mut() {
            for item in items.iter_mut() {
                if item.str_field("id") == Some(session_id) {
                    let count = item
                        .get("message_count")
                        .and_then(|v| v.as_u64())
                        .unwrap_or(0);
                    let total = item.get("tokens").and_then(|v| v.as_u64()).unwrap_or(0);
                    item.set("message_count", Json::Num((count + 1) as f64));
                    item.set("tokens", Json::Num((total + tokens) as f64));
                    item.set("updated_at", Json::Num(now_secs() as f64));
                }
            }
        }
        self.root.set("sessions", sessions);
        self.add_usage(tokens, 0, 0);
        Ok(())
    }

    pub fn read_transcript(&self, session_id: &str, limit: usize) -> Result<Json> {
        let path = sessions_dir().join(format!("{session_id}.jsonl"));
        if !path.exists() {
            return Ok(Json::Arr(Vec::new()));
        }
        let text = fs::read_to_string(&path)
            .map_err(|e| format!("cannot read {}: {}", path.display(), e))?;
        let mut items: Vec<Json> = text
            .lines()
            .filter(|line| !line.trim().is_empty())
            .filter_map(Json::parse)
            .collect();
        if limit > 0 && items.len() > limit {
            items = items.split_off(items.len() - limit);
        }
        Ok(Json::Arr(items))
    }

    /* -------------------------- usage -------------------------- */

    pub fn add_usage(&mut self, total: u64, prompt: u64, completion: u64) {
        let mut usage = self.root.get("usage").cloned().unwrap_or_else(Json::obj);
        let bump = |usage: &mut Json, key: &str, by: u64| {
            let current = usage.get(key).and_then(|v| v.as_u64()).unwrap_or(0);
            usage.set(key, Json::Num((current + by) as f64));
        };
        bump(&mut usage, "total_tokens", total);
        bump(&mut usage, "prompt_tokens", prompt);
        bump(&mut usage, "completion_tokens", completion);
        if total > 0 {
            bump(&mut usage, "requests", 1);
        }
        self.root.set("usage", usage);
    }

    /* -------------------------- public view -------------------------- */

    /// State with every secret stripped. This is what the gateway serves.
    pub fn public_view(&self) -> Json {
        let mut out = Json::obj();
        out.set(
            "schema",
            Json::Num(
                self.root
                    .get("schema")
                    .and_then(|v| v.as_f64())
                    .unwrap_or(SCHEMA_VERSION as f64),
            ),
        );
        out.set(
            "setup_complete",
            Json::Bool(
                self.root
                    .get("setup_complete")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false),
            ),
        );

        let mut account = Json::obj();
        account.set("exists", Json::Bool(self.has_account()));
        account.set("username", Json::string(self.username().unwrap_or("")));
        out.set("account", account);

        out.set("providers", self.providers_public());
        out.set("custom_models", self.custom_models_public());
        out.set(
            "sessions",
            self.root
                .get("sessions")
                .cloned()
                .unwrap_or_else(|| Json::Arr(Vec::new())),
        );
        out.set(
            "agents",
            self.root
                .get("agents")
                .cloned()
                .unwrap_or_else(|| Json::Arr(Vec::new())),
        );
        for key in [
            "active_session",
            "active_agent",
            "active_provider",
            "active_model",
        ] {
            out.set(key, self.root.get(key).cloned().unwrap_or(Json::Null));
        }
        out.set(
            "usage",
            self.root.get("usage").cloned().unwrap_or_else(Json::obj),
        );
        out.set("home", Json::string(home_dir().display().to_string()));
        out
    }
}

/* ------------------------------------------------------------------ *
 * Helpers
 * ------------------------------------------------------------------ */

/// Short, non-reversible tag so the UI can show *which* key is stored without
/// revealing it.
pub fn fingerprint(secret: &str) -> String {
    let digest = sha256(secret.as_bytes());
    to_hex(&digest[..4])
}

pub fn validate_password(password: &str) -> Result<()> {
    let len = password.chars().count();
    if len < 8 {
        return Err("password must be at least 8 characters".into());
    }
    if len > 256 {
        return Err("password cannot exceed 256 characters".into());
    }
    if password.chars().any(|c| c.is_control()) {
        return Err("password cannot contain control characters".into());
    }
    if !password.chars().any(|c| c.is_ascii_digit())
        && !password.chars().any(|c| !c.is_alphanumeric())
    {
        return Err("password must contain at least one digit or symbol".into());
    }
    Ok(())
}

/// Issue a short-lived token the frontend uses to talk to the gateway.
pub fn mint_gateway_token(data_key: &[u8; 32], issued_at: u64) -> String {
    let payload = format!("valeroy-gateway:{issued_at}");
    let mac = hmac_sha256(data_key, payload.as_bytes());
    format!("{issued_at}.{}", to_hex(&mac[..16]))
}

#[cfg(unix)]
fn restrict_permissions(path: &Path) {
    use std::os::unix::fs::PermissionsExt;
    let _ = fs::set_permissions(path, fs::Permissions::from_mode(0o600));
}

#[cfg(not(unix))]
fn restrict_permissions(_path: &Path) {
    // Windows inherits the user-profile ACL, which is already user-scoped.
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_home(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("valeroy-test-{tag}-{}", now_secs()));
        std::env::set_var("VALEROY_HOME", &dir);
        let _ = fs::remove_dir_all(&dir);
        dir
    }

    #[test]
    fn password_rules_reject_weak_input() {
        assert!(validate_password("short1").is_err());
        assert!(validate_password("alllettersonly").is_err());
        assert!(validate_password("goodpass1").is_ok());
        assert!(validate_password("good pass!").is_ok());
    }

    #[test]
    fn fingerprint_is_stable_and_short() {
        assert_eq!(fingerprint("abc").len(), 8);
        assert_eq!(fingerprint("abc"), fingerprint("abc"));
        assert_ne!(fingerprint("abc"), fingerprint("abd"));
    }

    #[test]
    fn account_roundtrip_and_vault() {
        let _dir = temp_home("account");
        let mut store = Store { root: Store::skeleton() };
        store.create_account("mcalrifle", "valeroy-pass1").unwrap();

        assert!(store.verify_password("valeroy-pass1").unwrap());
        assert!(!store.verify_password("wrong-pass1").unwrap());

        let key = store.unlock("valeroy-pass1").unwrap();
        store
            .enable_provider("openrouter", "sk-or-secret", &key, None)
            .unwrap();
        assert_eq!(
            store.provider_key("openrouter", &key).unwrap(),
            "sk-or-secret"
        );

        // Public view must never leak the key.
        let dumped = store.public_view().dump();
        assert!(!dumped.contains("sk-or-secret"));
        assert!(!dumped.contains("sealed_key"));
    }

    #[test]
    fn password_change_preserves_provider_keys() {
        let _dir = temp_home("rotate");
        let mut store = Store { root: Store::skeleton() };
        store.create_account("mcalrifle", "firstpass1").unwrap();
        let key = store.unlock("firstpass1").unwrap();
        store
            .enable_provider("novita", "novita-secret", &key, None)
            .unwrap();

        store.change_password("firstpass1", "secondpass2").unwrap();
        assert!(store.verify_password("secondpass2").unwrap());
        let new_key = store.unlock("secondpass2").unwrap();
        assert_eq!(store.provider_key("novita", &new_key).unwrap(), "novita-secret");
    }

    #[test]
    fn disabling_provider_clears_selection() {
        let _dir = temp_home("disable");
        let mut store = Store { root: Store::skeleton() };
        store.create_account("u", "password1").unwrap();
        let key = store.unlock("password1").unwrap();
        store.enable_provider("groq", "k", &key, None).unwrap();
        store.root.set("active_provider", Json::string("groq"));
        store.root.set("active_model", Json::string("some-model"));

        store.disable_provider("groq").unwrap();
        assert!(matches!(store.root.get("active_provider"), Some(Json::Null)));
        assert!(matches!(store.root.get("active_model"), Some(Json::Null)));
        assert!(store.disable_provider("groq").is_err());
    }
}
