# Building the Blender MCP server, and the HTTP transport it speaks

Why this server speaks HTTP, how it is built, and what the `rmcp_dsl` compiler
still cannot express. Blender-side traps are in `docs/blender-notes.md`, the
text-vision design in `docs/text-vision.md`, and the editor problems found driving
the build in `docs/editor-issues.md`.

## Why HTTP

An agent in a sandbox cannot run the server: `raj ctl exec` is refused over TCP by
design and there is no workspace mount, so every build and test was a human round
trip. With `transport :http` the server keeps running where Blender is and the agent
calls it directly — the arrangement the raj editor bridge already uses.

## Server side

```ruby
setting :mcp_token, env: "MCP_TOKEN", secret: true,
        description: "bearer token every request to the HTTP transport must carry"
transport :http, port: 8787, auth_setting: :mcp_token
```

It binds **127.0.0.1 only**; a container reaches it through `host.docker.internal`
(Docker Desktop forwards the host's loopback, confirmed with a plain TCP connect
before building anything). `auth_setting:` must name a `secret:` setting, and a
secret setting cannot be `optional:` — it is either there or the server refuses to
start, stdio included, so every run needs `MCP_TOKEN`. The DSL allows exactly one
`transport`, so adding HTTP replaces stdio rather than joining it: the binary then
listens and never reads stdin, and piping into it simply hangs.

## The two client quirks

**Host header.** rmcp enforces a DNS-rebinding check and answers `Forbidden: Host
header is not allowed` unless `Host` is one it trusts (`127.0.0.1:<port>`,
`localhost`). A client reaching the server from another host must connect to
`host.docker.internal` but present `Host: 127.0.0.1:8787`; `fetch` cannot set `Host`
(it is a forbidden header name), so use `node:http`, or `curl -H 'Host: …'`.

**SSE framing.** Replies are `text/event-stream` whose first `data:` line is empty:

```
data: 
id: 0
retry: 3000

data: {"jsonrpc":"2.0","id":1,"result":{…}}
```

Taking the first `data:` line parses nothing; join every `data:` line, then parse.
`initialize` returns the session id in the `mcp-session-id` response header, and
later requests send it back as `Mcp-Session-Id`; notifications answer `202` with an
empty body. A client that initialises per invocation is fine — sessions are cheap,
and it survives a server restart.

## What needs a save, and what does not

Save then rebuild `blender.rmcp.rb` and `bindings/*.rb`, because the compiler reads
them from disk. `python/mcp_scripts.py` needs a save but no rebuild: the server
reads it from disk on every call, so a saved edit applies at once and nothing
recompiles. `execute_code` payloads need no save at all — the agent reads the file
out of the editor's buffer (`raj ctl read --json F | jq -r .text`) and ships the
text in the request, so an unsaved edit runs immediately. Blender caches an
installed script by module name, so editing a script used to have no effect until
Blender restarted; `run_script` and `run_module` now name the module after a hash of
its text, so a changed script installs fresh with no rebuild and no restart.
`dev.sh` watches the Python too and, on a change, runs `ast.parse` over both files
with the first interpreter that answers — `uv run --no-project python`, then
`python3`, then `python` — proving the runner at startup instead of discovering it
at lint time; no bpy import, no bytecode written.

## How Python reaches Blender, and why the wire carries strings

The addon's protocol has exactly one code-running verb, `execute_code`, whose
parameter is source text. There is no run-this-file command and no file transfer, so
a script has to travel as a string; upstream's own server ships whole script sources
in every call, and ships its scripts twice (a copy in the addon, a copy in the
server package) to do it. Two mechanisms use that channel.

