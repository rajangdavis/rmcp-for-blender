# Blender MCP

An MCP server that drives the user's live Blender. Python runs inside Blender
with the full `bpy` API, and the tools answer with what a text model can read:
JSON facts, a wireframe drawn as text, an image reduced to a tone grid. A human
client gets the picture itself as truecolour blocks.

The server is a Rust binary built from a Ruby(ish) DSL. Everything the MCP client
sees — the 29 tools, their parameter schemas, their descriptions — is declared
in `blender.rmcp.rb`, and `rmcp_dsl` turns that into the crate under
`build/blender.rmcp/`. The tools reach Blender through the vendored
`mcp-for-blender` addon's socket, the same bridge the upstream Python server
uses.

```
MCP client ──HTTP(:8787)──> blender (Rust) ──TCP(:9876)──> addon ──> Blender
```

## Requirements

- **Blender**, with the vendored addon (`vendor/mcp-for-blender`) enabled and its
  socket server started; it listens on 9876 by default.
- **Rust/cargo** — the crate is Rust 2021 and pins `rmcp =3.5.0`.
- **`rmcp_dsl`** on `PATH` — the compiler that generates the crate.
- **`curl` and `jq`** for `mcp.sh`; optionally **`uv`/`python3`** for the lint.
- **A token.** `MCP_TOKEN` is a required `secret:` setting: the server refuses to
  start without it, stdio included.

## Build and run

```sh
export MCP_TOKEN=$(openssl rand -hex 16)

rmcp_dsl check blender.rmcp.rb     # Ruby only, instant: catches most mistakes
rmcp_dsl build blender.rmcp.rb     # generates src/ and runs cargo

./build/blender.rmcp/target/debug/blender
```

The binary only listens — the DSL allows exactly one transport and it is HTTP —
so it never reads stdin, and piping into it hangs.

With the server up:

```sh
MCP_TOKEN=$MCP_TOKEN bash dev/mcp.sh tools
MCP_TOKEN=$MCP_TOKEN bash dev/mcp.sh tool scene_info '{}'
MCP_TOKEN=$MCP_TOKEN bash dev/mcp.sh code /tmp/probe.py   # run Python in Blender now
```

`mcp.sh tool` prints text results as text and reduces an image to
`[image image/png 82 KB omitted]`: a text agent never wants the base64, and a
78x34 wireframe costs about 1 KB against about 80 KB for a screenshot.

`smoke.sh` exercises every tool and checks the shape of each reply:

```sh
MCP_TOKEN=$MCP_TOKEN bash dev/smoke.sh          # hermetic: reads, refusals, error paths
MCP_TOKEN=$MCP_TOKEN bash dev/smoke.sh --full   # adds a probe object, then cleans up
```

Neither run calls `generate_3d`, `make_3d` or `import_asset`: they spend money or
download, and a smoke test has to be safe to run on a whim.

## Development loop

```sh
MCP_TOKEN=$MCP_TOKEN bash dev/dev.sh
```

`dev/dev.sh` hashes the DSL, the bindings and the Rust once a second. On a change it
runs `rmcp_dsl check` (fast, Ruby only), then `build`, then restarts the server
and asks the port whether the new build is actually listening. A failed check or
build leaves the last good build serving, so a typo never becomes a dead port for
a client mid-loop. `RAJ_NOTIFY=<key>` sends failures to an agent's mailbox.

## The tools

**Scene and inspection** — `scene`, `scene_info`, `object_info`, `mesh_report`,
`wireframe`, `reveal`

**Building and changing** — `text`, `place`, `material`, `remove`, `duplicate`,
`array`, `boolean`, `modifier`, `aim`, `light`

**Seeing** — `screenshot`, `look`, `image_report`, `image_report_rust`,
`image_view`

**Output** — `render`, `export`

**Assets and generation** — `search_assets`, `import_asset`, `generate_3d`,
`make_3d`

**Escape hatches** — `execute_code`, `command`

`rmcp-blender-skills/SKILL.md` is the agent-facing guide; the full descriptions live in
`blender.rmcp.rb`, where they are written.

## Layout

