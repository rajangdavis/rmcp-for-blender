---
name: rmcp-blender-skills
description: Drive the Blender MCP server built in this workspace - 25 typed tools over the MCP Bridge add-on's token-guarded socket. Use when making, moving, colouring, cutting, duplicating, rendering or exporting anything in Blender, when a Blender tool's report looks wrong, or when deciding which tool fits a job.
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
| see | `wireframe`, `mesh_report`, `image_report`, `image_report_rust`, `look`, `screenshot`, `reveal`, `compare_reference` |
| make | `text`, `duplicate`, `array`, `modifier`, `boolean` (asset libraries and 3D generation are out until they are ported to this server) |
| place and look like something | `place`, `aim`, `material`, `light` |
| hand over | `render` (a still PNG), `render_animation` (a frame range to video or PNG sequence), `export` (glb/fbx) |
| remove | `remove` |
| escape hatch | `execute_code` (guarded: bpy, bmesh, mathutils and pure-Python helpers only; every path under the server's roots) |

## The loop that works

make → place → colour → `wireframe`/`mesh_report` to check the shape and the
measurements → `aim` → `render` → `image_report` on the file → `export` when it
is worth keeping. `look` when the picture itself is the answer.

## Seeing cheaply, and checking against the brief

- **Diff the brief against the picture.** Before changing a scene, especially
  one another agent built, write the request as a checklist. Mark each line from
  a render, then print the data behind every miss (world bounds, parents, keys,
  fonts). Several misses show only in the data.
- **Crop renders** (`render.use_border` + `use_crop_to_border`) show a face or
  the lettering at full detail for a fraction of a full frame.
- **Strips:** render several crops (loop frames, one per candidate font), stitch
  them with numpy into one JPEG, and look once.
- Previews go under the repo's `renders/look/`; delete them when done.

## Matching a reference picture

When the brief is "make it look like this image" (a cover, a concept painting):

1. **Lay it out from the reference.** One camera at the reference's aspect, facing
   the scene. Place each element by its fraction of the frame: at depth `d` in
   front of a 50 mm lens on a 36 mm sensor the frame is `0.72·d` wide, so a point
   at (u, v) sits at x = (u−0.5)·W, z = (0.5−v)·W.
2. **Mask what is not built yet.** Trace each missing element (a figure, a title)
   as a polygon in frame fractions once, and pass the same `mask` to every
   `compare_reference` call.
3. **Loop:** `render` → `compare_reference` → fix the three largest differences
   you can name ("lower-right glow missing", "rocks lit too bright") → repeat.
   Use `region` to zoom both images on one area when the detail matters (debris,
   a silhouette, a texture).
4. **Judge by eye, not by a score.** SSIM, edge SSIM and colour histograms ranked
   the render the owner judged worst as the best of twelve: averages reward a
   flat grey wash over contrast and shape. Sample the reference's colours for
   materials, but keep the view transform in mind (AgX shifts every value).
5. **Ask the owner** before trusting a read of a busy area. A wrong read (a
   "ridge" that is floating shards) costs a full round.

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
- **Bridge unreachable** — either the MCP Bridge add-on is not started in Blender,
  or Blender is busy with a long call (a big remesh or render) and the reply timed
  out while the work went on. `scene` with `limit: 1` first. If it answers, check what the call should have
  produced before re-running anything; see `blender-notes.md`. If it does not
  answer, that is a message for the user, not a retry.

## Things that are deliberately absent

- **No undo tool.** One was written, worked for a `text` call, failed to bring a
  data-API removal back, and a single-step test ended the Blender session. See
  `blender-notes.md`; prefer expressible inverses (re-create, re-import).
- **No telemetry, no trajectory recording, no inline viewport app.** Images come
  back as content blocks instead.
- **A client across a boundary is allowed by name.** `transport :http` sets
  `allowed_hosts: ["host.docker.internal", "127.0.0.1", "localhost"]`, so a client
  dialling those names and sending their own `Host` is accepted (the list replaces
  the loopback defaults, so keep them; an unlisted `Host` still gets 403); only a
  server without `allowed_hosts:` needs a `node:http` or curl client that can
  present a loopback `Host` (`fetch` cannot set it; `dev/mcp.sh` takes
  `MCP_HOST_HEADER`).

Depth lives in: `docs/blender-notes.md` (Blender traps; what the community
server has that this one does not), `docs/text-vision.md` (why text instead of
pixels), `docs/build-and-transport.md` (transport, the dev loop, and the
compiler's gaps), `docs/editor-issues.md` (defects found in the editor),
`docs/scene-craft.md` (a prompt turned into a finished scene, every technique and
number, with `docs/scene-craft-island.py` as the runnable build), and
`docs/scene-craft-cartoon.md` (a flat 2D cartoon in 3D: elevation camera, a
window that never leaks sky, shader-mask fur patterns, bold CJK signage,
seamless loops, MP4 output).
