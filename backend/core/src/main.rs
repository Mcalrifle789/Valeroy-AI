//! valeroy-core - Valeroy AI core state engine.
//!
//! A line-oriented JSON CLI. The Go gateway and the Python TUI both drive state
//! through this binary so there is exactly one implementation of the rules
//! around accounts, the credential vault, sessions and agents.
//!
//! Every invocation prints a single JSON object to stdout:
//!   {"ok":true,  ...}
//!   {"ok":false, "error":"..."}
//! and exits 0 on success, 1 on failure.

mod crypto;
mod json;
mod store;

use std::collections::BTreeMap;
use std::io::{self, Read};

use json::Json;
use store::{Store, mint_gateway_token, now_secs};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match dispatch(&args) {
        Ok(payload) => {
            let mut out = Json::obj();
            out.set("ok", Json::Bool(true));
            if let Json::Obj(fields) = payload {
                for (key, value) in fields {
                    out.set(&key, value);
                }
            }
            println!("{}", out.dump());
        }
        Err(message) => {
            let mut out = Json::obj();
            out.set("ok", Json::Bool(false));
            out.set("error", Json::string(message));
            println!("{}", out.dump());
            std::process::exit(1);
        }
    }
}

const USAGE: &str = "\
valeroy-core <group> <action> [--flag value ...]

groups:
  state     path | show | reset
  account   create | verify | unlock | exists | passwd
  provider  enable | disable | list | key | select
  model     select | add | list | key | cache
  session   new | list | switch | delete | append | transcript
  agent     create | list | switch | delete
  usage     add | show
  setup     complete | status
  token     mint
  version
";

