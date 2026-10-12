//! Asset libraries for blender.rmcp.rb: Poly Haven, Sketchfab and Poly Pizza.
//!
//! Ported from the mcp-for-blender add-on's handlers, with one change of shape:
//! every network call happens here, in the server, and Blender only ever imports
//! files that are already on disk. So Blender needs no network access, and the
//! API keys stay in this server's environment, out of reach of agent code
//! running inside Blender:
//!
//!   BLENDERMCP_SKETCHFAB_API_KEY  (https://sketchfab.com/settings/password)
//!   BLENDERMCP_POLYPIZZA_API_KEY  (https://poly.pizza/settings/api)
//!
//! Poly Haven needs no key. asset_search answers with JSON text. asset_fetch
//! downloads one asset into a fresh folder under the directory it is handed
//! (blender.rmcp.rb resolves that under the write roots) and answers with a JSON
//! manifest for the import_asset entry point in python/mcp_scripts.py, which
//! deletes the folder once the files are packed into the .blend. Errors come
//! back as {"error": "..."} rather than a separate channel, because a rust_fn
//! returns one string.
//!
//! Declared with rust_file / rust_fn (from: :blender_assets); ureq and
//! serde_json come from bindings/json.rb.

use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::io::Read;
use std::path::{Component, Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant, SystemTime};

const POLYHAVEN_API: &str = "https://api.polyhaven.com";
const POLYHAVEN_SITE: &str = "https://polyhaven.com";
const SKETCHFAB_API: &str = "https://api.sketchfab.com/v3";
const POLYPIZZA_API: &str = "https://api.poly.pizza/v1.1";
const SKETCHFAB_KEY: &str = "BLENDERMCP_SKETCHFAB_API_KEY";
const POLYPIZZA_KEY: &str = "BLENDERMCP_POLYPIZZA_API_KEY";
/// Poly Haven serves its asset list with max-age=43200 and an ETag; the cache
/// matches that, and revalidates with If-None-Match once it lapses.
const CACHE_TTL: Duration = Duration::from_secs(12 * 60 * 60);
const CACHE_MAX: usize = 16;
/// A single download larger than this is refused (a 24k EXR is 2.4 GB).
const MAX_DOWNLOAD: u64 = 2 * 1024 * 1024 * 1024;
const MAX_JSON: u64 = 64 * 1024 * 1024;
/// Every download folder this module makes starts with this, and only such
/// folders are ever swept or deleted.
pub const DOWNLOAD_PREFIX: &str = "mcp-asset-";
/// A download folder older than this was left by an import that never finished.
const STALE_AFTER: Duration = Duration::from_secs(60 * 60);

// ---------- HTTP ----------

fn agent() -> &'static ureq::Agent {
    static AGENT: OnceLock<ureq::Agent> = OnceLock::new();
    AGENT.get_or_init(|| {
        ureq::AgentBuilder::new()
            .timeout_connect(Duration::from_secs(10))
            .timeout_read(Duration::from_secs(60))
            // Poly Haven asks integrations to identify themselves.
            .user_agent("blender.rmcp/0.2 (MCP server for Blender; asset port of blender-mcp)")
            .build()
    })
}

/// A failed request: the HTTP status (with Retry-After when sent), or why
/// there was no response at all.
enum Http {
    Status(u16, Option<String>),
    Other(String),
}

impl Http {
    fn text(&self, what: &str) -> String {
        match self {
            Http::Status(code, _) => format!("{what} failed with HTTP {code}"),
            Http::Other(why) => format!("{what} failed: {why}"),
        }
    }
}

fn request(url: &str, query: &[(&str, String)], headers: &[(&str, String)]) -> Result<ureq::Response, Http> {
    let mut req = agent().get(url);
    for (key, value) in query {
        req = req.query(key, value);
    }
    for (key, value) in headers {
        req = req.set(key, value);
    }
    match req.call() {
        Ok(resp) => Ok(resp),
        Err(ureq::Error::Status(code, resp)) => Err(Http::Status(code, resp.header("Retry-After").map(str::to_string))),
        Err(other) => Err(Http::Other(other.to_string())),
    }
}

fn read_json(resp: ureq::Response) -> Result<Value, Http> {
    let mut text = String::new();
    resp.into_reader()
        .take(MAX_JSON)
        .read_to_string(&mut text)
        .map_err(|e| Http::Other(format!("reading the reply: {e}")))?;
    serde_json::from_str(&text).map_err(|e| Http::Other(format!("the reply is not JSON: {e}")))
}

fn get_json(url: &str, query: &[(&str, String)], headers: &[(&str, String)]) -> Result<Value, Http> {
    read_json(request(url, query, headers)?)
}

/// Stream url to dest. Refuses anything over MAX_DOWNLOAD, and a body whose
/// length disagrees with the size the API published.
fn download(url: &str, headers: &[(&str, String)], dest: &Path, expected: Option<u64>) -> Result<u64, String> {
    let resp = request(url, &[], headers).map_err(|e| e.text("download"))?;
    save(resp, dest, expected)
}