| path | what it is |
| --- | --- |
| `blender.rmcp.rb` | the whole surface in the DSL: settings, params, helpers, the 29 tools, the HTTP transport |
| `rust/blender_bridge.rs` | the addon's socket client: one connection, one command at a time, replies read until they parse |
| `rust/blender_gen.rs` | helpers the DSL cannot express — `sleep_ms`, base64 image reads, Rust trim |
| `rust/textvision.rs` | image arithmetic — `numbers`, `grid`, `ansi` — unit-tested with `cargo test` |
| `bindings/*.rb` | crate declarations (`json`, `imagefile`) and the Rust-backed helpers they expose |
| `python/mcp_scripts.py` | the Blender-side scripts our tools run, one function per entry point |
| `vendor/mcp-for-blender/` | the addon, vendored |
| `build/blender.rmcp/` | the generated crate: `src/main.rs` from the DSL, the `.rs` files copied in |
| `dev/dev.sh`, `dev/mcp.sh`, `dev/smoke.sh` | watch/restart loop, curl client, 29-tool harness |

## Where a change goes

| you changed | save? | rebuild? |
| --- | --- | --- |
| `blender.rmcp.rb`, `bindings/*.rb` | yes | yes — the compiler reads disk |
| `rust/*.rs` | yes | yes — copied in at build time |
| `python/mcp_scripts.py` | yes | no — the server reads it per call |

Per call, the server ships `python/mcp_scripts.py` to Blender once per content
hash and then names the module, so from the second call on the wire carries a few
hundred bytes. The same trick covers the addon's own `blender_scripts.py`, which
`run_script` reaches for `SCENE_SUMMARY`, `LOOK` and `BOUNDS`.

There are two ways into Blender on purpose: `run_script` for upstream's file,
`run_module` for ours. A new tool belongs in `python/mcp_scripts.py` as a real
function returning `{"report": ...}`, and can be run with no server at all:

```sh
blender --background --python python/mcp_scripts.py -- reveal '{"name": "Chair"}'
```

## Seeing, for two different readers

- `image_report` (Python, inside Blender) and `image_report_rust` (Rust, no
  Blender session needed) read an image **as text**: dimensions, mean, a palette,
  a tone grid, a hue-and-strength grid, a spectrum ordered by hue, and a summary
  that names what is in the picture and where. Put one image through both and the
  first lines should agree.
- `image_view` is the picture itself, in truecolour ANSI, and it is for a
  **human**. `half` stacks two samples per cell with two colours; `braille`
  spends a 4x2 dot grid on one glyph for four times the vertical detail; `blend`
  adds a second colour for the lit dots and the gaps. Dithering is `diffusion`
  (Floyd-Steinberg), `ordered` (Bayer 4x4) or `threshold`. A text model reads
  characters, not dots: it wants the reports.

## Security

`MCP_TOKEN` is a full-power credential for the machine it points at.
`execute_code` runs arbitrary Python with the user's privileges and can read or
write any file the user can, and Blender's Python is not sandboxed at all. Keep
the port loopback-only — or reachable solely through the host gateway — rotate
the token per session, and never bind it to a shared network.

## Known limits

- **The Host header.** rmcp enforces a DNS-rebinding check. The transport answers
  it: `allowed_hosts:` lists the exact `Host` names trusted, and it *replaces* the
  loopback defaults, so include them — `["host.docker.internal", "127.0.0.1", "localhost"]`.
  A client
  reaching the server at that name is accepted (verified: allowed `Host` -> 200, an
  unlisted one -> 403). Only a server without `allowed_hosts:` needs a hand-written
  client to present `Host: 127.0.0.1:8787` (`fetch` cannot set it, so use `curl -H`
  or `node:http`; `dev/mcp.sh` takes `MCP_HOST_HEADER`).
- **Replies are SSE**, and the first `data:` line is empty — join every `data:`
  line before parsing. `initialize` returns the session id in a response header.
- **Generation is unproven end to end.** Tripo wants Premium, the Rodin trial key
  reports `API_INSUFFICIENT_FUNDS`, and Hunyuan3D's local API refuses
  connections. The tools are wired and hand back a job handle; the success path
  has not been observed.
- **One transport.** Adding HTTP replaced stdio rather than joining it.
- Captures and renders write real files, and `undo` is the whole file's history —
  which is why there is deliberately no undo tool. See `docs/blender-notes.md`.

## Docs

- `docs/build-and-transport.md` — the transport, the two client quirks, what needs a save, the dev loop, and the compiler's gaps
- `docs/blender-notes.md` — Blender traps that cost round trips, and the tool surface against the upstream Python server
- `docs/text-vision.md` — the text-vision design and its numbers
- `docs/editor-issues.md` — defects found in the editor while building this
- `rmcp-blender-skills/SKILL.md` — the agent-facing guide to the tools