fn dispatch(args: &[String]) -> store::Result<Json> {
    let flags = parse_flags(args)?;
    let group = args.first().map(|s| s.as_str()).unwrap_or("");
    let action = args
        .get(1)
        .filter(|a| !a.starts_with("--"))
        .map(|s| s.as_str())
        .unwrap_or("");

    match (group, action) {
        ("version", _) | ("--version", _) => {
            let mut out = Json::obj();
            out.set("name", Json::string("valeroy-core"));
            out.set("version", Json::string(env!("CARGO_PKG_VERSION")));
            out.set("schema", Json::Num(store::SCHEMA_VERSION as f64));
            Ok(out)
        }
        ("help", _) | ("--help", _) | ("", _) => Err(USAGE.trim().to_string()),

        ("state", "path") => {
            let mut out = Json::obj();
            out.set("home", Json::string(store::home_dir().display().to_string()));
            out.set("state", Json::string(store::state_path().display().to_string()));
            out.set("sessions", Json::string(store::sessions_dir().display().to_string()));
            out.set("logs", Json::string(store::logs_dir().display().to_string()));
            out.set("runtime", Json::string(store::runtime_dir().display().to_string()));
            Ok(out)
        }
        ("state", "show") => {
            let store = Store::load()?;
            let mut out = Json::obj();
            out.set("state", store.public_view());
            Ok(out)
        }
        ("state", "reset") => {
            // Back up rather than destroy: setup reset must be recoverable.
            let path = store::state_path();
            if path.exists() {
                let backup = store::home_dir().join(format!("state.backup.{}.json", now_secs()));
                std::fs::copy(&path, &backup)
                    .map_err(|e| format!("cannot back up state: {e}"))?;
                std::fs::remove_file(&path).map_err(|e| format!("cannot remove state: {e}"))?;
                let mut out = Json::obj();
                out.set("backup", Json::string(backup.display().to_string()));
                return Ok(out);
            }
            Ok(Json::obj())
        }

        ("account", "create") => {
            let username = require(&flags, "username")?;
            let password = require_secret(&flags, "password")?;
            let confirm = require_secret(&flags, "confirm")?;
            if password != confirm {
                return Err("passwords do not match".into());
            }
            let mut store = Store::load()?;
            if store.has_account() && !flag_bool(&flags, "force") {
                return Err("an account already exists; pass --force to replace it".into());
            }
            store.create_account(&username, &password)?;
            store.save()?;
            let mut out = Json::obj();
            out.set("username", Json::string(username));
            Ok(out)
        }
        ("account", "verify") => {
            let password = require_secret(&flags, "password")?;
            let store = Store::load()?;
            let valid = store.verify_password(&password)?;
            if !valid {
                return Err("incorrect password".into());
            }
            let mut out = Json::obj();
            out.set("username", Json::string(store.username().unwrap_or("")));
            Ok(out)
        }
        ("account", "unlock") => {
            let password = require_secret(&flags, "password")?;
            let store = Store::load()?;
            let data_key = store.unlock(&password)?;
            let issued = now_secs();
            let mut out = Json::obj();
            out.set("username", Json::string(store.username().unwrap_or("")));
            out.set("data_key", Json::string(crypto::to_hex(&data_key)));
            out.set("gateway_token", Json::string(mint_gateway_token(&data_key, issued)));
            out.set("issued_at", Json::Num(issued as f64));
            Ok(out)
        }
        ("account", "exists") => {
            let store = Store::load()?;
            let mut out = Json::obj();
            out.set("exists", Json::Bool(store.has_account()));
            out.set("username", Json::string(store.username().unwrap_or("")));
            Ok(out)
        }
        ("account", "passwd") => {
            let current = require_secret(&flags, "current")?;
            let next = require_secret(&flags, "password")?;
            let confirm = require_secret(&flags, "confirm")?;
            if next != confirm {
                return Err("passwords do not match".into());
            }
            let mut store = Store::load()?;
            store.change_password(&current, &next)?;
            store.save()?;
            Ok(Json::obj())
        }

        ("provider", "enable") => {
            let id = require(&flags, "id")?;
            let api_key = require_secret(&flags, "key")?;
            let data_key = data_key_from(&flags)?;
            let mut store = Store::load()?;
            store.enable_provider(&id, &api_key, &data_key, flags.get("base-url").map(|s| s.as_str()))?;
            store.save()?;
            let mut out = Json::obj();
            out.set("id", Json::string(id));
            out.set("fingerprint", Json::string(store::fingerprint(&api_key)));
            Ok(out)
        }
        ("provider", "disable") => {
            let id = require(&flags, "id")?;
            let mut store = Store::load()?;
            store.disable_provider(&id)?;
            store.save()?;
            Ok(Json::obj())
        }
        ("provider", "list") => {
            let store = Store::load()?;
            let mut out = Json::obj();
            out.set("providers", store.providers_public());
            Ok(out)
        }
        ("provider", "key") => {
            let id = require(&flags, "id")?;
            let data_key = data_key_from(&flags)?;
            let store = Store::load()?;
            let mut out = Json::obj();
            out.set("id", Json::string(&id));
            out.set("key", Json::string(store.provider_key(&id, &data_key)?));
            Ok(out)
        }
        ("provider", "select") => {
            let id = require(&flags, "id")?;
            let mut store = Store::load()?;
            if !store.provider_ids().iter().any(|p| p == &id) {
                return Err(format!("provider '{id}' is not enabled"));
            }
            store.root.set("active_provider", Json::string(&id));
            store.root.set("active_model", Json::Null);
            store.save()?;
            Ok(Json::obj())
        }

        ("model", "select") => {
            let id = require(&flags, "id")?;
            let mut store = Store::load()?;
            if let Some(provider) = flags.get("provider") {
                store.root.set("active_provider", Json::string(provider));
            }
            store.root.set("active_model", Json::string(&id));
            store.save()?;
            let mut out = Json::obj();
            out.set("model", Json::string(id));
            Ok(out)
        }
        ("model", "add") => {
            let id = require(&flags, "id")?;
            let base_url = require(&flags, "base-url")?;
            let api_key = require_secret(&flags, "key")?;
            let label = flags.get("label").cloned().unwrap_or_default();
            let data_key = data_key_from(&flags)?;
            let mut store = Store::load()?;
            let entry_id = store.add_custom_model(&id, &label, &base_url, &api_key, &data_key)?;
            store.save()?;
            let mut out = Json::obj();
            out.set("entry_id", Json::string(entry_id));
            out.set("id", Json::string(id));
            Ok(out)
        }
        ("model", "list") => {
            let store = Store::load()?;
            let mut out = Json::obj();
            out.set("custom_models", store.custom_models_public());
            out.set(
                "cache",
                store.root.get("model_cache").cloned().unwrap_or_else(Json::obj),
            );
            out.set(
                "active_model",
                store.root.get("active_model").cloned().unwrap_or(Json::Null),
            );
            Ok(out)
        }
        ("model", "key") => {
            let id = require(&flags, "id")?;
            let data_key = data_key_from(&flags)?;
            let store = Store::load()?;
            let mut out = Json::obj();
            out.set("id", Json::string(&id));
            out.set("key", Json::string(store.custom_model_key(&id, &data_key)?));
            Ok(out)
        }
        ("model", "cache") => {
            let provider = require(&flags, "provider")?;
            // Model lists arrive on stdin so a long JSON payload never hits the
            // command line length limit.
            let mut raw = String::new();
            io::stdin()
                .read_to_string(&mut raw)
                .map_err(|e| format!("cannot read stdin: {e}"))?;
            let models = Json::parse(raw.trim())
                .ok_or_else(|| "stdin did not contain valid JSON".to_string())?;
            let count = models.as_array().map(|a| a.len()).unwrap_or(0);
            let mut store = Store::load()?;
            store.cache_models(&provider, models);
            store.save()?;
            let mut out = Json::obj();
            out.set("cached", Json::Num(count as f64));
            Ok(out)
        }

        ("session", "new") => {
            let title = flags.get("title").cloned().unwrap_or_default();
            let mut store = Store::load()?;
            let id = store.create_session(&title, flags.get("agent").map(|s| s.as_str()))?;
            store.save()?;
            let mut out = Json::obj();
            out.set("id", Json::string(id));
            Ok(out)
        }
        ("session", "list") => {
            let store = Store::load()?;
            let mut out = Json::obj();
            out.set(
                "sessions",
                store.root.get("sessions").cloned().unwrap_or_else(|| Json::Arr(Vec::new())),
            );
            out.set(
                "active_session",
                store.root.get("active_session").cloned().unwrap_or(Json::Null),
            );
            Ok(out)
        }
        ("session", "switch") => {
            let id = require(&flags, "id")?;
            let mut store = Store::load()?;
            if !store.session_exists(&id) {
                return Err(format!("session '{id}' does not exist"));
            }
            store.root.set("active_session", Json::string(&id));
            store.save()?;
            Ok(Json::obj())
        }
        ("session", "delete") => {
            let id = require(&flags, "id")?;
            let mut store = Store::load()?;
            store.delete_session(&id)?;
            store.save()?;
            Ok(Json::obj())
        }
        ("session", "append") => {
            let id = require(&flags, "id")?;
            let role = require(&flags, "role")?;
            let tokens = flags
                .get("tokens")
                .map(|t| t.parse::<u64>().map_err(|_| "--tokens must be a number".to_string()))
                .transpose()?
                .unwrap_or(0);
            // Content comes in on stdin to survive newlines and shell quoting.
            let content = match flags.get("content") {
                Some(inline) => inline.clone(),
                None => {
                    let mut buf = String::new();
                    io::stdin()
                        .read_to_string(&mut buf)
                        .map_err(|e| format!("cannot read stdin: {e}"))?;
                    buf
                }
            };
            let mut store = Store::load()?;
            store.append_message(&id, &role, &content, tokens)?;
            store.save()?;
            Ok(Json::obj())
        }
        ("session", "transcript") => {
            let id = require(&flags, "id")?;
            let limit = flags
                .get("limit")
                .map(|t| t.parse::<usize>().map_err(|_| "--limit must be a number".to_string()))
                .transpose()?
                .unwrap_or(0);
            let store = Store::load()?;
            let mut out = Json::obj();
            out.set("messages", store.read_transcript(&id, limit)?);
            Ok(out)
        }

        ("agent", "create") => {
            let name = require(&flags, "name")?;
            let description = flags.get("description").cloned().unwrap_or_default();
            let instructions = match flags.get("instructions") {
                Some(inline) => inline.clone(),
                None if flag_bool(&flags, "stdin") => {
                    let mut buf = String::new();
                    io::stdin()
                        .read_to_string(&mut buf)
                        .map_err(|e| format!("cannot read stdin: {e}"))?;
                    buf
                }
                None => String::new(),
            };
            let mut store = Store::load()?;
            let id = store.create_agent(&name, &description, &instructions)?;
            store.save()?;
            let mut out = Json::obj();
            out.set("id", Json::string(id));
            out.set("name", Json::string(name));
            Ok(out)
        }
        ("agent", "list") => {
            let store = Store::load()?;
            let mut out = Json::obj();
            out.set(
                "agents",
                store.root.get("agents").cloned().unwrap_or_else(|| Json::Arr(Vec::new())),
            );
            out.set(
                "active_agent",
                store.root.get("active_agent").cloned().unwrap_or(Json::Null),
            );
            Ok(out)
        }
        ("agent", "switch") => {
            let id = require(&flags, "id")?;
            let mut store = Store::load()?;
            let resolved = store
                .resolve_agent(&id)
                .ok_or_else(|| format!("agent '{id}' does not exist"))?;
            store.root.set("active_agent", Json::string(&resolved));
            store.save()?;
            let mut out = Json::obj();
            out.set("id", Json::string(resolved));
            Ok(out)
        }
        ("agent", "delete") => {
            let id = require(&flags, "id")?;
            let mut store = Store::load()?;
            store.delete_agent(&id)?;
            store.save()?;
            Ok(Json::obj())
        }

        ("usage", "add") => {
            let total = flags
                .get("tokens")
                .map(|t| t.parse::<u64>().map_err(|_| "--tokens must be a number".to_string()))
                .transpose()?
                .unwrap_or(0);
            let prompt = flags
                .get("prompt")
                .map(|t| t.parse::<u64>().map_err(|_| "--prompt must be a number".to_string()))
                .transpose()?
                .unwrap_or(0);
            let completion = flags
                .get("completion")
                .map(|t| t.parse::<u64>().map_err(|_| "--completion must be a number".to_string()))
                .transpose()?
                .unwrap_or(0);
            let mut store = Store::load()?;
            store.add_usage(total, prompt, completion);
            store.save()?;
            let mut out = Json::obj();
            out.set("usage", store.root.get("usage").cloned().unwrap_or_else(Json::obj));
            Ok(out)
        }
        ("usage", "show") => {
            let store = Store::load()?;
            let mut out = Json::obj();
            out.set("usage", store.root.get("usage").cloned().unwrap_or_else(Json::obj));
            Ok(out)
        }

        ("setup", "complete") => {
            let mut store = Store::load()?;
            if !store.has_account() {
                return Err("cannot complete setup before an account exists".into());
            }
            store.root.set("setup_complete", Json::Bool(true));
            store.root.set("setup_completed_at", Json::Num(now_secs() as f64));
            store.save()?;
            Ok(Json::obj())
        }
        ("setup", "status") => {
            let store = Store::load()?;
            let mut out = Json::obj();
            out.set(
                "setup_complete",
                Json::Bool(
                    store
                        .root
                        .get("setup_complete")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false),
                ),
            );
            out.set("account_exists", Json::Bool(store.has_account()));
            out.set("username", Json::string(store.username().unwrap_or("")));
            out.set("providers", store.providers_public());
            Ok(out)
        }

        ("token", "mint") => {
            let data_key = data_key_from(&flags)?;
            let issued = now_secs();
            let mut out = Json::obj();
            out.set("token", Json::string(mint_gateway_token(&data_key, issued)));
            out.set("issued_at", Json::Num(issued as f64));
            Ok(out)
        }

        (g, a) if !g.is_empty() && a.is_empty() => {
            Err(format!("'{g}' needs an action\n\n{}", USAGE.trim()))
        }
        (g, a) => Err(format!("unknown command '{g} {a}'\n\n{}", USAGE.trim())),
    }
}