/// Write a response body to dest, with download's limits.
fn save(resp: ureq::Response, dest: &Path, expected: Option<u64>) -> Result<u64, String> {
    let mut file = std::fs::File::create(dest).map_err(|e| format!("cannot create {}: {e}", dest.display()))?;
    let written = std::io::copy(&mut resp.into_reader().take(MAX_DOWNLOAD + 1), &mut file)
        .map_err(|e| format!("download of {} broke off: {e}", dest.display()))?;
    if written > MAX_DOWNLOAD {
        let _ = std::fs::remove_file(dest);
        return Err(format!("{} is larger than 2 GiB; pick a lower resolution", file_name(dest)));
    }
    if let Some(size) = expected {
        if size != written {
            let _ = std::fs::remove_file(dest);
            return Err(format!("{} was truncated: {written} of {size} bytes arrived", file_name(dest)));
        }
    }
    Ok(written)
}

fn file_name(path: &Path) -> String {
    path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default()
}

/// Percent-encode one path segment (RFC 3986 unreserved characters pass).
fn encode_segment(text: &str) -> String {
    let mut out = String::new();
    for byte in text.bytes() {
        if byte.is_ascii_alphanumeric() || b"-_.~".contains(&byte) {
            out.push(byte as char);
        } else {
            out.push_str(&format!("%{byte:02X}"));
        }
    }
    out
}

fn key(env: &str, site: &str, url: &str) -> Result<String, String> {
    let value = std::env::var(env).unwrap_or_default().trim().to_string();
    if value.is_empty() {
        return Err(format!("{site} needs an API key: set {env} in this MCP server's environment (get one at {url}) and restart it"));
    }
    Ok(value)
}

fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().map(|f| f != 0.0).unwrap_or(true),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

fn error(message: impl Into<String>) -> String {
    json!({ "error": message.into() }).to_string()
}

// ---------- Poly Haven ----------

struct Entry {
    payload: Value,
    etag: Option<String>,
    fetched: Instant,
    used: u64,
}

fn cache() -> &'static Mutex<(HashMap<String, Entry>, u64)> {
    static CACHE: OnceLock<Mutex<(HashMap<String, Entry>, u64)>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new((HashMap::new(), 0)))
}

/// GET a Poly Haven endpoint. With cached, the payload is held for CACHE_TTL and
/// then revalidated with If-None-Match; eviction is least recently used, so the
/// asset list (fetched first, then only read) is not the first thing thrown out.
fn polyhaven_get(path: &str, query: &[(&str, String)], cached: bool) -> Result<Value, Http> {
    let key = format!("{path}?{}", query.iter().map(|(k, v)| format!("{k}={v}")).collect::<Vec<_>>().join("&"));
    let mut etag = None;
    if cached {
        let mut guard = cache().lock().unwrap_or_else(|p| p.into_inner());
        let (map, clock) = &mut *guard;
        *clock += 1;
        if let Some(entry) = map.get_mut(&key) {
            if entry.fetched.elapsed() < CACHE_TTL {
                entry.used = *clock;
                return Ok(entry.payload.clone());
            }
            etag = entry.etag.clone();
        }
    }
    let mut headers = Vec::new();
    if let Some(tag) = &etag {
        headers.push(("If-None-Match", tag.clone()));
    }
    let resp = request(&format!("{POLYHAVEN_API}/{path}"), query, &headers)?;
    if cached && resp.status() == 304 {
        let mut guard = cache().lock().unwrap_or_else(|p| p.into_inner());
        let (map, clock) = &mut *guard;
        if let Some(entry) = map.get_mut(&key) {
            entry.fetched = Instant::now();
            entry.used = *clock;
            return Ok(entry.payload.clone());
        }
    }
    let new_etag = resp.header("ETag").map(str::to_string);
    let payload = read_json(resp)?;
    if cached {
        let mut guard = cache().lock().unwrap_or_else(|p| p.into_inner());
        let (map, clock) = &mut *guard;
        if map.len() >= CACHE_MAX && !map.contains_key(&key) {
            if let Some(coldest) = map.iter().min_by_key(|(_, e)| e.used).map(|(k, _)| k.clone()) {
                map.remove(&coldest);
            }
        }
        map.insert(key, Entry { payload: payload.clone(), etag: new_etag, fetched: Instant::now(), used: *clock });
    }
    Ok(payload)
}

fn polyhaven_url(slug: &str) -> String {
    format!("{POLYHAVEN_SITE}/a/{}", encode_segment(slug))
}

fn valid_slug(slug: &str) -> bool {
    !slug.is_empty() && slug.len() <= 80 && slug.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

fn polyhaven_type(code: &Value) -> &'static str {
    match code.as_i64() {
        Some(0) => "hdris",
        Some(1) => "textures",
        Some(2) => "models",
        _ => "unknown",
    }
}

fn authors_of(record: &Value) -> Value {
    match record.get("authors") {
        Some(Value::Object(map)) => {
            let mut names: Vec<&String> = map.keys().collect();
            names.sort();
            json!(names)
        }
        Some(other @ Value::Array(_)) => other.clone(),
        _ => json!([]),
    }
}

/// Trim an /assets record to what is worth sending back: a whole page of
/// untrimmed records is most of what the model would then have to read.
fn summarize_asset(slug: &str, record: &Value) -> Value {
    let mut out = Map::new();
    out.insert("id".into(), json!(slug));
    out.insert("name".into(), record.get("name").cloned().filter(truthy).unwrap_or_else(|| json!(slug)));
    out.insert("type".into(), json!(polyhaven_type(record.get("type").unwrap_or(&Value::Null))));
    out.insert("url".into(), json!(polyhaven_url(slug)));
    out.insert("authors".into(), authors_of(record));
    out.insert("downloads".into(), record.get("download_count").cloned().unwrap_or(Value::Null));
    for field in ["description", "category", "tags", "attributes", "max_resolution", "thumbnail_url"] {
        if let Some(value) = record.get(field).filter(|v| truthy(v)) {
            out.insert(field.into(), value.clone());
        }
    }
    // Real-world size in millimetres, published for every texture: without it
    // nothing knows a wall texture is 1.8 m across.
    if let Some(dimensions) = record.get("dimensions").filter(|v| truthy(v)) {
        out.insert("dimensions_mm".into(), dimensions.clone());
    }
    Value::Object(out)
}

