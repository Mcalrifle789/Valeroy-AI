//! Minimal JSON reader/writer for the Valeroy core.
//!
//! Only what the state store needs: objects, arrays, strings, numbers, bools,
//! null. No serde dependency so the core builds on a clean machine.

use std::collections::BTreeMap;
use std::fmt::Write as _;

#[derive(Debug, Clone, PartialEq)]
pub enum Json {
    Null,
    Bool(bool),
    Num(f64),
    Str(String),
    Arr(Vec<Json>),
    Obj(BTreeMap<String, Json>),
}

impl Json {
    pub fn obj() -> Json {
        Json::Obj(BTreeMap::new())
    }

    pub fn get(&self, key: &str) -> Option<&Json> {
        match self {
            Json::Obj(m) => m.get(key),
            _ => None,
        }
    }

    pub fn set(&mut self, key: &str, value: Json) {
        if let Json::Obj(m) = self {
            m.insert(key.to_string(), value);
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Json::Str(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_f64(&self) -> Option<f64> {
        match self {
            Json::Num(n) => Some(*n),
            _ => None,
        }
    }

    pub fn as_u64(&self) -> Option<u64> {
        self.as_f64().map(|n| n as u64)
    }

    pub fn as_bool(&self) -> Option<bool> {
        match self {
            Json::Bool(b) => Some(*b),
            _ => None,
        }
    }

    pub fn as_array(&self) -> Option<&Vec<Json>> {
        match self {
            Json::Arr(a) => Some(a),
            _ => None,
        }
    }

    pub fn as_array_mut(&mut self) -> Option<&mut Vec<Json>> {
        match self {
            Json::Arr(a) => Some(a),
            _ => None,
        }
    }

    pub fn str_field(&self, key: &str) -> Option<&str> {
        self.get(key).and_then(|v| v.as_str())
    }

    pub fn string(s: impl Into<String>) -> Json {
        Json::Str(s.into())
    }

    /// Serialize to compact JSON text.
    pub fn dump(&self) -> String {
        let mut out = String::new();
        self.write_into(&mut out);
        out
    }

    fn write_into(&self, out: &mut String) {
        match self {
            Json::Null => out.push_str("null"),
            Json::Bool(true) => out.push_str("true"),
            Json::Bool(false) => out.push_str("false"),
            Json::Num(n) => {
                if n.is_finite() {
                    if (n.fract()).abs() < f64::EPSILON && n.abs() < 9e15 {
                        let _ = write!(out, "{}", *n as i64);
                    } else {
                        let _ = write!(out, "{}", n);
                    }
                } else {
                    out.push_str("null");
                }
            }
            Json::Str(s) => write_escaped(s, out),
            Json::Arr(items) => {
                out.push('[');
                for (i, item) in items.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    item.write_into(out);
                }
                out.push(']');
            }
            Json::Obj(map) => {
                out.push('{');
                for (i, (key, value)) in map.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    write_escaped(key, out);
                    out.push(':');
                    value.write_into(out);
                }
                out.push('}');
            }
        }
    }

    /// Parse JSON text. Returns None on malformed input.
    pub fn parse(text: &str) -> Option<Json> {
        let bytes = text.as_bytes();
        let mut pos = 0usize;
        let value = parse_value(bytes, &mut pos, 0)?;
        skip_ws(bytes, &mut pos);
        if pos != bytes.len() {
            return None;
        }
        Some(value)
    }
}

fn write_escaped(s: &str, out: &mut String) {
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

fn skip_ws(b: &[u8], pos: &mut usize) {
    while *pos < b.len() && matches!(b[*pos], b' ' | b'\t' | b'\n' | b'\r') {
        *pos += 1;
    }
}

const MAX_DEPTH: usize = 64;

fn parse_value(b: &[u8], pos: &mut usize, depth: usize) -> Option<Json> {
    if depth > MAX_DEPTH {
        return None;
    }
    skip_ws(b, pos);
    if *pos >= b.len() {
        return None;
    }
    match b[*pos] {
        b'{' => parse_object(b, pos, depth),
        b'[' => parse_array(b, pos, depth),
        b'"' => parse_string(b, pos).map(Json::Str),
        b't' => expect(b, pos, b"true").map(|_| Json::Bool(true)),
        b'f' => expect(b, pos, b"false").map(|_| Json::Bool(false)),
        b'n' => expect(b, pos, b"null").map(|_| Json::Null),
        _ => parse_number(b, pos),
    }
}

fn expect(b: &[u8], pos: &mut usize, lit: &[u8]) -> Option<()> {
    if b.len() - *pos >= lit.len() && &b[*pos..*pos + lit.len()] == lit {
        *pos += lit.len();
        Some(())
    } else {
        None
    }
}

fn parse_object(b: &[u8], pos: &mut usize, depth: usize) -> Option<Json> {
    *pos += 1; // '{'
    let mut map = BTreeMap::new();
    skip_ws(b, pos);
    if *pos < b.len() && b[*pos] == b'}' {
        *pos += 1;
        return Some(Json::Obj(map));
    }
    loop {
        skip_ws(b, pos);
        let key = parse_string(b, pos)?;
        skip_ws(b, pos);
        if *pos >= b.len() || b[*pos] != b':' {
            return None;
        }
        *pos += 1;
        let value = parse_value(b, pos, depth + 1)?;
        map.insert(key, value);
        skip_ws(b, pos);
        if *pos >= b.len() {
            return None;
        }
        match b[*pos] {
            b',' => {
                *pos += 1;
            }
            b'}' => {
                *pos += 1;
                return Some(Json::Obj(map));
            }
            _ => return None,
        }
    }
}

fn parse_array(b: &[u8], pos: &mut usize, depth: usize) -> Option<Json> {
    *pos += 1; // '['
    let mut items = Vec::new();
    skip_ws(b, pos);
    if *pos < b.len() && b[*pos] == b']' {
        *pos += 1;
        return Some(Json::Arr(items));
    }
    loop {
        let value = parse_value(b, pos, depth + 1)?;
        items.push(value);
        skip_ws(b, pos);
        if *pos >= b.len() {
            return None;
        }
        match b[*pos] {
            b',' => {
                *pos += 1;
            }
            b']' => {
                *pos += 1;
                return Some(Json::Arr(items));
            }
            _ => return None,
        }
    }
}

fn parse_string(b: &[u8], pos: &mut usize) -> Option<String> {
    if *pos >= b.len() || b[*pos] != b'"' {
        return None;
    }
    *pos += 1;
    let mut out = String::new();
    while *pos < b.len() {
        match b[*pos] {
            b'"' => {
                *pos += 1;
                return Some(out);
            }
            b'\\' => {
                *pos += 1;
                if *pos >= b.len() {
                    return None;
                }
                let esc = b[*pos];
                *pos += 1;
                match esc {
                    b'"' => out.push('"'),
                    b'\\' => out.push('\\'),
                    b'/' => out.push('/'),
                    b'b' => out.push('\u{08}'),
                    b'f' => out.push('\u{0c}'),
                    b'n' => out.push('\n'),
                    b'r' => out.push('\r'),
                    b't' => out.push('\t'),
                    b'u' => {
                        let hi = parse_hex4(b, pos)?;
                        let code = if (0xD800..0xDC00).contains(&hi) {
                            // surrogate pair
                            if b.len() - *pos >= 6 && b[*pos] == b'\\' && b[*pos + 1] == b'u' {
                                *pos += 2;
                                let lo = parse_hex4(b, pos)?;
                                if (0xDC00..0xE000).contains(&lo) {
                                    0x10000 + ((hi - 0xD800) << 10) + (lo - 0xDC00)
                                } else {
                                    0xFFFD
                                }
                            } else {
                                0xFFFD
                            }
                        } else if (0xDC00..0xE000).contains(&hi) {
                            0xFFFD
                        } else {
                            hi
                        };
                        out.push(char::from_u32(code).unwrap_or('\u{FFFD}'));
                    }
                    _ => return None,
                }
            }
            _ => {
                // Collect a run of raw bytes and decode as UTF-8.
                let start = *pos;
                while *pos < b.len() && b[*pos] != b'"' && b[*pos] != b'\\' {
                    *pos += 1;
                }
                out.push_str(std::str::from_utf8(&b[start..*pos]).ok()?);
            }
        }
    }
    None
}

fn parse_hex4(b: &[u8], pos: &mut usize) -> Option<u32> {
    if b.len() - *pos < 4 {
        return None;
    }
    let mut code = 0u32;
    for _ in 0..4 {
        let c = b[*pos];
        *pos += 1;
        let nib = match c {
            b'0'..=b'9' => c - b'0',
            b'a'..=b'f' => c - b'a' + 10,
            b'A'..=b'F' => c - b'A' + 10,
            _ => return None,
        };
        code = (code << 4) | nib as u32;
    }
    Some(code)
}

fn parse_number(b: &[u8], pos: &mut usize) -> Option<Json> {
    let start = *pos;
    if *pos < b.len() && (b[*pos] == b'-' || b[*pos] == b'+') {
        *pos += 1;
    }
    let mut digits = false;
    while *pos < b.len() && b[*pos].is_ascii_digit() {
        *pos += 1;
        digits = true;
    }
    if *pos < b.len() && b[*pos] == b'.' {
        *pos += 1;
        while *pos < b.len() && b[*pos].is_ascii_digit() {
            *pos += 1;
            digits = true;
        }
    }
    if !digits {
        return None;
    }
    if *pos < b.len() && (b[*pos] == b'e' || b[*pos] == b'E') {
        *pos += 1;
        if *pos < b.len() && (b[*pos] == b'-' || b[*pos] == b'+') {
            *pos += 1;
        }
        while *pos < b.len() && b[*pos].is_ascii_digit() {
            *pos += 1;
        }
    }
    std::str::from_utf8(&b[start..*pos])
        .ok()?
        .parse::<f64>()
        .ok()
        .map(Json::Num)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrips_nested_structures() {
        let text = r#"{"a":[1,2,{"b":"c"}],"d":true,"e":null,"f":1.5}"#;
        let parsed = Json::parse(text).expect("parses");
        assert_eq!(parsed.dump(), text);
    }

    #[test]
    fn escapes_and_unescapes() {
        let original = Json::Str("line\nquote\"tab\tdone".into());
        let text = original.dump();
        assert_eq!(Json::parse(&text).unwrap(), original);
    }

    #[test]
    fn handles_unicode_escape() {
        let parsed = Json::parse(r#""Aé""#).unwrap();
        assert_eq!(parsed.as_str().unwrap(), "Aé");
    }

    #[test]
    fn handles_surrogate_pair() {
        let parsed = Json::parse(r#""😀""#).unwrap();
        assert_eq!(parsed.as_str().unwrap(), "😀");
    }

    #[test]
    fn rejects_malformed() {
        assert!(Json::parse("{").is_none());
        assert!(Json::parse("{\"a\":}").is_none());
        assert!(Json::parse("[1,2").is_none());
        assert!(Json::parse("tru").is_none());
        assert!(Json::parse("{} trailing").is_none());
    }

    #[test]
    fn integers_do_not_gain_decimal_point() {
        assert_eq!(Json::Num(42.0).dump(), "42");
    }
}
