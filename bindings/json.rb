# typed: true
# JSON over HTTP, backed by `ureq` and `serde_json`. `Value` is an opaque type
# carrying a parsed JSON document between this binding's functions; the pointer
# functions pull typed values out of it using RFC 6901 JSON pointers, such as
# "/current/temperature_2m" or "/daily/time". A pointer that does not exist, or
# a value of the wrong JSON type, gives nil, never an error. The `*_list`
# functions read a JSON array at the pointer into a typed list.
module Json
  extend T::Sig
  extend RmcpDsl::BindingDsl

  crate "ureq", "2"
  crate "serde_json", "1"
  crate "base64", "0.22"

  class Value < RmcpDsl::Opaque
    type_rust "serde_json::Value", wire: true
  end

  # Fetch a URL and parse the body as JSON; nil when the request fails, the
  # response is not a success, or the body is not JSON.
  rust "ureq::AgentBuilder::new().timeout(std::time::Duration::from_secs(10)).build().get(url).call().ok().and_then(|r| r.into_string().ok()).and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())"
  no_reference "needs a server to talk to; the end-to-end test runs it against a local one"
  sig { params(url: String).returns(T.nilable(Value)) }
  def self.get(url) = raise(NotImplementedError, "no Ruby stand-in")

  # A number at the pointer, as a float; nil when it is absent or not a number.
  rust "value.pointer(ptr).and_then(|v| v.as_f64())"
  no_reference "serde_json is the parser"
  sig { params(value: Value, ptr: String).returns(T.nilable(Float)) }
  def self.f64(value, ptr) = raise(NotImplementedError, "no Ruby stand-in")

  # An integer at the pointer; nil when it is absent or not an integer.
  rust "value.pointer(ptr).and_then(|v| v.as_i64())"
  no_reference "serde_json is the parser"
  sig { params(value: Value, ptr: String).returns(T.nilable(I64)) }
  def self.i64(value, ptr) = raise(NotImplementedError, "no Ruby stand-in")

  # A string at the pointer; nil when it is absent or not a string.
  rust "value.pointer(ptr).and_then(|v| v.as_str().map(|s| s.to_string()))"
  no_reference "serde_json is the parser"
  sig { params(value: Value, ptr: String).returns(T.nilable(String)) }
  def self.text(value, ptr) = raise(NotImplementedError, "no Ruby stand-in")

  # True when a value exists at the pointer, of any JSON type.
  rust "value.pointer(ptr).is_some()"
  no_reference "serde_json is the parser"
  sig { params(value: Value, ptr: String).returns(T::Boolean) }
  def self.has?(value, ptr) = raise(NotImplementedError, "no Ruby stand-in")

  # The length of the array at the pointer; nil when it is absent or not an array.
  rust "value.pointer(ptr).and_then(|v| v.as_array()).map(|a| a.len() as i64)"
  no_reference "serde_json is the parser"
  sig { params(value: Value, ptr: String).returns(T.nilable(I64)) }
  def self.count(value, ptr) = raise(NotImplementedError, "no Ruby stand-in")

  # The JSON value at the pointer, of any type, kept as an opaque document; nil when absent.
  rust "value.pointer(ptr).cloned()"
  no_reference "serde_json is the parser"
  sig { params(value: Value, ptr: String).returns(T.nilable(Value)) }
  def self.at(value, ptr) = raise(NotImplementedError, "no Ruby stand-in")

  # The strings in the array at the pointer; nil when it is absent or not an array.
  rust "value.pointer(ptr).and_then(|v| v.as_array()).map(|a| a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect::<Vec<String>>())"
  no_reference "serde_json is the parser"
  sig { params(value: Value, ptr: String).returns(T.nilable(T::Array[String])) }
  def self.text_list(value, ptr) = raise(NotImplementedError, "no Ruby stand-in")

  # A JSON array text for a list of strings; "[]" when there is no list. Lets a
  # typed list argument cross into a request without quoting each item by hand.
  rust "serde_json::to_string(&items).unwrap_or_else(|_| \"[]\".to_string())"
  no_reference "serde_json is the parser"
  sig { params(items: T::Array[String]).returns(String) }
  def self.str_list_json(items) = raise(NotImplementedError, "no Ruby stand-in")

  # A JSON array text for a list of integers; "[]" when there is no list.
  rust "serde_json::to_string(&items).unwrap_or_else(|_| \"[]\".to_string())"
  no_reference "serde_json is the parser"
  sig { params(items: T::Array[I64]).returns(String) }
  def self.i64_list_json(items) = raise(NotImplementedError, "no Ruby stand-in")

  # A JSON string literal for text, quotes and escapes included, for building requests.
  rust "serde_json::to_string(s).unwrap_or_default()"
  no_reference "serde_json is the parser"
  sig { params(s: String).returns(String) }
  def self.quote(s) = raise(NotImplementedError, "no Ruby stand-in")

  # A fresh path for one image Blender writes and this server reads: the system
  # temp directory, a kind, this process id and a counter, so concurrent tools
  # (or concurrent servers) never read each other's file. Both run on one host.
  rust "{ use std::sync::atomic::{AtomicU64, Ordering}; static N: AtomicU64 = AtomicU64::new(0); let n = N.fetch_add(1, Ordering::Relaxed); std::env::temp_dir().join(format!(\"mcp-blender-{}-{}-{}.png\", kind, std::process::id(), n)).to_string_lossy().into_owned() }"
  no_reference "needs the host's temp directory; the end-to-end test writes and reads a file"
  sig { params(kind: String).returns(String) }
  def self.temp_png(kind) = raise(NotImplementedError, "no Ruby stand-in")

  # The base64 of a file's bytes, then remove it; nil when it cannot be read.
  # For the image files Blender writes for this server at a temp path.
  rust "{ use base64::Engine as _; let data = std::fs::read(path).ok().map(|b| base64::engine::general_purpose::STANDARD.encode(b)); let _ = std::fs::remove_file(path); data }"
  no_reference "reads and removes a host file; the end-to-end test writes one"
  sig { params(path: String).returns(T.nilable(String)) }
  def self.take_file_base64(path) = raise(NotImplementedError, "no Ruby stand-in")

  # The text of a top-level `NAME = r'''...'''` constant in a Python file on
  # disk; nil when the file or the constant is absent. Lets the server run the
  # addon's own blender_scripts.py without embedding it.
  rust "{ let mut out: Option<String> = None; let mut prefix = String::new(); for _ in 0..4 { let cand = format!(\"{}{}\", prefix, path); if let Ok(s) = std::fs::read_to_string(&cand) { let needle = format!(\"{} = r'''\", name); if let Some(i) = s.find(&needle) { let rest = &s[i + needle.len()..]; if let Some(e) = rest.find(\"'''\") { out = Some(rest[..e].to_string()); break; } } } prefix.push_str(\"../\"); } out }"
  no_reference "reads the host filesystem"
  sig { params(path: String, name: String).returns(T.nilable(String)) }
  def self.py_constant(path, name) = raise(NotImplementedError, "no Ruby stand-in")

  # The text of a whole file on disk; nil when it cannot be read. Tries the path
  # as given and then from up to four parent directories, exactly as py_constant
  # does, because a setting holds a path relative to the server's own working
  # directory. This is how our own Python module reaches Blender: as a real file
  # in the repository, read here and sent once per content hash by run_module.
  rust "{ let mut out: Option<String> = None; let mut prefix = String::new(); for _ in 0..4 { let cand = format!(\"{}{}\", prefix, path); if let Ok(s) = std::fs::read_to_string(&cand) { out = Some(s); break; } prefix.push_str(\"../\"); } out }"
  no_reference "reads the host filesystem; the reference run has no file to point at"
  sig { params(path: String).returns(T.nilable(String)) }
  def self.read_text(path) = raise(NotImplementedError, "no Ruby stand-in")

  # Parse a JSON text into a Value; nil when it is not JSON.
  rust "serde_json::from_str::<serde_json::Value>(text).ok()"
  no_reference "serde_json is the parser"
  sig { params(text: String).returns(T.nilable(Value)) }
  def self.parse(text) = raise(NotImplementedError, "no Ruby stand-in")

  # A JSON text for a Value; nil when it cannot be encoded. The inverse of parse.
  rust "serde_json::to_string(&value).ok()"
  no_reference "serde_json is the parser"
  sig { params(value: Value).returns(T.nilable(String)) }
  def self.dump(value) = raise(NotImplementedError, "no Ruby stand-in")

  # A short digest of a text, for cache keys: it lets run_script install a changed
  # script under a new module name instead of reusing the one Blender already has.
  rust "{ use std::hash::{Hash, Hasher}; let mut h = std::collections::hash_map::DefaultHasher::new(); text.hash(&mut h); format!(\"{:x}\", h.finish() & 0xffff_ffff) }"
  no_reference "DefaultHasher output is not stable across Rust releases; compare two runs of the server instead"
  sig { params(text: String).returns(String) }
  def self.short_hash(text) = raise(NotImplementedError, "no Ruby stand-in")
end