/// The fallback the API asks for when /search answers 503.
fn keyword_match(query: &str, assets: &Map<String, Value>) -> Vec<String> {
    let terms: Vec<&str> = query.split_whitespace().collect();
    let mut scored: Vec<(usize, i64, String)> = Vec::new();
    for (slug, record) in assets {
        let tags = record.get("tags").and_then(|t| t.as_array()).map(|a| {
            a.iter().filter_map(|t| t.as_str()).collect::<Vec<_>>().join(" ")
        }).unwrap_or_default();
        let haystack = format!(
            "{} {} {} {}",
            slug.replace('_', " "),
            record.get("name").and_then(|n| n.as_str()).unwrap_or(""),
            tags,
            record.get("category").map(|c| c.to_string()).unwrap_or_default()
        ).to_lowercase();
        let hits = terms.iter().filter(|t| haystack.contains(*t)).count();
        if hits > 0 {
            scored.push((hits, record.get("download_count").and_then(|d| d.as_i64()).unwrap_or(0), slug.clone()));
        }
    }
    scored.sort_by(|a, b| b.cmp(a));
    scored.into_iter().map(|(_, _, slug)| slug).collect()
}

fn polyhaven_search(asset_type: &str, category: &str, query: &str, min_size_m: f64, limit: i64) -> Result<Value, String> {
    let mut filters: Vec<(&str, String)> = Vec::new();
    if asset_type != "all" {
        filters.push(("type", asset_type.to_string()));
    }
    // `category` takes the taxonomy path ("Metal/Sheet & Corrugated") and is
    // inclusive; the legacy `categories` answers a path with an empty 200.
    if !category.is_empty() {
        filters.push(("category", category.to_string()));
    }
    let assets = match polyhaven_get("assets", &filters, true) {
        Ok(value) => value,
        Err(Http::Status(400, _)) => {
            return Err(format!(
                "Poly Haven did not recognise the category {category:?}. Categories are taxonomy paths such as \"Metal/Sheet & Corrugated\"; \
                 the list for each type is at {POLYHAVEN_API}/taxonomy/textures (or hdris, models)"
            ))
        }
        Err(e) => return Err(e.text("the Poly Haven asset list")),
    };
    let all = assets.as_object().ok_or("Poly Haven's asset list was not an object")?;
    let mut note: Option<String> = None;

    // Filtered here, since the API publishes a size but takes no filter on it.
    // Anything with no published size (every HDRI) cannot meet a floor.
    let floor_mm = min_size_m * 1000.0;
    let pool: Map<String, Value> = if min_size_m > 0.0 {
        let kept: Map<String, Value> = all
            .iter()
            .filter(|(_, record)| {
                record.get("dimensions").and_then(|d| d.as_array()).map(|d| {
                    d.iter().filter_map(|v| v.as_f64()).fold(0.0, f64::max) >= floor_mm
                }).unwrap_or(false)
            })
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();
        if !all.is_empty() && kept.is_empty() {
            note = Some(format!(
                "Nothing matching the other filters is {min_size_m}m or larger. Most textures are 1-4m, and HDRIs have no real-world size at all. Lower min_size_m or leave it out."
            ));
        }
        kept
    } else {
        all.clone()
    };

    let query = query.trim().to_lowercase();
    let ordered: Vec<String> = if !query.is_empty() {
        let mut params = vec![("q", query.clone())];
        if asset_type != "all" {
            params.push(("t", asset_type.to_string()));
        }
        // The array order is the ranking; /search knows nothing of the filters,
        // so the whole list is intersected with the filtered pool.
        let ranked: Vec<String> = match polyhaven_get("search", &params, true) {
            Ok(payload) => payload
                .get("results")
                .and_then(|r| r.as_array())
                .map(|a| a.iter().filter_map(|r| r.get("slug").and_then(|s| s.as_str()).map(str::to_string)).collect())
                .unwrap_or_default(),
            Err(Http::Status(429, retry)) => {
                return Err(format!(
                    "Poly Haven is rate limiting searches from this address.{}",
                    retry.map(|s| format!(" Retry in {s}s.")).unwrap_or_default()
                ))
            }
            Err(Http::Status(503, _)) => {
                note = Some("Poly Haven's semantic search was unavailable, so these are plain keyword matches and the ranking is weaker than usual.".into());
                keyword_match(&query, &pool)
            }
            Err(e) => return Err(e.text("the Poly Haven search")),
        };
        ranked.into_iter().filter(|slug| pool.contains_key(slug)).collect()
    } else {
        // Most downloaded first: the API's own order is by slug, which put 20
        // models ahead of every HDRI and texture.
        let mut slugs: Vec<&String> = pool.keys().collect();
        slugs.sort_by_key(|slug| std::cmp::Reverse(pool[*slug].get("download_count").and_then(|d| d.as_i64()).unwrap_or(0)));
        slugs.into_iter().cloned().collect()
    };
    let limit = limit.clamp(1, 50) as usize;
    let selected: Vec<Value> = ordered.iter().take(limit).map(|slug| summarize_asset(slug, &pool[slug])).collect();
    Ok(json!({
        "source": "polyhaven",
        "assets": selected,
        "total_count": ordered.len(),
        "returned_count": selected.len(),
        "query": if query.is_empty() { Value::Null } else { json!(query) },
        "note": note,
    }))
}

