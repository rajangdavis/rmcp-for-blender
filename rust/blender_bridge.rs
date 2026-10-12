//! The Blender addon's socket bridge: one JSON request per command, one JSON
//! reply, on one TCP connection kept between calls.
//!
//! The addon's protocol is self-delimiting JSON with no framing, so a reply is
//! read until it parses. The connection is kept, as the Python MCP server keeps
//! one; it is dropped when its write fails or a reply cannot be parsed, and a
//! request that was written is never sent twice.
//!
//! Every call waits under its own read timeout. A timeout is reported as its own
//! JSON result (`{"status":"timeout", ...}`), not the empty string, because a
//! timed-out command may still be running in Blender: the caller has to verify
//! before retrying, and it must not be told the bridge was unreachable when it
//! was merely slow. The empty string still means "no reply" -- unreachable or
//! closed -- so the two failures stay distinguishable.

use std::io::{ErrorKind, Read, Write};
use std::net::TcpStream;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

/// How long a call waits for its reply when the caller does not say. Long
/// operations pass their own: a Cycles still takes 18-27 s, and an animation or
/// an import can take minutes.
const DEFAULT_TIMEOUT_SECS: i64 = 60;

/// How long the follow-up ping waits when a call times out. It answers at once
/// when Blender is idle, and does not answer while a command still holds the
/// main thread, which is exactly what the ping is there to learn.
const PING_TIMEOUT_SECS: u64 = 5;

static CONN: OnceLock<Mutex<Option<TcpStream>>> = OnceLock::new();

/// What reading one reply ended in. TimedOut is kept apart from Closed: a
/// timeout leaves a command that was written and may still have run, while a
/// closed or unparsable connection means the reply is simply gone.
enum ReadOutcome {
    Reply(serde_json::Value),
    TimedOut,
    Closed,
}

/// Read one complete JSON reply; Closed when the peer closes, errors, or sends
/// something that never parses; TimedOut when the read blocks past the stream's
/// read timeout with the reply still incomplete.
///
/// The bytes are scanned once as they arrive, tracking string and bracket
/// depth, and parsed a single time when the top-level value closes. Parsing the
/// whole buffer after every chunk cost about n * n / chunk bytes of parsing for
/// an n-byte reply, which dominated replies carrying base64 images.
fn read_reply(stream: &mut TcpStream) -> ReadOutcome {
    let mut buf: Vec<u8> = Vec::new();
    let mut chunk = [0u8; 65536];
    let mut depth: usize = 0;
    let mut started = false;
    let mut in_string = false;
    let mut escaped = false;
    loop {
        let n = match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(n) => n,
            Err(e) if e.kind() == ErrorKind::WouldBlock || e.kind() == ErrorKind::TimedOut => {
                return ReadOutcome::TimedOut
            }
            Err(_) => break,
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
                        return match serde_json::from_slice::<serde_json::Value>(&buf[..=i]) {
                            Ok(value) => ReadOutcome::Reply(value),
                            Err(_) => ReadOutcome::Closed,
                        };
                    }
                }
                _ => {}
            }
        }
    }
    match serde_json::from_slice::<serde_json::Value>(&buf) {
        Ok(value) => ReadOutcome::Reply(value),
        Err(_) => ReadOutcome::Closed,
    }
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

/// The synthetic reply a timed-out call returns. It is JSON text with a status
/// of its own, so a caller that already branches on `/status` sees "timeout"
/// instead of "success", reads `/message`, and knows the command may have run.
/// `answered` says whether a fresh-connection ping reached Blender afterwards.
fn timeout_reply(timeout_secs: i64, answered: bool) -> String {
    let message = if answered {
        format!(
            "timed out after {} s -- the operation may still have run in Blender; verify before retrying (the command was NOT resent). A follow-up ping answered, so Blender is reachable",
            timeout_secs
        )
    } else {
        format!(
            "timed out after {} s -- the operation may still have run in Blender; verify before retrying (the command was NOT resent). A follow-up ping did not answer: Blender is busy or unreachable",
            timeout_secs
        )
    };
    let mut object = serde_json::Map::new();
    object.insert("status".to_string(), serde_json::Value::String("timeout".to_string()));
    object.insert("message".to_string(), serde_json::Value::String(message));
    object.insert("blender_answered".to_string(), serde_json::Value::Bool(answered));
    serde_json::Value::Object(object).to_string()
}