/* ------------------------------------------------------------------ *
 * Flag parsing
 * ------------------------------------------------------------------ */

type Flags = BTreeMap<String, String>;

/// Parse `--key value` and `--flag` pairs. Values are never read from argv for
/// secrets when the caller passes `--password-stdin` style sentinels; see
/// `require_secret`.
fn parse_flags(args: &[String]) -> store::Result<Flags> {
    let mut flags = Flags::new();
    let mut i = 0;
    while i < args.len() {
        let arg = &args[i];
        if let Some(name) = arg.strip_prefix("--") {
            if name.is_empty() {
                return Err("encountered a bare '--'".into());
            }
            if let Some((key, value)) = name.split_once('=') {
                flags.insert(key.to_string(), value.to_string());
                i += 1;
                continue;
            }
            let next = args.get(i + 1);
            match next {
                Some(value) if !value.starts_with("--") => {
                    flags.insert(name.to_string(), value.clone());
                    i += 2;
                }
                _ => {
                    flags.insert(name.to_string(), "true".to_string());
                    i += 1;
                }
            }
        } else {
            i += 1;
        }
    }
    Ok(flags)
}

fn require(flags: &Flags, key: &str) -> store::Result<String> {
    flags
        .get(key)
        .filter(|v| !v.trim().is_empty())
        .cloned()
        .ok_or_else(|| format!("--{key} is required"))
}