`run_script(host, port, path, NAME, args)` lifts a `NAME = r'''…'''` constant out of
a Python file with `Json.py_constant` and runs its body as `_main()`, arguments in a
module-global `ARGS`. It reaches one file only: upstream's `blender_scripts.py`
(`SCENE_SUMMARY`, `LOOK`, `BOUNDS`), written in that format and not ours to
restructure. `run_module(host, port, path, entry, args)` reads the whole file with
`Json.read_text` and calls `entry(args)` in it as a real module; it carries
`python/mcp_scripts.py`, every script of our own — the text-vision trio and the
twelve scene and output tools (see `docs/text-vision.md`). `compile()` is handed the
file's own path, so a traceback names a line there instead of in a generated string,
and the file can be linted, imported and run alone:
`blender --background --python python/mcp_scripts.py -- reveal '{}'`.

Both install into `sys.modules` under a hash of the text and answer
`__MCP_NEED_INSTALL__` when Blender has not seen that text, so the first call in a
session pays one extra round trip and every later call sends a few hundred bytes.
The rule for new tools: prefer `run_module`, and write real Python returning a dict
with `"report"`.

## The dev loop

`dev.sh` hashes the four sources once a second; on a change it runs `rmcp_dsl check`
(Ruby only, instant), then `rmcp_dsl build`, then restarts the server. A failed check
or build leaves the last good build serving, so a typo never turns into a dead port
mid-loop, and `RAJ_NOTIFY=<key>` sends the failure to an agent's mailbox through
`raj ctl send`. `rmcp_dsl` has no watch mode; `check` is the fast gate and `build`
the slow one — worth keeping separate, since `check` catches most mistakes without
cargo.

## Clients

`mcp.sh` (curl + jq) offers `tool NAME 'JSON'`, `code FILE.py` and `raw FILE`; add
`MCP_HOST_HEADER` when calling across a sandbox boundary. A node variant over
`node:http` covers sandboxes without curl. Both render text blocks as text and
summarise images (`[image image/png 82 KB omitted]`) — the base64 is never useful to
a text agent, and a 78x34 wireframe is ~1 KB against ~80 KB for a screenshot.

## Security

That token is a full-power credential for the machine it points at: `execute_code`
runs arbitrary Python with the user's privileges and can read or write any file the
user can. Keep the port loopback-only (or reachable solely through the host
gateway), rotate the token per session, and never bind it to a shared network. The
blast radius is wider than the raj bridge's for exactly that reason: Blender's
Python is not sandboxed at all.

## What the compiler cannot express

`rmcp_dsl` is the Ruby-ish DSL that generates this server; building
`blender.rmcp.rb` surfaced the defects below, tagged **language** (not expressible
today), **typing** (expressible only through an opaque `Json::Value`), **ergonomics**
(expressible but awkward or poorly explained), **tooling** (the LSP/build workflow),
**codegen** (the quality of the emitted Rust) or **runtime** (the generated server's
behaviour), and ordered by how much each slowed the work. Editor issues from the
same sessions are in `docs/editor-issues.md`.

### 1. `language` — a tool cannot take no arguments

`params` must declare at least one `field`, so an empty argument object is not
expressible (`params :NoArgs do end` answers `needs at least one field`), though
argument-less tools (`ping`, "current time") are common. **Suggest:** allow an empty
`params`, or make `params:` optional.

### 2. `typing` — binding return types have no float (or i32) arrays

`T::Array[Float]` is refused — the allowed binding returns are `String`, `Float`,
`I32`, `I64`, `T::Boolean`, `T::Array[String]`, `T::Array[I64]`, `Json::Value` — so
a numeric array from JSON is opaque and an `:f64_list` output cannot be filled from
a binding at all. **Suggest:** add `T::Array[Float]` (and `T::Array[I32]`,
`T::Array[T::Boolean]`).

### 3. `typing` — no typed record

Rows are reachable today (`Json::Value` plus `wire: true` lets an output field carry
one), but there is no *typed* record — a `record :Row do ... end` for binding returns
and outputs — so schemas and editor types cannot describe a row and
`Html.select`/`Html.attr` stay column-oriented (20 names and 20 links, not 20 rows).
**Suggest:** a record type, or a `rows` helper on the HTML binding.

### 4. `language` — no `nil` literal in a body

An optional output field or "no value" result cannot be produced; the body invents a
sentinel, with `... : nil` an unsupported `NilNode`. **Suggest:** allow `nil` where a
nil-able type is expected, so absent means absent.

