# rmcp_dsl gaps found building the Blender MCP server

Found while building `blender.rmcp.rb` (a Rust MCP server over the
`mcp-for-blender` addon's socket bridge). Each entry is tagged:

- **language** — not expressible today; needs a compiler change.
- **typing** — expressible via an opaque `Json::Value`, but without types (no
  schema, structured output or editor support).
- **ergonomics** — expressible, but awkward or poorly explained by a diagnostic.
- **tooling** — the LSP/build workflow, not the language itself.
- **codegen** — the quality of the emitted Rust (warnings, idioms).

Ordered by how much each one slowed the work. Editor-side issues found in the
same sessions (saving, stale buffers, LSP caching, claim sets) are recorded
separately in `raj-editor-issues.md`.

## 1. `language` — a tool cannot take no arguments

`params` must declare at least one `field`, so an MCP tool with an empty
argument object is not expressible.

```ruby
params :NoArgs do
end
```
→ `params 'NoArgs' needs at least one field`

Argument-less tools are common in MCP (the Blender addon's `get_scene_info`,
`get_addon_info`, `get_world_state_snapshot`; `ping`; "current time").
*Workaround:* point the tool at a sibling command that does take arguments.
**Suggest:** allow an empty `params`, or make `params:` optional on a tool.

## 2. `typing` — binding return types have no float (or i32) arrays

`T.nilable(T::Array[Float])` is refused. The allowed set is `String`, `Float`,
`I32`, `I64`, `T::Boolean`, `T::Array[String]`, `T::Array[I64]`, `Json::Value`.
So a numeric array parsed from JSON can only come back as opaque `Json::Value`
(a weather forecast's daily temperatures), and an `:f64_list` output field
cannot be filled from a binding at all.
*Workaround:* return the array as `Json::Value`.
**Suggest:** add `T::Array[Float]` (and `T::Array[I32]`, `T::Array[T::Boolean]`).

## 3. `typing` — no typed record/row (rows themselves are expressible)

Rows are reachable today: a binding can return `Json::Value`, e.g. a
`Html.rows(html, ".place-card", ...)` yielding an array of objects, and
`wire: true` lets an output field carry it. What is missing is a *typed* record —
a `record :Row do ... end` usable in binding returns and outputs — so the
schema, the structured result and the editor types can describe a row. Until
then, `Html.select`/`Html.attr` stay column-oriented (20 names and 20 links, not
20 rows) and row data is opaque.
**Suggest:** a record type, or ship a `rows` helper on the HTML binding.

## 4. `language` — no `nil` literal in a body

An optional output field or a "no value" result cannot be produced; the body
must invent a sentinel.

```ruby
next_start = start + 20 < total ? start + 20 : nil   # unsupported NilNode
```
*Workaround:* a sentinel such as `-1`, documented in the field description.
**Suggest:** allow `nil` where a nil-able type is expected, so absent means absent.

## 5. `ergonomics` — `+` will not mix `str` and `String`

A Ruby literal lowers to borrowed `str`; a binding return is owned `String`, and
Rust's `Add` allows `String + &str` but not `&str + String`. So
`"literal" + owned` is a type mismatch (`str vs string`). It already works as
`"literal".to_s + owned`, or with interpolation — the gap is that neither the
message nor the docs point at that.
*Workaround:* interpolate (`"...#{owned}..."`), which is also what the Blender
server ended up doing.
**Suggest:** type string literals as `String` at `+`, accept a `Rust::Str(...)`
cast, or add a hint ("use interpolation or `.to_s`").

## 6. `ergonomics` — settings are always strings

Numeric config must be parsed by hand: `Integer(setting(:blender_port), 10)`.
*Workaround:* `Integer(setting(:x), 10)`.
**Suggest:** a typed setting (`setting :port, type: :i64`), or `setting(:x).to_i`.

## 7. `ergonomics` — building a JSON request in a body is awkward

Forming `{"type":"execute_code","params":{"code":<quoted>}}` needed a binding
`quote` helper plus string interpolation; there is no way to build arbitrary
JSON in the body (typed maps exist, but not for a nested request object).
*Workaround:* a `quote` binding function + interpolation (done here).
**Suggest:** `to_json` on maps, or a map/JSON literal accepted where JSON is
expected.

## 8. `language`/`typing` — opaque types do not cross binding modules

`Value` declared in `bindings/json.rb` cannot be passed to a function in another
binding, so the TCP client had to live in `json.rb` to reuse the type.
*Workaround:* one binding module holds both.
**Suggest:** document the one-module rule, or allow a shared/imported opaque type.

## 9. `tooling` — bindings are resolved from disk and cached

`use_bindings` reads `bindings/*.rb` from disk. A binding saved *after* the
server was first analysed is not picked up until the server's document changes,
and an unsaved binding buffer is invisible to both the LSP and `rmcp_dsl build`.
Repro: create and save `bindings/json.rb`, run diagnostics on the server → still
`bindings has no json.rb` until the server document itself is edited.
**Suggest:** watch `bindings/` and invalidate on change, and consider reading
bindings from open buffers so proposals can be checked before saving.

## 10. `ergonomics` — terse type-mismatch messages

`type mismatch: str vs string` names the types but not the fix, and neither does
the `+` case. A trailing hint would save a round trip — the compiler already does
this well elsewhere ("did you mean ...", "use `|| default` ...").

## 11. `codegen` — generated code can warn (`unused_mut`)

Building the Blender server (which has no required settings) emits:

```
warning: variable does not need to be mutable
   --> src/main.rs:154:9
    |
154 |     let mut missing: Vec<&str> = Vec::new();
    |         ----^^^^^^^
```

The settings check always declares `mut missing`, but when every `setting` has a
`default:` or `optional: true` nothing is ever pushed, so `mut` is unused. The
generated crate is meant to be warning-free (the emitter already scopes
deprecated calls with `#[allow(deprecated)]` for exactly this reason), so this is
a codegen defect, not just noise: a warning makes `-D warnings` CI and
`cargo clippy` unusable, and it points at line 154 of the generated file rather
than the DSL line. The map file (`rmcp_dsl.map.json`) translates *errors* back to
DSL lines; warnings have no such span.
**Suggest:** emit `mut` only when at least one setting can be missing (or add
`#[allow(unused_mut)]`), and route rustc warnings through `rmcp_dsl.map.json` so
they name the DSL line like errors do.

## Second session (2026-10-06)

Found while adding `look` (the LOOK script bridge), moving the transport into
hand-written Rust, and adding the persistent connection and install-once. The
entries below are ordered among themselves.

## 12. `tooling` — the build reads disk, and a stale buffer hides that

Three separate round trips came from this in one session, so it leads.

- `rmcp_dsl build` reads the file **on disk**. Edit the buffer, build before
  saving, and the older text compiles silently: the notices still print
  (`N-BINDING: … 10 function(s)`) and say nothing about which version they read.
  We built a caption-less `look`, read the runtime result, and nearly recorded a
  content-block bug that did not exist.
- `open --create` makes a **buffer**, not a file, so `rust_file "x.rs"` names a
  path that is not on disk; the checker reports `rust_file not found: x.rs`
  until the buffer is saved.
- The LSP caches bindings and `rust_file` resolution per referring document. A
  no-op `apply` does not invalidate it; a real edit (append then delete a
  newline) does.
- There is no `read --disk`, so when a stale buffer shadows a generated path a
  driver cannot see the bytes that were actually compiled (see #13).

**Suggest:** resolve bindings and `rust_file` from open buffers, or have the
`N-BINDING` / `N-RUST-INJECTED` notices state the path's on-disk version so a
stale build is visible; add `read --disk` for the case a driver only wants to
know what was compiled.

## 13. `tooling` — a stale generated-file buffer shadows reads, and `save --all` clobbers

The editor can hold `build/blender.rmcp/src/main.rs` as a buffer from an earlier
read. After the next build rewrites the file, the buffer keeps the pre-build
text and reports `unsaved-changes`; `raj ctl read` and `search` then answer from
the buffer, so a driver reading generated code reads the wrong build (we
diagnosed a non-existent bug this way).
**Workaround:** close those buffers, or ask the user to. `reload` and
`close --discard` are refused with "holds unsaved text written by the user", so
a driver cannot refresh them itself.
**Suggest:** treat generated paths specially (reload on change, or refuse to
keep them open), and give a driver a way to read bytes as they are on disk. The
clobber half is sharper: a `save --all` in that workspace writes the old text
back over freshly generated sources.

## 14. `ergonomics` — a large Rust implementation cannot stay in its binding

`bindings.md` puts a binding first among the escape hatches, and `rust "…"`
works well for an expression. But a binding has no `rust_file`, so a 15-line
transport has to live as a 1,900-character escaped string. Moving it to
`rust_file` + `rust_fn` works and puts the code in a real `.rs` file that rustc
checks, but it costs the typed layer:

- `rust_fn`'s `returns:` is one of `:i32`, `:i64`, `:f64`, `:bool`, `:string` —
  no nilable and no opaque `Json::Value`, so "no reply" becomes a sentinel
  (`""`) instead of `nil` and the reply crosses as text to be re-parsed;
- the call leaves the binding and moves into a body or helper, so the typed
  function that bodies call by name disappears.

**Suggest:** allow `rust_file` at binding level (a binding's implementation in a
`.rs` file beside it), and a nullable `returns:` such as `:string?`.

## 15. `typing` — binding parameters cannot be nil-able, and list fields take no default

```ruby
sig { params(items: T.nilable(T::Array[String])).returns(String) }
```
→ `a parameter cannot be nilable yet; return a nilable value instead`

and a list field (`:string_list`, `:i64_list`) cannot take `default:` (the docs
allow "a string, number or true/false literal"), so an optional list is
`optional: true` and the body folds nil itself:
`Json.str_list_json(targets || [])`.
**Suggest:** allow nilable parameters (the callee can decide), or document the
`optional: true` + `|| []` idiom beside the field table.

## 16. `ergonomics` — small body/helper rules that cost a round trip each

- **Settings are body-only.** `setting(:x)` in a helper is refused ("settings
  are read in a tool, prompt or resource body, not in a helper or a binding"),
  so a helper that needs one takes it as an argument. The message is clear; the
  helper section does not mention it.
- **Block parameters are field names, with no aliasing.** `body do |…,
  image_ref, …|` → `image_ref is not a field of the tool's params (fields: …,
  image, …); did you mean image?`. Worth knowing the good half: a field named
  `image` does **not** shadow the `image(base64, "image/png")` content block.
- **Locals are checked against Rust keywords** (`local ref must be snake_case
  and not a Rust keyword`) — a good diagnostic, worth keeping.

## 17. `ergonomics`/`codegen` — `||` moves its left operand

```ruby
raw = Json.parse(...)
resp = raw || raise("…")            # moves raw
if cold then retry else raw end     # error[E0382]: use of partially moved value
```

The mapped error points at the DSL body line (`use of partially moved value:
raw (in helper `run_script`; generated src/main.rs:377)`) but not at the fix:
make both branches yield the same non-nil value instead of reusing the moved
local.
**Suggest:** borrow at the `||` site, or add a hint naming the local the operator
consumed.

## 18. `language` — a heredoc is not accepted as a keyword-argument value

```ruby
server "blender", version: "0.1.0",
       instructions: <<~'TXT'
         …
       TXT
       do
```
→ `syntax error: unexpected 'do', ignoring it`; the same text as a single-line
string literal compiles. `instructions:` is a page of prose, so it is the
keyword most likely to want one.
**Suggest:** accept `<<~` here (and for other string-literal keywords), or state
in the grammar that a string literal is the only form.

## 19. `codegen` — `W-STR-STRIP-RUBY` fires on `.strip`

`ruby strip (NUL and ASCII whitespace) compiles to an explicit-set trim, not
Rust trim()` — emitted for two ordinary `.strip` calls. The trim is correct; the
warning is noise an author cannot act on (the same family as #11).
**Suggest:** keep it silent when the semantics coincide, or make it a notice.

### Confirmed working, for the record

- An array of content blocks: `[image(data, "image/png"), text(caption)]` emits
  both (`"types":["image","text"]`), and a param named `image` does not shadow
  `image(...)`.
- `rust_file` + `rust_fn` with `args: [:string, :i64, :string]` and a
  `pub fn(host: impl AsRef<str>, …, request: impl AsRef<str>) -> String`
  compiles and runs — `AsRef` sidesteps whether the call site passes `&str` or
  `String` (generated bindings use `&str`).
- A typed list reaches a Python script: `views: ["front","right"]` arrived as a
  JSON array and the script reported exactly those two, while omitting `views`
  produced its four defaults.

## Third session (2026-10-07)

### 20. `runtime` — `transport :http` trusts loopback only, and nothing can change that

The HTTP transport is the one that makes the server usable by an agent that is
not on the same machine — the whole point of driving Blender from a sandbox. It
binds `127.0.0.1`, and rmcp enforces a DNS-rebinding **host check**: a request
whose `Host` is not a loopback value is refused with
`Forbidden: Host header is not allowed`.

Every real MCP client sends the **URL's own authority** as `Host`. Captured from
opencode against a local probe:

```
POST /mcp?codemode=false
host: 127.0.0.1:9999        # exactly the URL it dialled
authorization: Bearer …
user-agent: opencode/latest/2.0.20/cli
```

So a client **on the host** works (`http://127.0.0.1:8787/mcp`), and a client
**across a boundary** — a container, another machine — cannot, because it must
dial something other than loopback and will present a `Host` the check refuses.
The transport's only knobs are `port:`, `auth_setting:` and the OAuth fields:
there is no `allowed_hosts:`, no bind address, and no way to disable the check.

**Workaround, and why it does not count:** a hand-written client can set
`Host: 127.0.0.1:<port>` itself while dialling the real address — a real MCP
client cannot, so the case stays unsolved.

**Suggest:** an `allowed_hosts:` keyword on `transport :http` (seeding rmcp's
check), and/or a `bind:` address. The bearer token is already the authentication
story; the host check is a browser-oriented defence and is the wrong default for
a token-bearing service meant to be reached from elsewhere.

### 21. `language` — a `String` local cannot be borrowed or cloned

Moving a `String` local in one branch and reading it in another is a Rust error:

```
error[E0382]: borrow of moved value: `url0`
blender.rmcp.rb:245: error: use of moved value: `url1` (in helper `gen_poll`)
```

rustc's own suggestion is to `.clone()` at the move site. The DSL has neither
`.clone` nor `.dup`, and no borrow syntax, so the only remedy is to
**restructure** so each local is moved on at most one path and never read after:

```ruby
# both statements, url0/url1 move in the first and are read in the second
glb = if type0 == "GLB" then url0 elsif type1 == "GLB" then url1 else "" end
model = if glb != "" then glb elsif url0 != "" then url0 else url1 end

# one expression, each local read once on any path
model = if type0 == "GLB" then url0 elsif type1 == "GLB" then url1 elsif url0 != "" then url0 else url1 end
```

**Suggest:** allow `.clone`/`.dup` (a Rust `.clone()`), or document the
restructure rule beside gap #17, which is the same move semantics seen through
`||`.

### 22. `codegen` — a cast operand is parenthesised, and rustc says so

`handle[provider.length + 1, …]` compiles to
`ck_add_i64((provider.chars().count() as i64), 1, …)`, and rustc warns:

```
warning: unnecessary parentheses around function argument
  --> src/main.rs:834   (blender.rmcp.rb:368, in helper `gen_wait`)
```

Hoisting the length into a plain local first (`plen = provider.length`) avoids
the cast and, we believe, the warning — that build has not been read back, so
treat the fix as unconfirmed.

**Suggest:** do not parenthesise a cast operand when emitting a call argument.

### 23. `language` — no exception handling, so retries and fallbacks are written as values

Errors are `raise`d and cannot be caught: the body language has no `begin`/`rescue`
and no `catch`. `.each { … }` loops cannot carry state between iterations either
(reassigning an outer local is refused), so a fallback cannot be written as
control flow:

```ruby
# the shape one reaches for, and cannot have
begin
  submit(provider_a)
rescue
  submit(provider_b)
end
```

What *is* expressible is the value form — turn failure into data, then choose:

```ruby
a = attempt(provider_a)                 # raises nothing: "" or {"problem": …}
b = if a == "" then attempt(provider_b) else "" end
```

at the cost of an explicit attempt per candidate, unrolled, plus a
non-raising variant of every helper that needs it. `xs[i]`, `xs.first` and
`xs.last` exist (all nil-able), so the unrolled form at least works.

This surfaced on `generate_3d`'s `auto` provider choice: the addon's `enabled`
flag does **not** mean reachable (Hunyuan3D reports `enabled: true` with nothing
listening on its local API), so the first "enabled" provider is a dead socket and
the call fails where a fallback should have moved on. Python gets this with
`try`/`except`.

**Suggest:** document "failures are values, not exceptions" as *the* retry
pattern (it is easy to reach for `rescue` first), or allow a `rescue`-like form.

