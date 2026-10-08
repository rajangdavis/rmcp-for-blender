//! The Blender addon's socket bridge: one JSON request per command, one JSON
//! reply, on one TCP connection kept between calls.
//!
//! The addon's protocol is self-delimiting JSON with no framing, so a reply is
//! read until it parses. The connection is kept, as the Python MCP server keeps
//! one; it is dropped when its write fails or a reply cannot be parsed, and a
//! request that was written is never sent twice.

use std::io::{Read, Write};
use std::net::TcpStream;
use std::sync::{Mutex, OnceLock};

static CONN: OnceLock<Mutex<Option<TcpStream>>> = OnceLock::new();

/// Read one complete JSON reply; None when the peer closes, errors, or sends
/// something that never parses.
///
/// The bytes are scanned once as they arrive, tracking string and bracket
/// depth, and parsed a single time when the top-level value closes. Parsing the
/// whole buffer after every chunk cost about n * n / chunk bytes of parsing for
/// an n-byte reply, which dominated replies carrying base64 images.
fn read_reply(stream: &mut TcpStream) -> Option<serde_json::Value> {
    let mut buf: Vec<u8> = Vec::new();
    let mut chunk = [0u8; 65536];
    let mut depth: usize = 0;
    let mut started = false;
    let mut in_string = false;
    let mut escaped = false;
    loop {
        let n = match stream.read(&mut chunk) {
            Ok(0) | Err(_) => break,
            Ok(n) => n,
        };
        let start = buf.len();
        buf.extend_from_slice(&chunk[..n]);
        for i in start..buf.len() {
            let b = buf[i];
            if in_string {
                if escaped {
                    escaped = false;
                } else if b == b'\\' {
                    escaped = true;
                } else if b == b'"' {
                    in_string = false;
                }
                continue;
            }
            match b {
                b'"' => in_string = true,
                b'{' | b'[' => {
                    depth += 1;
                    started = true;
                }
                b'}' | b']' => {
                    depth = depth.saturating_sub(1);
                    if started && depth == 0 {
                        return serde_json::from_slice::<serde_json::Value>(&buf[..=i]).ok();
                    }
                }
                _ => {}
            }
        }
    }
    serde_json::from_slice::<serde_json::Value>(&buf).ok()
}

/// The bridge token, read once from BLENDER_BRIDGE_TOKEN. It is read here
/// rather than declared as a DSL setting because a secret setting may only be
/// handed to a rust_fn directly, and every caller of blender_call is a helper.
fn bridge_token() -> &'static str {
    static TOKEN: OnceLock<String> = OnceLock::new();
    TOKEN.get_or_init(|| std::env::var("BLENDER_BRIDGE_TOKEN").unwrap_or_default().trim().to_string())
}

/// Add the bridge token to a request. The addon runs what it is sent with
/// exec(), so it refuses any request whose "token" does not match its own;
/// this server is meant to be the only client that knows it. None when the
/// request is not a JSON object or there is no token to send, so an unset
/// token fails closed instead of sending an unauthenticated request.
fn with_token(request: &str, token: &str) -> Option<String> {
    if token.is_empty() {
        return None;
    }
    let mut value: serde_json::Value = serde_json::from_str(request).ok()?;
    value
        .as_object_mut()?
        .insert("token".to_string(), serde_json::Value::String(token.to_string()));
    Some(value.to_string())
}

/// Send one command to the addon and return its reply as JSON text.
///
/// The empty string means "no reply": the addon is not listening, the kept
/// connection died, or the reply never parsed. A command that was written is
/// not retried on a new connection, so a command runs at most once. A request
/// that cannot carry the token is never sent.
pub fn blender_call(host: impl AsRef<str>, port: i64, request: impl AsRef<str>) -> String {
    let request = match with_token(request.as_ref(), bridge_token()) {
        Some(request) => request,
        None => return String::new(),
    };
    let request = request.as_str();
    let cell = CONN.get_or_init(|| Mutex::new(None));
    let mut guard = match cell.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    };

    let mut out: Option<serde_json::Value> = None;
    let mut sent = false;
    let mut dead = false;

    if let Some(stream) = guard.as_mut() {
        let _ = stream.set_read_timeout(Some(std::time::Duration::from_secs(30)));
        if stream.write_all(request.as_bytes()).is_ok() {
            sent = true;
            out = read_reply(stream);
        } else {
            dead = true;
        }
    }
    if dead {
        *guard = None;
    }

    if out.is_none() && !sent {
        if let Ok(mut stream) = TcpStream::connect(format!("{}:{}", host.as_ref(), port)) {
            let _ = stream.set_read_timeout(Some(std::time::Duration::from_secs(30)));
            if stream.write_all(request.as_bytes()).is_ok() {
                out = read_reply(&mut stream);
                *guard = Some(stream);
            }
        }
    }
    if out.is_none() {
        *guard = None;
    }

    out.map(|value| value.to_string()).unwrap_or_default()
}