### 5. `ergonomics` — `+` will not mix `str` and `String`

A Ruby literal lowers to borrowed `str` and a binding return is owned `String`, so
`"literal" + owned` is `str vs string`; interpolation or `.to_s` works, but nothing
says so. **Suggest:** type literals as `String` at `+`, accept a `Rust::Str(...)`
cast, or hint at the fix.

### 6. `ergonomics` — settings are always strings

Numeric config needs `Integer(setting(:blender_port), 10)`. **Suggest:** a typed
setting (`setting :port, type: :i64`), or `setting(:x).to_i`.

### 7. `ergonomics` — building a JSON request in a body is awkward

A nested request body needs a binding `quote` helper plus interpolation; typed maps
stop short of a nested request object. **Suggest:** `to_json` on maps, or a map/JSON
literal accepted where JSON is expected.

### 8. `language`/`typing` — opaque types do not cross binding modules

A `Value` declared in `bindings/json.rb` cannot be passed to a function in another
binding, so the TCP client had to live in `json.rb` to reuse the type.
**Suggest:** document the one-module rule, or allow a shared/imported opaque type.

### 9. `tooling` — bindings are resolved from disk and cached

`use_bindings` reads `bindings/*.rb` from disk and caches per document, so a binding
saved after the server was first analysed is not picked up until the server document
changes, and an unsaved binding buffer is invisible to both the LSP and
`rmcp_dsl build`. **Suggest:** watch `bindings/` and invalidate on change, and read
it from open buffers so proposals can be checked before saving.

### 10. `ergonomics` — terse type-mismatch messages

