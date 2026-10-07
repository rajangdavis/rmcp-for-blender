//! Hand-written generation helpers for blender.rmcp.rb. The DSL has no sleep
//! and cannot hand Hyper3D Rodin the image bytes it wants, so these live here,
//! declared with rust_file / rust_fn (from: :blender_gen); rustc checks them as
//! a file rather than as embedded strings.

/// Sleep for `ms` milliseconds, clamped to ten minutes. Returns `ms` so the
/// call has a value for the DSL to read.
pub async fn sleep_ms(ms: i64) -> i64 {
    tokio::time::sleep(std::time::Duration::from_millis(ms.clamp(0, 600_000) as u64)).await;
    ms
}

/// Read a local image as base64 for Hyper3D Rodin, whose main-site request
/// takes image bytes rather than a path. The empty string means the read failed.
pub fn gen_file_base64(path: impl AsRef<str>) -> String {
    use base64::Engine as _;
    match std::fs::read(path.as_ref()) {
        Ok(bytes) => base64::engine::general_purpose::STANDARD.encode(bytes),
        Err(_) => String::new(),
    }
}

/// The lower-case extension of an image path, for the multipart filename.
pub fn gen_path_suffix(path: impl AsRef<str>) -> String {
    std::path::Path::new(path.as_ref())
        .extension()
        .and_then(|ext| ext.to_str())
        .map(|ext| format!(".{}", ext.to_lowercase()))
        .unwrap_or_default()
}

/// Ruby's strip and Rust's trim() agree on the text this server handles (script
/// source, captured stdout, user-supplied names), and Rust's own trim keeps the
/// generated code idiomatic: a Ruby .strip otherwise compiles to an explicit-set
/// trim and earns a W-STR-STRIP-RUBY warning.
pub fn trim_text(text: impl AsRef<str>) -> String {
    text.as_ref().trim().to_string()
}