/// One asset's record: from the cached asset list when it is there, else /info.
fn polyhaven_record(slug: &str) -> Value {
    {
        let guard = cache().lock().unwrap_or_else(|p| p.into_inner());
        for entry in guard.0.values() {
            if let Some(record) = entry.payload.get(slug).filter(|r| r.get("name").is_some()) {
                return record.clone();
            }
        }
    }
    polyhaven_get(&format!("info/{}", encode_segment(slug)), &[], true).unwrap_or(Value::Null)
}

fn supported_formats(asset_type: &str) -> &'static [&'static str] {
    match asset_type {
        "hdris" => &["hdr", "exr"],
        "textures" => &["jpg", "png", "exr"],
        // blend is what the artist built; gltf is the fallback for a .blend
        // written by a newer Blender than the one running.
        "models" => &["blend", "gltf"],
        _ => &[],
    }
}

fn default_format(asset_type: &str) -> &'static str {
    match asset_type {
        "hdris" => "hdr",
        "textures" => "jpg",
        _ => "blend",
    }
}

fn resolution_rank(resolution: &str) -> i64 {
    resolution.trim_end_matches('k').parse().unwrap_or(-1)
}

/// What an asset actually offers, for an error the agent can act on.
fn available(files: &Value, asset_type: &str) -> String {
    let supported = supported_formats(asset_type);
    let mut resolutions: Vec<String> = Vec::new();
    let mut formats: Vec<String> = Vec::new();
    for by_resolution in files.as_object().into_iter().flat_map(|m| m.values()) {
        for (resolution, by_format) in by_resolution.as_object().into_iter().flat_map(|m| m.iter()) {
            let present: Vec<&String> = by_format.as_object().map(|m| m.keys().filter(|f| supported.contains(&f.as_str())).collect()).unwrap_or_default();
            if !present.is_empty() && !resolutions.contains(resolution) {
                resolutions.push(resolution.clone());
            }
            for format in present {
                if !formats.contains(format) {
                    formats.push(format.clone());
                }
            }
        }
    }
    resolutions.sort_by_key(|r| (resolution_rank(r) < 0, resolution_rank(r)));
    formats.sort();
    format!(
        "available resolutions: {}; formats: {}",
        if resolutions.is_empty() { "none".into() } else { resolutions.join(", ") },
        if formats.is_empty() { "none".into() } else { formats.join(", ") }
    )
}

/// The texture maps that drive a Principled BSDF directly, and their roles.
/// Poly Haven's keys are matched exactly: their casing is inconsistent and
/// load-bearing ("Diffuse" and "Rough" but "nor_gl" and "arm").
const TEXTURE_MAPS: [(&str, &str); 6] = [
    ("Diffuse", "base_color"),
    ("Rough", "roughness"),
    ("Metal", "metallic"),
    ("Displacement", "displacement"),
    ("nor_gl", "normal"),
    ("nor_dx", "normal"),
];

