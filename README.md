# Blender MCP

An MCP server that drives the user's live Blender. Python runs inside Blender
with the full `bpy` API, and the tools answer with what a text model can read:
JSON facts, a wireframe drawn as text, an image reduced to a tone grid. A human
client gets the picture itself as truecolour blocks.

The server is a Rust binary built from a Ruby(ish) DSL. Everything the MCP client
sees — the 27 tools, their parameter schemas, their descriptions — is declared
in `blender.rmcp.rb`, and `rmcp_dsl` turns that into the crate under
`build/blender.rmcp/`. The tools reach Blender through our own add-on,
`addon/mcp_bridge.py`: a token-guarded loopback socket that runs this server's
Python modules on Blender's main thread and nothing else.

```
MCP client ──HTTP(:8787)──> blender (Rust) ──TCP(:9876, token)──> MCP Bridge add-on ──> Blender
```

## Requirements

- **Blender 4.2 or later**, with `addon/mcp_bridge.py` installed (Edit → Preferences →
  Add-ons → Install from Disk) and enabled, and started from the 3D viewport sidebar
  (N → MCP); it listens on 127.0.0.1:9876. Disable the old "MCP for Blender" add-on
  first: both want that port. The first start prints where the bridge token file
  is; start the server with `BLENDER_BRIDGE_TOKEN="$(cat <that file>)"`.
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

Nothing either run calls spends money or downloads, so both are safe to run on a
whim.

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

**Output** — `render`, `render_animation`, `export`

**Assets** — `search_assets`, `import_asset`: Poly Haven (no account), Sketchfab
and Poly Pizza (API keys in the server's environment as
`BLENDERMCP_SKETCHFAB_API_KEY` and `BLENDERMCP_POLYPIZZA_API_KEY`). The server does
every download, into `downloads/` under the first write root; Blender only imports
the files, packs the images and deletes the folder.

**Escape hatch** — `execute_code` (guarded: held to the file roots, see Security)

3D generation (`generate_3d`, `make_3d`) is out until it is ported to this server.

`rmcp-blender-skills/SKILL.md` is the agent-facing guide; the full descriptions live in
`blender.rmcp.rb`, where they are written.

## Layout

| path | what it is |
| --- | --- |
| `blender.rmcp.rb` | the whole surface in the DSL: settings, params, helpers, the 27 tools, the HTTP transport |
| `rust/blender_bridge.rs` | the add-on's socket client: one connection, one command at a time, the token on each, replies read until they parse |
| `rust/blender_gen.rs` | Rust trim, which the DSL cannot express idiomatically |
| `rust/blender_jail.rs` | the path jail: every file path a tool takes, resolved and held to the roots |
| `rust/blender_assets.rs` | Poly Haven, Sketchfab and Poly Pizza: search, and downloads into a folder under the write roots |
| `rust/textvision.rs` | image arithmetic — `numbers`, `grid`, `ansi` — unit-tested with `cargo test` |
| `bindings/*.rb` | crate declarations (`json`, `imagefile`) and the Rust-backed helpers they expose |
| `python/mcp_scripts.py` | the Blender-side scripts our tools run, one typed function per entry point |
| `python/mcp_guard.py`, `python/safe_mode.py` | the guard around `execute_code`, and upstream's validator it runs first |
| `addon/mcp_bridge.py` | the Blender add-on: the token-guarded socket, `ping` and `execute_code` only |
| `vendor/` | local reference copies of upstream projects; not tracked, not read at runtime |
| `build/blender.rmcp/` | the generated crate: `src/main.rs` from the DSL, the `.rs` files copied in |
| `dev/dev.sh`, `dev/mcp.sh`, `dev/smoke.sh` | watch/restart loop, curl client, 27-tool harness |

## Where a change goes

| you changed | save? | rebuild? |
| --- | --- | --- |
| `blender.rmcp.rb`, `bindings/*.rb` | yes | yes — the compiler reads disk |
| `rust/*.rs` | yes | yes — copied in at build time |
| `python/mcp_scripts.py` | yes | no — the server reads it per call |

Per call, the server ships `python/mcp_scripts.py` to Blender once per content
hash and then names the module, so from the second call on the wire carries a few
hundred bytes. `scene_info`, `look` and the generators' bounds check run from it
too (`scene_summary`, `look`, `bounds`); nothing is read from the vendored
package's `blender_scripts.py` any more.

