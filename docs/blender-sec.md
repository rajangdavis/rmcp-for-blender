# Blender MCP security: what an agent can reach, and the fix

Found on 2026-10-08, during a session where an agent (Claude, in a container) drove
Blender through this server. The short version: **any process that can open a TCP
connection to the Mac's localhost:9876 can run arbitrary Python in the user's Blender,
as the user**. That includes agents in Docker/Lima containers, and no MCP server or
token is involved. Through that Python, an agent can read and write anything the user
can, run programs, and reach the network.

The owner's requirement, as stated in the same session (2026-10-08): "agents shouldn't have
write access on the host", and "you shouldn't have any ability to write files outside
of what my sandbox has for you".

## How the stack is wired

```
agent ──HTTP :8787──> Rust MCP server ──TCP :9876──> addon ──> exec(code) in Blender
        MCP_TOKEN checked here           nothing checked here
```

`MCP_TOKEN` guards the HTTP side only. The hop to the addon had no authentication at
all.

## Findings (with evidence)

### F1. The addon socket is unauthenticated and reachable from containers

- `vendor/mcp-for-blender/addon.py` `_handle_client` (about line 1422): `json.loads` the
  bytes and queue the command. There is no credential of any kind.
- `addon.py` `execute_code` (about line 2238): `exec(code, namespace)`. Its own comment
  reads "This is powerful but potentially dangerous".
- The socket binds `localhost`, but Lima's user-mode network (host address
  `192.168.5.2`) and Docker Desktop's `host.docker.internal` both forward container
  traffic to the host's loopback. "Bound to localhost" does not mean "local processes
  only".
- Verified from inside the agent container with no token: `{"type":"ping"}` →
  `{"status": "success", "result": {"pong": true}}`, and a print-only `execute_code`
  returned `blender 4.2.18 LTS | running as rajandavis | scenes ['CLAUDE_island', 'Scene']`.

### F2. `execute_code` is full user-level access

Agent Python runs inside Blender's process as the user. In the session, it:

- wrote files outside any sandbox: `~/Desktop/claude-island-build.py`,
  `~/Desktop/claude-island*.png` (via `bpy.ops.render.render(write_still=True)`),
  `/tmp/claude_*.png`, `/tmp/ck.png`, and a copy into this repo
  (`docs/scene-craft-island.py`) that skipped raj review;
- listed `/System/Library/Fonts`, `/Library/Fonts` and `~/Library/Fonts`, and loaded
  fonts from them.

What else is reachable in principle, but was **not** tested: dotfiles (`~/.ssh`,
`~/.aws`), the repo's `.mcp-token`, API keys in Blender's preferences, `subprocess`,
the network, and persistence through `bpy.app.timers`/handlers or Blender startup
scripts. macOS TCC still gates Desktop, Documents, Downloads, Mail, Messages and
Photos per app. Blender had evidently been granted Desktop access, since the writes
worked. Everything outside TCC-protected folders is open.

### F3. Typed tools take unrestricted paths

| tool / param | direction | where |
|---|---|---|
| `render.file` | write | `python/mcp_scripts.py` `render`; unset → beside the .blend or **the Desktop** |
| `export.file` | write | `python/mcp_scripts.py` `export` |
| `look.image` | read (pixels returned) | via Blender |
| `image_report.source` | read | via Blender |
| `image_report_rust.source`, `image_view.source` | read | Rust `textvision.rs` on the server host |
| `generate_3d.image` | read **any file as raw bytes and upload it to a third party** | Rust `gen_file_base64` (`rust/blender_gen.rs`) |

### F4. `command` is a raw passthrough

`blender.rmcp.rb` `tool :command`: its enum includes `execute_code`, `export_scene`,
`download_*` and `set_texture`, and the request is built as
`"{\"type\":\"#{name}\",\"params\":#{args}}"`. In that string, `args` is spliced in as
raw JSON text and never checked.

### F5. Upstream has the same exposures

The vendored upstream server says so itself (`src/blender_mcp/safe_mode.py`):

