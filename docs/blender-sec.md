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

### L1: path jail for the typed tools (next)

- **`BLENDER_FILE_ROOTS`** lists the allowed directories. It defaults to this repo, the
  only host directory mapped into the agent sandbox.
- **Every path parameter is resolved in Rust:** `canonicalize`, or the parent
  directory for a new file. It is refused unless it sits under a root, and Blender is
  handed the resolved path.
- **`render` returns the image instead of writing it.** It renders to Blender's temp
  directory, reads the PNG back, deletes it, and returns it in the reply, so a render
  leaves nothing on the host. MCP clients already store returned images on the agent's
  side (Claude Code keeps them under `~/.claude/.../tool-results/`).
- **`generate_3d.image`** is jailed and must be an image type.
- **`command`** loses `execute_code`, `export_scene`, `download_*` and `set_texture`,
  and `args` must parse as a JSON object.

### L2: policy on agent Python (next)

- **Static check before running:** reuse upstream's AST validator mechanics
  (deny-by-default, structural) with a stricter policy. Block:
  - `open`, `os`, `sys`, `subprocess`, `socket`, `ctypes`, `importlib`,
    `eval`/`exec`/`__import__`, and the dunder ladder;
  - persistence (`bpy.app.handlers`, `bpy.app.timers`, drivers, `register_class`);
  - code-execution operators and external .blend loading.
- **Runtime path checks on Blender's own writes**, which the static check can't judge
  because their paths are runtime values and the writes happen in C, unseen by Python
  audit hooks:
  - `render.render` with write_still/animation (scene output path plus compositor File
    Output nodes);
  - `Image.save`/`save_render`;
  - `wm.save_*`;
  - `bpy.data.libraries.write`;
  - every `export_scene.*` / `wm.*_export`.

  Each must resolve under a root.
- **Residual, stated honestly:** disk-cached physics, simulation bakes, movie/cache
  output and autosave write paths computed inside Blender. L2 checks the ones it can
  find. It is a guardrail, not a seal.

### L3: OS sandbox (optional, the airtight one)

Run a separate, agent-only Blender under macOS `sandbox-exec`. It denies `file-write*`
except the roots, the temp directory and Blender's config directory, and the kernel
enforces it, whatever code runs. The owner's everyday Blender keeps the addon off and
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
| L0 bridge token | proposed in raj: addon (both copies), `rust/blender_bridge.rs`, error text in `blender.rmcp.rb`. Not yet built or tested |
| L1 path jail + image-returning render + `command` trim | planned |
| L2 code policy | planned |
| L3 sandboxed agent Blender | optional, planned |