fn select_texture_maps(files: &Value, resolution: &str, format: &str) -> Vec<(String, &'static str)> {
    let has = |key: &str| files.get(key).and_then(|r| r.get(resolution)).and_then(|f| f.get(format)).is_some();
    let mut selected: Vec<(String, &'static str)> = TEXTURE_MAPS.iter().filter(|(k, _)| has(k)).map(|(k, r)| (k.to_string(), *r)).collect();
    // OpenGL normals are what Blender's Normal Map node expects; nor_dx only
    // for the few assets without them.
    if selected.iter().any(|(k, _)| k == "nor_gl") {
        selected.retain(|(k, _)| k != "nor_dx");
    }
    // Some fabrics name their albedo col_1, col_03 and the like.
    if !selected.iter().any(|(_, r)| *r == "base_color") {
        let mut keys: Vec<&String> = files.as_object().map(|m| m.keys().collect()).unwrap_or_default();
        keys.sort();
        if let Some(k) = keys.into_iter().find(|k| {
            let lower = k.to_lowercase();
            (lower.starts_with("col") || lower.starts_with("diff")) && has(k)
        }) {
            selected.push((k.clone(), "base_color"));
        }
    }
    selected
}

/// A path from the API, as a relative path inside dir with no way out of it.
fn inside(dir: &Path, relative: &str) -> Option<PathBuf> {
    let rel = Path::new(relative);
    if rel.is_absolute() || relative.contains("..") {
        return None;
    }
    if rel.components().any(|c| !matches!(c, Component::Normal(_))) {
        return None;
    }
    Some(dir.join(rel))
}

fn file_size(info: &Value) -> Option<u64> {
    info.get("size").and_then(|s| s.as_u64())
}

fn file_url(info: &Value) -> Result<&str, String> {
    info.get("url").and_then(|u| u.as_str()).ok_or_else(|| "the file record has no url".to_string())
}

fn polyhaven_fetch(id: &str, asset_type: &str, resolution: &str, format: &str, dir: &Path) -> Result<Value, String> {
    if !valid_slug(id) {
        return Err(format!("Invalid Poly Haven id {id:?}: slugs are letters, digits, underscores and hyphens"));
    }
    let supported = supported_formats(asset_type);
    if supported.is_empty() {
        return Err("polyhaven needs asset_type: hdris, textures or models".into());
    }
    let format = if format.is_empty() { default_format(asset_type).to_string() } else { format.to_lowercase() };
    if !supported.contains(&format.as_str()) {
        return Err(format!("Unsupported {asset_type} format: {format}. Supported formats: {}", supported.join(", ")));
    }
    let files = polyhaven_get(&format!("files/{}", encode_segment(id)), &[], false)
        .map_err(|e| e.text(&format!("fetching the file list for {id:?}")))?;
    let record = polyhaven_record(id);
    let mut manifest = json!({
        "source": "polyhaven",
        "id": id,
        "asset_type": asset_type,
        "resolution": resolution,
        "format": format,
        "dir": dir.to_string_lossy(),
        "url": polyhaven_url(id),
        "authors": authors_of(&record),
        "licence": "CC0",
    });
    match asset_type {
        "hdris" => {
            let info = files.get("hdri").and_then(|r| r.get(resolution)).and_then(|f| f.get(&format))
                .ok_or_else(|| format!("HDRI {id:?} has no {resolution} {format} - {}", available(&files, asset_type)))?;
            let path = dir.join(format!("{id}_{resolution}.{format}"));
            download(file_url(info)?, &[], &path, file_size(info))?;
            manifest["kind"] = json!("hdri");
            manifest["path"] = json!(path.to_string_lossy());
        }
        "textures" => {
            let wanted = select_texture_maps(&files, resolution, &format);
            if wanted.is_empty() {
                return Err(format!("Texture {id:?} has no maps at {resolution} {format} - {}", available(&files, asset_type)));
            }
            let mut maps = Vec::new();
            for (key, role) in wanted {
                let info = &files[&key][resolution][&format];
                let path = dir.join(format!("{id}_{key}_{resolution}.{format}"));
                download(file_url(info)?, &[], &path, file_size(info))?;
                maps.push(json!({ "key": key, "role": role, "path": path.to_string_lossy() }));
            }
            manifest["kind"] = json!("texture");
            manifest["maps"] = json!(maps);
            // A texture's real-world size; length two, unlike a model's box.
            if let Some(d) = record.get("dimensions").and_then(|d| d.as_array()).filter(|d| d.len() == 2) {
                manifest["dimensions_mm"] = json!(d);
            }
        }
        _ => {
            let info = files.get(&format).and_then(|r| r.get(resolution)).and_then(|f| f.get(&format))
                .ok_or_else(|| format!("Model {id:?} has no {resolution} {format} - {}", available(&files, asset_type)))?;
            let url = file_url(info)?;
            let main_name = url.split('?').next().unwrap_or(url).rsplit('/').next().unwrap_or("model").to_string();
            let main = inside(dir, &main_name).ok_or_else(|| format!("unsafe file name {main_name:?} from Poly Haven"))?;
            download(url, &[], &main, file_size(info))?;
            // Sidecar textures; the keys come from the API, so each must stay
            // inside the download folder.
            if let Some(includes) = info.get("include").and_then(|i| i.as_object()) {
                for (relative, include) in includes {
                    let Some(target) = inside(dir, relative) else {
                        continue;
                    };
                    if let Some(parent) = target.parent() {
                        std::fs::create_dir_all(parent).map_err(|e| format!("cannot create {}: {e}", parent.display()))?;
                    }
                    download(file_url(include)?, &[], &target, file_size(include))?;
                }
            }
            manifest["kind"] = json!("model");
            manifest["path"] = json!(main.to_string_lossy());
        }
    }
    Ok(manifest)
}

// ---------- Sketchfab ----------

fn sketchfab_search(query: &str, categories: &str, limit: i64) -> Result<Value, String> {
    let token = key(SKETCHFAB_KEY, "Sketchfab", "https://sketchfab.com/settings/password")?;
    let mut params = vec![
        ("type", "models".to_string()),
        ("q", query.to_string()),
        ("count", limit.clamp(1, 24).to_string()),
        ("downloadable", "true".to_string()),
        ("archives_flavours", "false".to_string()),
    ];
    if !categories.is_empty() {
        params.push(("categories", categories.to_string()));
    }
    let data = get_json(&format!("{SKETCHFAB_API}/search"), &params, &[("Authorization", format!("Token {token}"))]).map_err(|e| match e {
        Http::Status(401, _) => "Sketchfab authentication failed (401). Check BLENDERMCP_SKETCHFAB_API_KEY.".to_string(),
        other => other.text("the Sketchfab search"),
    })?;
    let results = data.get("results").and_then(|r| r.as_array()).ok_or("Sketchfab's reply had no results list")?;
    let models: Vec<Value> = results.iter().map(|m| {
        let thumbnails = m.pointer("/thumbnails/images").and_then(|t| t.as_array()).cloned().unwrap_or_default();
        let thumbnail = thumbnails.iter()
            .find(|t| t.get("width").and_then(|w| w.as_i64()).map(|w| (400..=800).contains(&w)).unwrap_or(false))
            .or_else(|| thumbnails.first())
            .and_then(|t| t.get("url")).cloned().unwrap_or(Value::Null);
        json!({
            "uid": m.get("uid"),
            "name": m.get("name"),
            "author": m.pointer("/user/username"),
            "license": m.pointer("/license/label"),
            "faces": m.get("faceCount"),
            "vertices": m.get("vertexCount"),
            "animated": m.get("animationCount").and_then(|a| a.as_i64()).map(|a| a > 0).unwrap_or(false),
            "url": m.get("viewerUrl"),
            "thumbnail": thumbnail,
        })
    }).collect();
    Ok(json!({ "source": "sketchfab", "results": models, "returned_count": results.len(), "more": data.get("next").map(truthy).unwrap_or(false) }))
}

fn sketchfab_fetch(uid: &str, dir: &Path) -> Result<Value, String> {
    if uid.is_empty() || uid.len() > 64 || !uid.bytes().all(|b| b.is_ascii_alphanumeric()) {
        return Err(format!("Invalid Sketchfab uid {uid:?}: it is the hexadecimal uid from search_assets"));
    }
    let token = key(SKETCHFAB_KEY, "Sketchfab", "https://sketchfab.com/settings/password")?;
    let auth = [("Authorization", format!("Token {token}"))];
    let data = get_json(&format!("{SKETCHFAB_API}/models/{uid}/download"), &[], &auth).map_err(|e| match e {
        Http::Status(401, _) => "Sketchfab authentication failed (401). Check BLENDERMCP_SKETCHFAB_API_KEY.".to_string(),
        Http::Status(404, _) => format!("Sketchfab has no downloadable model {uid}"),
        other => other.text("the Sketchfab download request"),
    })?;
    let url = data.pointer("/gltf/url").and_then(|u| u.as_str())
        .ok_or("Sketchfab offered no glTF archive for this model; make sure it is downloadable and the key has access")?;
    let archive = dir.join(format!("{uid}.zip"));
    // A signed URL: it carries its own credentials, so no key is sent with it.
    download(url, &[], &archive, data.pointer("/gltf/size").and_then(|s| s.as_u64()))?;
    // Who made it and under what licence, for the credit line; best effort.
    let info = get_json(&format!("{SKETCHFAB_API}/models/{uid}"), &[], &auth).unwrap_or(Value::Null);
    Ok(json!({
        "source": "sketchfab",
        "kind": "archive",
        "id": uid,
        "dir": dir.to_string_lossy(),
        "path": archive.to_string_lossy(),
        "name": info.get("name"),
        "authors": info.pointer("/user/username").map(|u| json!([u])).unwrap_or(json!([])),
        "licence": info.pointer("/license/label"),
        "url": info.get("viewerUrl"),
    }))
}

// ---------- Poly Pizza ----------

/// A category name or id 0-11 to the id the API filters on.
fn polypizza_category(text: &str) -> Result<Option<i64>, String> {
    let stripped = text.trim();
    if stripped.is_empty() {
        return Ok(None);
    }
    if stripped.bytes().all(|b| b.is_ascii_digit()) {
        let value: i64 = stripped.parse().map_err(|_| format!("Poly Pizza category {stripped} is not a number"))?;
        return if value <= 11 { Ok(Some(value)) } else { Err(format!("Poly Pizza category id {value} is out of range (valid ids are 0-11)")) };
    }
    let key: String = stripped.to_lowercase().chars().filter(|c| c.is_ascii_alphanumeric()).collect();
    let id = match key.as_str() {
        "fooddrink" | "food" | "drink" | "drinks" => 0,
        "clutter" => 1,
        "weapons" | "weapon" => 2,
        "transport" | "vehicle" | "vehicles" | "transportation" => 3,
        "furnituredecor" | "furniture" | "decor" => 4,
        "objects" | "object" | "prop" | "props" => 5,
        "nature" | "plant" | "plants" => 6,
        "animals" | "animal" => 7,
        "buildings" | "building" | "architecture" | "buildingsarchitecture" => 8,
        "peoplecharacters" | "person" | "character" | "characters" | "people" => 9,
        "sceneslevels" | "scene" | "scenes" | "level" | "levels" => 10,
        "other" => 11,
        _ => {
            return Err(format!(
                "Unknown Poly Pizza category {text:?}. Valid categories: Food & Drink, Clutter, Weapons, Transport, Furniture & Decor, Objects, Nature, Animals, Buildings, People & Characters, Scenes & Levels, Other."
            ))
        }
    };
    Ok(Some(id))
}

fn polypizza_licence(text: &str) -> Result<Option<i64>, String> {
    let stripped = text.trim();
    if stripped.is_empty() {
        return Ok(None);
    }
    if stripped.bytes().all(|b| b.is_ascii_digit()) {
        return match stripped {
            "0" => Ok(Some(0)),
            "1" => Ok(Some(1)),
            _ => Err(format!("Poly Pizza licence id {stripped} is invalid (0 = CC-BY, 1 = CC0)")),
        };
    }
    let key: String = stripped.to_lowercase().chars().filter(|c| c.is_ascii_alphanumeric()).collect();
    if key.starts_with("ccby") {
        Ok(Some(0))
    } else if key.starts_with("cc0") || key == "publicdomain" {
        Ok(Some(1))
    } else {
        Err(format!("Unknown Poly Pizza licence {text:?}. Use 'CC0' or 'CC-BY'."))
    }
}

fn polypizza_summary(model: &Value) -> Value {
    json!({
        "id": model.get("ID"),
        "title": model.get("Title"),
        "creator": model.pointer("/Creator/Username"),
        "licence": model.get("Licence"),
        "triangles": model.get("Tri Count"),
        "animated": model.get("Animated").map(truthy).unwrap_or(false),
        "category": model.get("Category"),
        "tags": model.get("Tags").cloned().unwrap_or(json!([])),
        "thumbnail": model.get("Thumbnail"),
    })
}

fn polypizza_search(query: &str, category: &str, licence: &str, animated: bool, limit: i64) -> Result<Value, String> {
    let token = key(POLYPIZZA_KEY, "Poly Pizza", "https://poly.pizza/settings/api")?;
    // Every query parameter is Capitalized: lowercase ones are accepted with a
    // 200 and then silently ignored.
    let mut params: Vec<(&str, String)> = Vec::new();
    if let Some(id) = polypizza_category(category)? {
        params.push(("Category", id.to_string()));
    }
    if let Some(id) = polypizza_licence(licence)? {
        params.push(("License", id.to_string()));
    }
    // Animated=0 is treated as falsy and filters nothing, so it is only sent as 1.
    if animated {
        params.push(("Animated", "1".into()));
    }
    let keyword = query.trim();
    if keyword.is_empty() && params.is_empty() {
        return Err("polypizza needs a query or at least one filter (category, licence, or animated); the API refuses an unfiltered listing".into());
    }
    params.push(("Limit", limit.clamp(1, 32).to_string()));
    let url = if keyword.is_empty() { format!("{POLYPIZZA_API}/search") } else { format!("{POLYPIZZA_API}/search/{}", encode_segment(keyword)) };
    let data = get_json(&url, &params, &[("x-auth-token", token)]).map_err(|e| match e {
        Http::Status(code @ (401 | 403), _) => format!("Poly Pizza authentication failed ({code}). Check BLENDERMCP_POLYPIZZA_API_KEY."),
        Http::Status(400, _) => "Poly Pizza rejected the search parameters (400).".to_string(),
        Http::Status(429, _) => "Poly Pizza rate limit exceeded. Try again in a moment.".to_string(),
        other => other.text("the Poly Pizza search"),
    })?;
    let results = data.get("results").and_then(|r| r.as_array()).ok_or("Poly Pizza's reply had no results list")?;
    Ok(json!({
        "source": "polypizza",
        "total": data.get("total").cloned().unwrap_or(json!(results.len())),
        "results": results.iter().filter(|m| m.is_object()).map(polypizza_summary).collect::<Vec<_>>(),
    }))
}

fn polypizza_fetch(id: &str, dir: &Path) -> Result<Value, String> {
    let token = key(POLYPIZZA_KEY, "Poly Pizza", "https://poly.pizza/settings/api")?;
    let model = get_json(&format!("{POLYPIZZA_API}/model/{}", encode_segment(id)), &[], &[("x-auth-token", token)]).map_err(|e| match e {
        Http::Status(code @ (401 | 403), _) => format!("Poly Pizza authentication failed ({code}). Check BLENDERMCP_POLYPIZZA_API_KEY."),
        Http::Status(404, _) => format!("No Poly Pizza model has the id {id:?}"),
        other => other.text("the Poly Pizza model lookup"),
    })?;
    let url = model.get("Download").and_then(|u| u.as_str()).ok_or_else(|| format!("Poly Pizza model {id:?} has no downloadable GLB"))?;
    let safe: String = id.chars().map(|c| if c.is_ascii_alphanumeric() || c == '_' || c == '-' { c } else { '_' }).collect();
    let path = dir.join(format!("{}.glb", if safe.is_empty() { "model".into() } else { safe }));
    // The CDN is a separate host that takes no key, so none is sent to it. It
    // sits behind Cloudflare bot management, which answers datacenter, VPN and
    // cloud addresses with an HTML challenge rather than the file.
    let resp = match request(url, &[], &[]) {
        Err(Http::Status(code, _)) if code == 403 || code == 503 => {
            return Err(format!(
                "Poly Pizza's CDN refused the download (HTTP {code}), most likely a Cloudflare bot-protection challenge: \
                 it blocks datacenter, VPN and cloud addresses. This is not a key problem. Retry from a residential \
                 connection, or download the .glb from https://poly.pizza and import it with File > Import > glTF 2.0."
            ))
        }
        Err(e) => return Err(e.text("the Poly Pizza file download")),
        Ok(resp) => resp,
    };
    save(resp, &path, None)?;
    let mut head = [0u8; 4];
    let ok = std::fs::File::open(&path).and_then(|mut f| f.read_exact(&mut head)).is_ok() && &head == b"glTF";
    if !ok {
        let _ = std::fs::remove_file(&path);
        return Err("Poly Pizza's CDN sent something that is not a GLB file (no glTF magic bytes), most likely an HTML challenge page; search again for a fresh link, or retry from another connection".into());
    }
    Ok(json!({
        "source": "polypizza",
        "kind": "glb",
        "id": model.get("ID").cloned().unwrap_or(json!(id)),
        "dir": dir.to_string_lossy(),
        "path": path.to_string_lossy(),
        "name": model.get("Title"),
        "authors": model.pointer("/Creator/Username").map(|u| json!([u])).unwrap_or(json!([])),
        "licence": model.get("Licence"),
        "attribution": model.get("Attribution"),
    }))
}

// ---------- download folders ----------

/// A fresh folder for one asset under parent (created if missing), after
/// sweeping folders this module left behind more than an hour ago.
fn fresh_dir(parent: &Path, source: &str, id: &str) -> Result<PathBuf, String> {
    std::fs::create_dir_all(parent).map_err(|e| format!("cannot create {}: {e}", parent.display()))?;
    if let Ok(entries) = std::fs::read_dir(parent) {
        for entry in entries.flatten() {
            let stale = entry.file_name().to_string_lossy().starts_with(DOWNLOAD_PREFIX)
                && entry.file_type().map(|t| t.is_dir()).unwrap_or(false)
                && entry.metadata().and_then(|m| m.modified()).ok()
                    .and_then(|t| SystemTime::now().duration_since(t).ok())
                    .map(|age| age > STALE_AFTER).unwrap_or(false);
            if stale {
                let _ = std::fs::remove_dir_all(entry.path());
            }
        }
    }
    static N: AtomicU64 = AtomicU64::new(0);
    let safe: String = id.chars().take(40).map(|c| if c.is_ascii_alphanumeric() || c == '_' || c == '-' { c } else { '_' }).collect();
    let dir = parent.join(format!("{DOWNLOAD_PREFIX}{source}-{safe}-{}-{}", std::process::id(), N.fetch_add(1, Ordering::Relaxed)));
    std::fs::create_dir(&dir).map_err(|e| format!("cannot create {}: {e}", dir.display()))?;
    Ok(dir)
}

// ---------- entry points ----------

/// Search one library. source is polyhaven, sketchfab or polypizza; the other
/// arguments apply where that library has them (asset_type, min_size_m:
/// polyhaven; category: all three, in each one's vocabulary; licence, animated:
/// polypizza). Answers JSON text, or {"error": ...}.
pub fn asset_search(source: &str, query: &str, asset_type: &str, category: &str, licence: &str, min_size_m: f64, animated: bool, limit: i64) -> String {
    let result = match source {
        "polyhaven" => polyhaven_search(asset_type, category, query, min_size_m, limit),
        "sketchfab" => {
            if query.trim().is_empty() {
                Err("sketchfab needs a query".to_string())
            } else {
                sketchfab_search(query, category, limit)
            }
        }
        "polypizza" => polypizza_search(query, category, licence, animated, limit),
        other => Err(format!("unknown source {other:?}: polyhaven, sketchfab or polypizza")),
    };
    match result {
        Ok(value) => value.to_string(),
        Err(why) => error(why),
    }
}

/// Download one asset into a fresh folder under parent and answer the manifest
/// python/mcp_scripts.py's import_asset reads: kind (hdri, texture, model,
/// archive, glb), dir, the file path or texture maps, and the credit fields.
pub fn asset_fetch(source: &str, id: &str, asset_type: &str, resolution: &str, format: &str, parent: &str) -> String {
    let id = id.trim();
    let dir = match fresh_dir(Path::new(parent), source, id) {
        Ok(dir) => dir,
        Err(why) => return error(why),
    };
    let result = match source {
        "polyhaven" => polyhaven_fetch(id, asset_type, resolution, format, &dir),
        "sketchfab" => sketchfab_fetch(id, &dir),
        "polypizza" => polypizza_fetch(id, &dir),
        other => Err(format!("unknown source {other:?}: polyhaven, sketchfab or polypizza")),
    };
    match result {
        Ok(manifest) => manifest.to_string(),
        Err(why) => {
            let _ = std::fs::remove_dir_all(&dir);
            error(why)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn paths_from_the_api_stay_inside() {
        let dir = Path::new("/tmp/x");
        assert_eq!(inside(dir, "textures/a.jpg"), Some(dir.join("textures/a.jpg")));
        assert_eq!(inside(dir, "../a.jpg"), None);
        assert_eq!(inside(dir, "/etc/passwd"), None);
        assert_eq!(inside(dir, "a/../../b"), None);
    }

    #[test]
    fn slugs_and_segments() {
        assert!(valid_slug("brown_planks_09"));
        assert!(!valid_slug("../x"));
        assert!(!valid_slug(""));
        assert_eq!(encode_segment("red chair/1"), "red%20chair%2F1");
    }

    #[test]
    fn polypizza_names_resolve() {
        assert_eq!(polypizza_category("Furniture & Decor").unwrap(), Some(4));
        assert_eq!(polypizza_category("11").unwrap(), Some(11));
        assert!(polypizza_category("12").is_err());
        assert_eq!(polypizza_licence("CC-BY").unwrap(), Some(0));
        assert_eq!(polypizza_licence("cc0").unwrap(), Some(1));
        assert_eq!(polypizza_category("").unwrap(), None);
    }

    #[test]
    fn texture_maps_prefer_gl_normals_and_find_odd_albedos() {
        let files = json!({
            "Diffuse": {"1k": {"jpg": {}}}, "nor_gl": {"1k": {"jpg": {}}}, "nor_dx": {"1k": {"jpg": {}}}, "arm": {"1k": {"jpg": {}}}
        });
        let picked: Vec<String> = select_texture_maps(&files, "1k", "jpg").into_iter().map(|(k, _)| k).collect();
        assert_eq!(picked, vec!["Diffuse", "nor_gl"]);
        let fabric = json!({ "col_1": {"1k": {"jpg": {}}}, "Rough": {"1k": {"jpg": {}}} });
        let roles: Vec<&str> = select_texture_maps(&fabric, "1k", "jpg").into_iter().map(|(_, r)| r).collect();
        assert_eq!(roles, vec!["roughness", "base_color"]);
    }

    #[test]
    fn keyword_fallback_ranks_by_hits_then_downloads() {
        let assets = json!({
            "red_brick": {"name": "Red Brick", "download_count": 5},
            "red_brick_wall": {"name": "Red Brick Wall", "tags": ["wall"], "download_count": 1},
            "grass": {"name": "Grass", "download_count": 99}
        });
        let ranked = keyword_match("red wall", assets.as_object().unwrap());
        assert_eq!(ranked, vec!["red_brick_wall", "red_brick"]);
    }
}
