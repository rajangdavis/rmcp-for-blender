---
name: blender-tools
description: Drive the Blender MCP server built in this workspace - 29 typed tools over the mcp-for-blender addon's socket bridge. Use when making, moving, colouring, cutting, duplicating, rendering or exporting anything in Blender, when a Blender tool's report looks wrong, or when deciding which tool fits a job.
---

# Driving this Blender server

Blender runs on the same machine as the server; this agent usually does not. Every
tool takes typed arguments and returns **text** (or an image block for `look` and
`screenshot`), so read the report: it is the interface, and several tools exist
mainly to make a failure visible instead of silent.

## Before changing anything

- `reveal` — the file, scene, view layer, window and viewport count, then it
  clears local view, leaves camera view, unhides the object and frames it. It
  answers "which Blender, and which file, am I about to change". Run it first
  when something is not on screen.
- `scene` / `scene_info` — names, sizes, health. `object_info` for one object.

## By task

| job | tools |
|---|---|
| see | `wireframe`, `mesh_report`, `image_report`, `image_report_rust`, `look`, `screenshot`, `reveal` |
| make | `text`, `duplicate`, `array`, `modifier`, `boolean`, `search_assets`, `import_asset`, `generate_3d`, `make_3d` |
| place and look like something | `place`, `aim`, `material`, `light` |
| hand over | `render` (a file on disk), `export` (glb/fbx) |
| remove | `remove` |
| escape hatches | `execute_code`, `command` |

## The loop that works

make → place → colour → `wireframe`/`mesh_report` to check the shape and the
measurements → `aim` → `render` → `image_report` on the file → `export` when it
is worth keeping. `look` when the picture itself is the answer.

## Report signatures worth recognising

- **Flat grey render** — `mean` and `palette` both near `#333333` and every hue
  cell a dot means the camera is looking at the world background. Point it with
  `aim`; do not re-render hoping.
- **`faces 499 -> 0`** from `boolean` — the cutter contained the object. Cut with
  a slab, not a cube at the subject's centre.
- **`loose parts: N`** from `mesh_report` — the mesh is in N disconnected pieces,
  which is how you see a cut or a floating fragment without an image.
- **`purged data with no user left: …`** — orphans really went; with
  `purge: false` the tool says instead that the data is still in the file.
- **Two face counts** — `array` and `modifier` report the base mesh and the
  evaluated one, because `mesh_report` and `wireframe` read the base and renders
  apply the modifiers.
- **Bridge unreachable** — the addon's server is not listening in Blender. That
  is a message for the user, not a retry.

## Things that are deliberately absent

- **No undo tool.** One was written, worked for a `text` call, failed to bring a
  data-API removal back, and a single-step test ended the Blender session. See
  `blender-notes.md`; prefer expressible inverses (re-create, re-import).
- **No telemetry, no trajectory recording, no inline viewport app.** Images come
  back as content blocks instead.
- **A client from another machine must present a loopback `Host`.** rmcp's
  DNS-rebinding check refuses any other value, and `fetch` cannot set the header;
  a sandbox needs a `node:http` or curl client (`mcp.sh` takes `MCP_HOST_HEADER`).

Depth lives in: `docs/blender-notes.md` (Blender traps; what the community
server has that this one does not), `docs/text-vision.md` (why text instead of
pixels), `docs/build-and-transport.md` (transport, the dev loop, and the
compiler's gaps), `docs/editor-issues.md` (defects found in the editor).