> `execute_code` on the Blender socket is arbitrary code execution inside the user's
> Blender process — that is the product feature, so by default nothing is validated.

Its `BLENDER_MCP_SAFE_MODE=1` is an AST validator with three limits:
- **opt-in;**
- **MCP path only** ("the addon's socket accepts a raw `execute_code` from any local
  process, so this guard covers the MCP path only");
- **explicitly allows file I/O through `bpy`:** saving, rendering, and every
  import/export, to any path.

It is aimed at prompt injection, not at confining file access.

## The fix, in layers

Each layer closes a route the others can't.

### L0: bridge token on the addon socket (proposed)

Every request to the addon must carry a shared secret, so the MCP server is the only
client that can use Blender.

Update 2026-10-09: the vendored add-on is replaced by our own,
`addon/mcp_bridge.py`. It keeps the same token scheme (`BLENDER_BRIDGE_TOKEN`, or
the 0600 `mcp_bridge_token` file in Blender's config folder) and wire protocol,
and adds two limits. It accepts only `ping` and `execute_code`, so every tool runs
through the server's own modules. And a connection may send at most 1 MiB
before its first request proves the token. The steps below describe the
vendored add-on as first patched.

- **Addon** (`vendor/mcp-for-blender/addon.py` and the identical
  `src/blender_mcp/bundled/addon.py`):
  - `_load_bridge_token()` reads `BLENDER_BRIDGE_TOKEN`, or the `0600` file
    `<Blender config dir>/mcp_bridge_token`, which it creates with
    `secrets.token_hex(32)` on first start and prints the path.
  - `start()` loads the token before binding and refuses to start without one.
  - `_handle_client` pops `"token"` from every request, compares it with
    `hmac.compare_digest`, and on mismatch replies `{"status":"error","message":"unauthorized"}`
    and drops the connection.
- **Rust bridge** (`rust/blender_bridge.rs`): `bridge_token()` reads
  `BLENDER_BRIDGE_TOKEN` once, and `with_token()` adds it to every request. With no
  token, the request is never sent (fail closed). It's read in Rust rather than through
  a DSL `secret:` setting because a secret setting may only be passed directly to a
  `rust_fn`, and every caller of `blender_call` is a helper.
- **Per-call timeout, and a timeout that says so (plan item B, 2026-10-10):**
  `blender_call` still keeps one connection and still never resends a command that
  was written, but it now waits under a per-call read timeout: a 60 s default, and a
  caller-supplied one for `render`, `render_animation` and `import_asset` (their
  `timeout_seconds` field) through `blender_call_timeout` and `run_module_timeout`.
  A timeout is reported as `{"status":"timeout", ...}` whose message says the
  operation may still have run and was not resent, and a follow-up `ping` on a fresh
  connection says whether Blender answered; the empty string still means "unreachable
  or no reply", so "may still be running" is never confused with "gone". Each call
  logs its duration and outcome to stderr.
- **`blender.rmcp.rb`:** the "bridge unreachable" error now names `BLENDER_BRIDGE_TOKEN`.

Deploy:

1. Accept and save the proposals.
2. Reload the addon in Blender (disable/enable, or restart Blender), then start its
   server. It prints the token file's path.
3. Rebuild and restart the server:
   `rmcp_dsl build blender.rmcp.rb`, then
   `BLENDER_BRIDGE_TOKEN="$(cat '<that path>')" MCP_TOKEN=... ./build/blender.rmcp/target/debug/blender`.
4. Verify: the unauthenticated `ping` from a container must now return
   `unauthorized`, while the MCP tools keep working.

`dev/mcp.sh` and `dev/smoke.sh` talk to the MCP server, not the addon, so they need no
change beyond the server's environment.

### L1: path jail and `command` trim (proposed 2026-10-09)

This layer lives in `blender.rmcp.rb`, not the addon, because only the server can
tell a typed tool from an agent's own code. Every typed tool reaches the addon as
an `execute_code` request (`run_module` installs `python/mcp_scripts.py` through
it), so the addon sees one request type for both. L0 decides who may talk to
Blender; L1 and L2 decide what an authorised agent may do.

- **Two root lists**, each written like `PATH` (`:` between entries, `;` on
  Windows):
  - `BLENDER_WRITE_ROOTS`: where tools and code may write, and read. It defaults to
    `.`, the directory the server runs in (this repo under `dev/dev.sh`), the only
    host directory mapped into the agent sandbox.
  - `BLENDER_READ_ROOTS`: extra directories that may be read but not written,
    such as a texture library or `/System/Library/Fonts`. It is empty by default.

  Widening access is a matter of adding a directory to one of them; there is no
  switch that turns the roots off.
- **Every path parameter is resolved in Rust** (`rust/blender_jail.rs`,
  `jail_path`): `~` expanded, a relative path taken under the first write root,
  the longest existing prefix canonicalized (so symlinks are followed and a
  dangling one is refused), `..` in a part that does not exist yet refused, and the
  result refused unless it sits under a root of the right kind. A read must be an
  existing file. Blender and the Rust readers get the resolved path, never the one
  the agent wrote. This covers `image_view`, `image_report_rust`, `image_report`,
  `look` (image mode), `render`, `render_animation` and `export`. An image parameter with no `/` or `~` is a datablock name
  and goes to Blender as is; the Python side now loads from disk only an absolute
  path. The file uses only the standard library and builds on Unix and Windows;
  its symlink tests run on Unix.
- **Default outputs land under the first write root:** `renders/` for `render`
  and `render_animation`, `exports/` for `export`. The Desktop fallback stays only
  for a direct call that passes no folder.
- **`command` is gone** with the vendored add-on, and so is 3D generation, until
  it is ported to this server.
- **The asset tools are back (2026-10-09), ported so Blender stays offline.** Every
  network call and download runs in the server (`rust/blender_assets.rs`), with
  the Sketchfab and Poly Pizza keys read from its environment, so agent code in
  Blender cannot read them. Downloads land in a fresh `mcp-asset-*` folder under
  the first write root's `downloads/`. File names the APIs supply (Poly Haven
  includes, Sketchfab archive entries) are refused if they would leave that
  folder. Blender imports, packs the images and deletes the folder.
- **Not done, deliberately:** `render` still writes a file, now under the roots,
  rather than returning the image. Its contract is "a file the user keeps".
- **Residual:** the check and the use are separate steps (a symlink swapped in
  between them wins), and the jail is only meaningful while Blender runs on the
  server's machine (`BLENDER_HOST` local). `.mcp-token` sits in the repo root,
  inside the default write root: move it out.

### L2: the guard on agent Python (proposed 2026-10-09)

`BLENDER_CODE_POLICY` sets how `execute_code` runs. The owner, 2026-10-09: "I would
like to just not have agents be able to do full filesystem scans or limit what kind
of escapes they have to run random code on my filesystem."

- `guarded`, the default: the three steps below.
- `open`: the old behaviour, unchecked, as the user. Only for a session the user
  chose to open.
- `off`: refused.

Guarded code goes through three steps, each covering what the one before cannot
see:

1. **Upstream's validator**, `python/safe_mode.py`: mcp-for-blender's
   `src/blender_mcp/safe_mode.py` copied unmodified with its MIT notice, installed
   into Blender by `run_module` and called as `is_safe`.
   It refuses the raw escapes: imports beyond `bpy`, `bmesh`, `mathutils` and
   pure-Python helpers (so no `os`, `sys`, `subprocess`, `socket`, `ctypes` or
   `numpy`), `open`/`eval`/`exec`/`compile`/`__import__`, the dunder ladder,
   computed `getattr` names, handlers, timers, drivers, `register_class`, text
   datablocks and external .blend loading.
2. **A rewrite of the code** (`python/mcp_guard.py`, `_Paths`). It covers what that
   validator allows on purpose: Blender's own file I/O, which runs in C and raises
   no audit event.
   - Every path keyword on any call (`filepath`, `directory`, `filename`) gets a
     runtime roots check. So does the first argument of `load`, `save`,
     `save_render` and `save_as`, and every value assigned to `filepath`,
     `filepath_raw`, `base_path`, `directory` or `cache_directory`. A call whose
     dotted name says export, save, write, bake or unpack is held to the write
     roots.
   - Refused outright: a save with no path (it would write over the image's own
     file or the open .blend), aliases of the path-taking calls, `*args`,
     `**kwargs` and `files=`, unpacking, `save_all_modified`, `save_userpref`,
     draw handlers, `msgbus` and disk caches.
   - Every render is preceded by a check of the outputs it will write:
     `scene.render.filepath` with `write_still` or `animation`, and the
     compositor's File Output nodes.
3. **An audit hook** (PEP 578), installed once per Blender process. Whenever a
   frame of agent code (compiled as `<mcp-agent>`) is on the stack, it refuses
   `open`, `listdir`, `scandir`, `remove`, `rename`, `mkdir` and the other file
   events outside the roots. Reads may also reach Blender's own Python and data
   folders; the user config folder, which holds the bridge token, is excluded.
   It also refuses every process, network, `ctypes`, thread, `gc` and
   interpreter-hook event. It catches the Python inside `bpy` that the other two
   steps cannot see: `bpy.path.module_names` lists a directory through
   `os.listdir`, and the glTF and FBX add-ons write through `open`.

**Residual, stated honestly:**
- Blender's C code reads and writes without audit events, so step 2 is static
  analysis and can miss a route.
- Simulation bakes and autosave compute their write paths inside Blender.
- A change to the hook's own code takes effect after Blender restarts.
- The validator refuses `numpy`, which some scripts used.

It is a guardrail against an agent scanning or writing where it should not, not a
seal against one that sets out to escape. L3 is the seal.

### L3: OS sandbox (optional, the airtight one)

Run a separate, agent-only Blender under macOS `sandbox-exec`. It denies `file-write*`
except the roots, the temp directory and Blender's config directory, and the kernel
enforces it, whatever code runs. It must deny `file-read*` too, outside the roots,
Blender's install and config and the system libraries: with `execute_code` on, a
filesystem scan is a read, and a write-only profile leaves it open. Run the Rust
server under the same profile, since `image_view` and friends read in its process. The owner's everyday Blender keeps the addon off and
stays unrestricted.

## Until this ships

- **Stop the addon's server** (3D viewport sidebar → MCP for Blender) whenever no agent
  is working. It has no auth setting, so off is the only safe state.
- **Revoke Blender's access** under System Settings → Privacy & Security → Files and
  Folders (Desktop, Documents, Downloads), and keep it out of Full Disk Access. This is
  partial: it doesn't cover the rest of the home directory.
- **Blender's "Auto Run Python Scripts" preference does not help.** It governs scripts
  embedded in .blend files, not the addon's `exec`.

## Status

| layer | state |
|---|---|
| L0 bridge token | now in our own add-on, `addon/mcp_bridge.py` (proposed 2026-10-09), with `rust/blender_bridge.rs` sending the token. A probe from the agent container on 2026-10-09: port 9876 accepted the connection, and a ping without a token got no reply in 12 s. The token-checking add-on answers `unauthorized` at once, so the add-on running then most likely predates L0. Not yet built or tested |
| L1 path jail (write and read roots) | proposed 2026-10-09: `blender.rmcp.rb`, new `rust/blender_jail.rs`, `python/mcp_scripts.py`, `dev/smoke.sh`. Not yet built or tested |
| L2 guard on agent Python (`BLENDER_CODE_POLICY`) | proposed 2026-10-09: new `python/mcp_guard.py`, upstream's validator copied unmodified to `python/safe_mode.py`, `execute_code` in `blender.rmcp.rb`. Not yet run in Blender |
| L3 sandboxed agent Blender | optional, planned |