`type mismatch: str vs string` names the types but not the fix. **Suggest:** a
trailing hint, as the compiler already gives elsewhere ("did you mean ...", "use
`|| default` ...").

### 11. `codegen` — the settings check can warn (`unused_mut`)

The settings check always emits `let mut missing: Vec<&str>`, so a server whose
settings all have defaults warns `unused_mut` at the generated line. The crate is
meant to be warning-free, so this defeats `-D warnings`/clippy, and it is un-mapable
because `rmcp_dsl.map.json` carries errors, not warnings. **Suggest:** emit `mut`
only when a setting can be missing (or `#[allow(unused_mut)]`), and route warnings
through the map so they name the DSL line.

### 12. `tooling` — the build reads disk, and a stale buffer hides that

`rmcp_dsl build` reads the file **on disk**, so building before saving quietly
compiles the older text while the notices never say which version they read.
`open --create` makes a **buffer**, not a file, so `rust_file "x.rs"` names a missing
path until it is saved; bindings and `rust_file` resolution cache per referring
document; and there is no `read --disk` to see what was compiled (see #13).
**Suggest:** resolve from open buffers or state the on-disk version in the notices,
and add `read --disk`.

### 13. `tooling` — a stale generated buffer shadows reads, and `save --all` clobbers

A generated file held as a buffer from an earlier read keeps the pre-build text
after the next build, and `read`/`search` answer from it, so a driver reads the wrong
build (we nearly filed a non-existent bug). `reload`/`close --discard` are refused
("holds unsaved text written by the user"); worse, `save --all` writes that stale
text back over freshly generated sources. **Suggest:** treat generated paths
specially (reload on change, or refuse to keep them open), and let a driver refresh
text it never wrote.

### 14. `ergonomics` — a large Rust implementation cannot stay in its binding

A binding has no `rust_file`, so a 15-line transport lives as a huge escaped string;
`rust_file` + `rust_fn` restores the real `.rs` file rustc checks, but loses the
typed layer — no nilable or opaque `returns:` (so "no reply" is a sentinel), and the
call moves out of the binding into a body or helper. **Suggest:** allow `rust_file`
at binding level, and a nullable `returns:` such as `:string?`.

### 15. `typing` — binding parameters cannot be nil-able, and list fields take no default

A nilable parameter is refused (`a parameter cannot be nilable yet; return a nilable
value instead`), and a list field cannot take `default:`, so an optional list is
`optional: true` and the body folds nil itself (`Json.str_list_json(targets || [])`).
**Suggest:** allow nilable parameters, or document the `optional: true` + `|| []`
idiom beside the field table.

### 16. `ergonomics` — small body/helper rules that cost a round trip each

Three rules cost a round trip each: `setting(:x)` is body-only, refused in a helper
though the helper section does not say so; block parameters are field names with no
aliasing (`image_ref` → "did you mean image?"), though a field named `image` does
**not** shadow `image(base64, "image/png")`; and locals are checked against Rust
keywords — a good diagnostic, worth keeping.

### 17. `ergonomics`/`codegen` — `||` moves its left operand

`resp = raw || raise("…")` moves `raw`, so a later branch using it is `error[E0382]:
use of partially moved value`; the mapped error names the line but not the fix (make
both branches yield one non-nil value). **Suggest:** borrow at the `||` site, or
name the local the operator consumed.

### 18. `language` — a heredoc is not accepted as a keyword-argument value

A `<<~'TXT'` value before a `do` answers `syntax error: unexpected 'do', ignoring
it`, yet `instructions:` is a page of prose, the keyword most likely to want one.
**Suggest:** accept `<<~` (and for other string-literal keywords), or state in the
grammar that a string literal is the only form.

### 19. `codegen` — `W-STR-STRIP-RUBY` fires on `.strip`

`ruby strip ... compiles to an explicit-set trim, not Rust trim()` is emitted for
ordinary `.strip` calls even though the emitted trim is correct — noise an author
cannot act on (the same family as #11). **Suggest:** keep it silent when the
semantics coincide, or make it a notice.

### 20. `runtime` — `transport :http` trusts loopback only, and nothing can change that

The HTTP transport exists so an agent off the machine can reach the server, yet it
binds `127.0.0.1` and rmcp's host check refuses any non-loopback `Host`. Real clients
send the URL's own authority, so a client on the host works but one across a
boundary cannot; there is no `allowed_hosts:` and no bind address. Verified with one
`initialize`, changing only `Host`: `host.docker.internal:8787` → 403, while
`127.0.0.1:8787` and `localhost:8787` → 200. **Suggest:** an `allowed_hosts:`
keyword (seeding rmcp's check) and/or a `bind:` address; the bearer token is already
the authentication story, and the browser-oriented check is the wrong default for a
token-bearing service meant to be reached from elsewhere.

### 21. `language` — a `String` local cannot be borrowed or cloned

A `String` local moved on one branch and read on another is `error[E0382]: borrow of
moved value`. The DSL has no `.clone`/`.dup` and no borrow syntax, so the remedy is
to restructure so each local is moved on one path and read once on any path.
**Suggest:** allow `.clone`/`.dup`, or document the rule beside #17, the same move
semantics seen through `||`.

### 22. `codegen` — a cast operand is parenthesised, and rustc says so

`handle[provider.length + 1, …]` emits
`ck_add_i64((provider.chars().count() as i64), 1, …)` and rustc warns `unnecessary
parentheses around function argument`, naming the DSL line and helper. Hoisting the
length into a local avoids the cast and, we believe, the warning — unconfirmed.
**Suggest:** do not parenthesise a cast operand in a call argument.

### 23. `language` — no exception handling, so retries are written as values

There is no `begin`/`rescue` and no `catch`, and `.each` cannot carry state between
iterations, so a fallback cannot be control flow. It is written as values instead:
`a = attempt(a); b = if a == "" then attempt(b) else "" end`, unrolled, with a
non-raising variant of every helper that needs one. This surfaced on `generate_3d`'s
`auto` choice, where an `enabled` provider (Hunyuan3D) had nothing listening and a
fallback should have moved on. **Suggest:** document "failures are values, not
exceptions" as *the* retry pattern, or allow a `rescue`-like form.

### 24. `runtime` — one transport per server, so stdio and HTTP cannot coexist

A file may declare exactly one `transport`, so stdio and HTTP cannot both be served
without a shim that speaks the other one and forwards — a second implementation of a
protocol this project already implemented once. **Suggest:** accept a list
(`transport :stdio, :http`) or a second declaration; failing that, a generated
stdio↔http bridge.

### 25. `ergonomics` — the required-list diagnostic does not say "required"

When the left operand of `||` is a required `Vec<String>`, `names || []` answers `an
array literal needs at least one element` instead of saying `names` is not nilable —
which is the actual information. **Suggest:** say it ("`names` is not nilable, so
`||` gives `[]` no element type; drop the fallback").

### 26. `ergonomics` — a body-shape error names the statement, not the cause

An unbalanced `end` one tool above surfaced as `unsupported CallNode as a statement
(only `name = expr`, a guard clause, ... before the last expression)` inside the
wrong body. **Suggest:** when a body contains a construct that only belongs at the
top level, name the still-open `tool :x` and the line it opened at.

### 27. `tooling` — a binding that is never loaded fails as a missing crate, two steps later

A `bindings/*.rb` that no `use_bindings` names is never parsed, so its crates never
reach `Cargo.toml` and the failure surfaces two steps later as `cannot find module
or crate 'image'` in a `rust_file` — aimed at the injected file, while the LSP says
`ok`. "Loaded but unused" is already a clear check-time error; only "never loaded"
is silent. **Suggest:** warn when a `bindings/` `.rb` beside the DSL file is named by
no `use_bindings`: "its crates are not declared".

### 28. `tooling` — the `rust_fn` name *is* the Rust function's name, and no reference says so

`rust_fn :image_numbers, from: :textvision` emits `textvision::image_numbers(...)`,
so the module must define exactly that name; it defined `numbers` and the build
answered `cannot find function 'image_numbers'`. The rule — the declared name is the
function to look for inside `from:` — is in no reference, which is why the fix was a
rename and no archaeology. **Suggest:** state the mapping where `rust_fn` is
declared.

### 29. `tooling` — the compiler knows its inputs and does not say what they are

A watcher must know every file a build reads — the DSL, each `use_bindings`, each
`rust_file`. Ours was hand-written and wrong twice in one day (`blender_gen.rs`, then
`textvision.rs`), failing silently: a stale `cargo test` reports old assertions
failing with old messages, `Finished in 0.36s` the only clue nothing recompiled. The
compiler knows the set and hashes it anyway. **Suggest:** print the input paths on a
successful build, one per line, or add `--print-inputs`.

### 30. `tooling` — checked arithmetic is emitted with redundant parentheses

A cast inside a checked operation is emitted parenthesised inside the call, so
rustc prints three `unused_parens` warnings: ``ck_sub_i64((word.chars().count() as
i64), 1, "blender.rmcp.rb:160:22 in helper `gen_default_name`")`` at `main.rs:1524`,
and the same shape for `gen_wait` at 1582 and 1584. The brackets belong to the
compiler, not to the DSL author, so the warning points at a file nobody edits and
nothing in it can be acted on. **Suggest:** drop the operand's own parentheses when
it is already parenthesised, or allow the lint inside generated code.

### Confirmed working, worth not breaking

A missing `output:` is caught at check time, naming the statement, the type and the
fix; five tools missing it were found before any build. rustc errors map back to the
Ruby line and helper, turning a move error into a two-line fix instead of
archaeology. `check` is separate from `build` and fast enough for every change; a
watcher that keeps the old server alive when `check` fails turned three would-be
outages into log lines. Checked arithmetic carries a source tag, so a generated
panic names the DSL line and helper. An array of content blocks emits both
(`"types":["image","text"]`), and a param named `image` does not shadow `image(...)`.
A `rust_file` + `rust_fn` whose parameters are `impl AsRef<str>` compiles and runs —
`AsRef` sidesteps whether the call site passes `&str` or `String`. And a typed list
reaches a Python script: `views: ["front","right"]` arrived as a JSON array and the
script reported exactly those two, while omitting `views` produced its four
defaults.
