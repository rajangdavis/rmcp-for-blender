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
fn read_reply(stream: &mut TcpStream) -> Option<serde_json::Value> {
    let mut buf: Vec<u8> = Vec::new();
    let mut chunk = [0u8; 8192];
    loop {
        let n = match stream.read(&mut chunk) {
            Ok(0) | Err(_) => break,
            Ok(n) => n,
        };
        buf.extend_from_slice(&chunk[..n]);
        if let Ok(value) = serde_json::from_slice::<serde_json::Value>(&buf) {
            return Some(value);
        }
    }
    serde_json::from_slice::<serde_json::Value>(&buf).ok()
}

/// Send one command to the addon and return its reply as JSON text.
///
/// The empty string means "no reply": the addon is not listening, the kept
/// connection died, or the reply never parsed. A command that was written is
/// not retried on a new connection, so a command runs at most once.
pub fn blender_call(host: impl AsRef<str>, port: i64, request: impl AsRef<str>) -> String {
    let request = request.as_ref();
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