There is one way into Blender for our scripts: `run_module`. A new tool belongs
in `python/mcp_scripts.py` as a real
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

`MCP_TOKEN` is a credential for the machine it points at. Keep the port
loopback-only — or reachable solely through the host gateway — rotate the token
per session, and never bind it to a shared network.

Files are scoped by two lists, each written like `PATH`:

| variable | default | what it allows |
| --- | --- | --- |
| `BLENDER_WRITE_ROOTS` | `.`, the directory the server runs in | writes and reads; relative paths and the default `renders/` and `exports/` folders land under the first |
| `BLENDER_READ_ROOTS` | empty | reads only, such as a texture library or `/System/Library/Fonts` |

Every tool that takes a file path resolves it in `rust/blender_jail.rs`, with
symlinks followed, and refuses it outside those lists. The add-on runs only the
server's own modules: it has no command that takes a path or a URL.

`execute_code` runs under `BLENDER_CODE_POLICY`:

- `guarded` (the default): upstream's validator refuses `os`, `open`,
  `subprocess`, sockets, `ctypes`, `numpy` and persistence. Then
  `python/mcp_guard.py` holds every path the code hands Blender to the same
  lists, and an audit hook refuses directory listings, file access, processes
  and network outside them while agent code runs.
- `open`: the code runs unchecked, as the user, with the whole filesystem in
  reach.
- `off`: refused.

The guard is a guardrail, not a sandbox: Blender's C code does file I/O the hook
cannot see. `docs/blender-sec.md` has the threat model, what the guard misses,
and the OS sandbox that would seal it.

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
- **One transport.** Adding HTTP replaced stdio rather than joining it.
- Captures and renders write real files, and `undo` is the whole file's history —
  which is why there is deliberately no undo tool. See `docs/blender-notes.md`.

## Docs

- `docs/build-and-transport.md` — the transport, the two client quirks, what needs a save, the dev loop, and the compiler's gaps
- `docs/blender-notes.md` — Blender traps that cost round trips, and the tool surface against the upstream Python server
- `docs/text-vision.md` — the text-vision design and its numbers
- `docs/editor-issues.md` — defects found in the editor while building this
- `rmcp-blender-skills/SKILL.md` — the agent-facing guide to the tools

## Credits

Three MIT-licensed works shape this server. Local reference copies sit under
`vendor/`, which is not tracked; where code is copied into this repository, its
license travels with it.

### mcp-for-blender — MIT © 2025 Siddharth Ahuja

The original Blender add-on and socket bridge. `addon/mcp_bridge.py` replaces it,
keeping its wire protocol and bridge-token scheme, and its `list_scene_items`,
`get_object_info` and `get_viewport_screenshot` commands were ported into
`python/mcp_scripts.py` (`scene_items`, `object_info`, `viewport_screenshot`). Its `SCENE_SUMMARY`, `LOOK` and `BOUNDS` scripts were ported into
`python/mcp_scripts.py` (`scene_summary`, `look`, `bounds`), so the server no longer
reads `src/blender_mcp/blender_scripts.py`. Its validator, `safe_mode.py`, is copied
unmodified to `python/safe_mode.py` with its license, and guarded `execute_code` runs
it before the guard in `python/mcp_guard.py`; nothing is read from `vendor/` at
runtime.

### blender-skills — MIT © 2026 blender-skills contributors (v1.3.0)

Techniques adapted into `docs/techniques.md`; source paths there under
"From blender-skills". The skills mined: `lighting`, `materials`, `compositing`,
`rendering`, `geometry-nodes`, `animation`, `camera-cinematography`, `vfx-fx`;
the `stylized-style`, `neon-retrofuturism` and `dream-surreal-mood` mood/palette
guides; the `blender-director` orchestration skeleton; and the shared
`references/` docs and checklists.

### blenderwright — MIT © 2026 HoldMyBeer-gg

Ideas adapted into `docs/techniques.md`; source paths there under "From blenderwright". Items:
the `render_animation` + Sequencer video-encode approach (`tools/rendering.py`,
`tools/sequencer.py`); the procedural-material builder and ColorRamp control
(`tools/materials.py`); `sweep_profile_along_path` (`tools/sweep.py`); the
interpolation / follow-path notes (`tools/animation.py`); the
`animation_turntable`, `lighting_principles`, `studio_lighting_setup` and
`auto_critique_workflow` prompts; and the fast OpenGL viewport-capture idea. The
encode recipe there is the basis for the planned typed `render_animation` tool.