fn flag_bool(flags: &Flags, key: &str) -> bool {
    matches!(flags.get(key).map(|s| s.as_str()), Some("true") | Some("1") | Some("yes"))
}

/// Read a secret. `--<key> -` or `--<key>-stdin` pulls one line from stdin so
/// passwords and API keys never appear in the process table.
fn require_secret(flags: &Flags, key: &str) -> store::Result<String> {
    let stdin_key = format!("{key}-stdin");
    let wants_stdin = flag_bool(flags, &stdin_key)
        || flags.get(key).map(|v| v.as_str()) == Some("-");
    if wants_stdin {
        let mut buf = String::new();
        io::stdin()
            .read_line(&mut buf)
            .map_err(|e| format!("cannot read --{key} from stdin: {e}"))?;
        let value = buf.trim_end_matches(['\r', '\n']).to_string();
        if value.is_empty() {
            return Err(format!("--{key} was empty on stdin"));
        }
        return Ok(value);
    }
    require(flags, key)
}

/// The data key may be passed directly (gateway holds it in memory after login)
/// or derived on the spot from a password.
fn data_key_from(flags: &Flags) -> store::Result<[u8; 32]> {
    if let Some(hex) = flags.get("data-key") {
        let bytes = crypto::from_hex(hex).ok_or_else(|| "--data-key is not valid hex".to_string())?;
        if bytes.len() != 32 {
            return Err("--data-key must be 32 bytes of hex".into());
        }
        let mut key = [0u8; 32];
        key.copy_from_slice(&bytes);
        return Ok(key);
    }
    let password = require_secret(flags, "password")?;
    let store = Store::load()?;
    store.unlock(&password)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_space_and_equals_forms() {
        let args: Vec<String> = ["provider", "enable", "--id", "groq", "--key=sk-1", "--force"]
            .iter()
            .map(|s| s.to_string())
            .collect();
        let flags = parse_flags(&args).unwrap();
        assert_eq!(flags.get("id").unwrap(), "groq");
        assert_eq!(flags.get("key").unwrap(), "sk-1");
        assert!(flag_bool(&flags, "force"));
    }

    #[test]
    fn missing_required_flag_is_reported_by_name() {
        let flags = parse_flags(&[]).unwrap();
        let err = require(&flags, "id").unwrap_err();
        assert!(err.contains("--id"));
    }

    #[test]
    fn blank_values_count_as_missing() {
        let args: Vec<String> = ["--id", "   "].iter().map(|s| s.to_string()).collect();
        let flags = parse_flags(&args).unwrap();
        assert!(require(&flags, "id").is_err());
    }
}