/// Ask the addon, on a fresh connection, whether it is still there. A new,
/// read-only `ping`: it is never a resend of the command that timed out. It
/// carries the same token as every other request.
fn ping_after_timeout(host: &str, port: i64) -> bool {
    let request = match with_token("{\"type\":\"ping\"}", bridge_token()) {
        Some(request) => request,
        None => return false,
    };
    let mut stream = match TcpStream::connect(format!("{}:{}", host, port)) {
        Ok(stream) => stream,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(PING_TIMEOUT_SECS)));
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    matches!(
        read_reply(&mut stream),
        ReadOutcome::Reply(value) if value.get("status").and_then(|s| s.as_str()) == Some("success")
    )
}

/// Send one command to the addon and return its reply as JSON text, waiting the
/// default timeout. Kept as the three-argument call every existing helper uses.
pub fn blender_call(host: impl AsRef<str>, port: i64, request: impl AsRef<str>) -> String {
    blender_call_timeout(host, port, request, DEFAULT_TIMEOUT_SECS)
}

/// Send one command to the addon and return its reply as JSON text, waiting up
/// to `timeout_secs` for it (clamped to 1..86400).
///
/// The empty string means "no reply": the addon is not listening, the kept
/// connection died, or the reply never parsed. A timeout returns a distinct
/// JSON object whose status is "timeout" instead, so "may still be running" is
/// not confused with "unreachable". A command that was written is not retried
/// on a new connection, so a command runs at most once; the follow-up ping is a
/// new request, not a resend. A request that cannot carry the token is never
/// sent.
pub fn blender_call_timeout(
    host: impl AsRef<str>,
    port: i64,
    request: impl AsRef<str>,
    timeout_secs: i64,
) -> String {
    let host = host.as_ref();
    let timeout_secs = timeout_secs.clamp(1, 86_400);
    let timeout = Duration::from_secs(timeout_secs as u64);
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

    let started = Instant::now();
    let mut out: Option<serde_json::Value> = None;
    let mut sent = false;
    let mut timed_out = false;
    let mut dead = false;

    if let Some(stream) = guard.as_mut() {
        let _ = stream.set_read_timeout(Some(timeout));
        if stream.write_all(request.as_bytes()).is_ok() {
            sent = true;
            match read_reply(stream) {
                ReadOutcome::Reply(value) => out = Some(value),
                ReadOutcome::TimedOut => timed_out = true,
                ReadOutcome::Closed => {}
            }
        } else {
            dead = true;
        }
    }
    if dead {
        *guard = None;
    }

    if out.is_none() && !sent {
        if let Ok(mut stream) = TcpStream::connect(format!("{}:{}", host, port)) {
            let _ = stream.set_read_timeout(Some(timeout));
            if stream.write_all(request.as_bytes()).is_ok() {
                match read_reply(&mut stream) {
                    ReadOutcome::Reply(value) => {
                        out = Some(value);
                        *guard = Some(stream);
                    }
                    ReadOutcome::TimedOut => timed_out = true,
                    ReadOutcome::Closed => {}
                }
            }
        }
    }
    if out.is_none() {
        *guard = None;
    }

    // A timeout can mean the command is still running on Blender's main thread.
    // Ask, on a fresh connection, whether the addon answers at all; a ping is a
    // new request, never a resend of the one that timed out.
    let answered = timed_out && ping_after_timeout(host, port);

    let outcome = if out.is_some() {
        "reply"
    } else if timed_out {
        "timeout"
    } else {
        "no-reply"
    };
    eprintln!(
        "blender_call {}:{} {} in {} ms ({} bytes sent, timeout {} s, blender_answered={})",
        host,
        port,
        outcome,
        started.elapsed().as_millis(),
        request.len(),
        timeout_secs,
        answered
    );

    if let Some(value) = out {
        value.to_string()
    } else if timed_out {
        timeout_reply(timeout_secs, answered)
    } else {
        String::new()
    }
}
