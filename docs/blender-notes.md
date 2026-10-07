# Blender notes from building the tool surface

Blender-side facts that cost real round trips while this server was built. The
DSL's own gaps are in `docs/build-and-transport.md`, editor issues in
`docs/editor-issues.md`, and the text-vision design in `docs/text-vision.md`.
Each entry here is something a tool had to be told about, with the evidence
that found it. The tool surface, and the decisions behind it, are mapped against
the upstream Python server in the sections at the end.

## A camera facing the wrong way renders the world, and nothing says so

A render came back twice as a flat grey picture. `image_report` read it
correctly — `mean #3b3b3b`, `palette #333333 97%`, every hue cell a dot — which
is the signature of "world background, no geometry". The object was fine; the
camera was not.

The cause was mine and worth stating exactly, because the tool that reports it
already existed: `place` had been asked for `rx: 90` on the scene camera, which
set the pitch absolutely and left an inherited **36.87 degrees of yaw** in
place, pointing the camera about 3 m to the left of the subject. `place`'s own
report printed `now: rotation (90.00, -0.00, 36.87 deg)` and the number was not
read.

`aim` exists so this is not a judgement call: it frames a target from a named
side, computes the distance that fits the target's size to the lens, and points
the camera with a track quaternion rather than hand-set Euler angles. For a
1.05 m object at 50 mm it chose 2.63 m.

## Undo is the whole file's history, not one tool's

Measured, not assumed:

```
plain undo returned {'FINISHED'}
plain: objects 2 -> 3 after add -> 5 after undo      ← it walked back further than one step
with undo_push first: ok; objects 5 -> 6 after add -> 5 after undo   ← exactly one step
```

So undo *does* cover changes made by scripts through the socket, and
`bpy.ops.ed.undo_push(message=...)` creates an exact boundary. Two consequences
are built into this server: every tool that changes the scene opens a step first
(the module's `undoable` decorator), and `undo` is described as walking the
*file's* history rather than "undo the last call" — because it can cross the
user's own edits and earlier calls. It also does not unlink files that `render`
or `export` wrote.

Two lessons earned the hard way. **Never test undo on a live, unsaved file.**
The first probe, of two undos, walked past that session's changes, resurrected
three objects the user had deliberately deleted, and reset the camera to
Blender's startup default. The second probe was a *single* step and it ended the
session: `undo {"steps": 1}` right after a `text` call reverted the creation
exactly (`objects now (2): Camera, Light`), which shows the decorator and
`undo_push` do what they claim — and then Blender turned off, the addon's socket
refused while the MCP server stayed healthy on its own port, and the user
confirmed the application had gone. Scratch files exist for this.

So the `undo` tool was **removed** rather than labelled experimental: a tool that
can end a session is worse than no tool. What remains is the boundary decorator
on every mutating entry point, which is useful on its own terms — the user's
Ctrl-Z lands on a tool call's boundary instead of in the middle of one.

There is also an unresolved asymmetry worth chasing in a scratch session.
Reverting a `text` call works, and that path ends in an **operator**
(`object.convert`). Failing to revert a `remove` call is the observed case where
the change is pure **data API** (`bpy.data.objects.remove`). If that is the
distinction, mutating tools should prefer operators where one exists —
`bpy.ops.object.delete()` for removal — before undo can be described as a safety
net.

## Local view and camera view hide a scene that is fine

Every trap that hides an object while the scene data says it is visible:

- **local view** (`space_data.local_view` set) — the viewport shows only the
  isolated objects; the outliner disagrees.
- **camera view** — `region_3d.view_perspective == "CAMERA"` overrides the
  framing, so `view_selected` appears to do nothing.
- **hidden collections** — `collection.hide_viewport`, or the layer collection's
  `exclude` (which removes it from the view layer entirely, so no viewport can
  draw it) or `hide_viewport`.
- **the object flags** — `hide_viewport`, `hide_set()` (the eye, per view
  layer), `hide_select`, `hide_render`.
- **a second Blender** — another window or process holding the addon socket.

`reveal` reports the file, scene, view layer, window count and viewport count
first, precisely because "the scene" is ambiguous when more than one is open,
then clears those traps and frames the object.

## A text object is a curve, and the mesh tools cannot read it

`bpy.data.curves.new(type="FONT")` produces something `wireframe`, `mesh_report`
and a glTF export cannot read as a mesh. `text` converts to a mesh by default
and says so (`converted to MESH: 1200 vertices, 880 faces`); `as_mesh: false`
keeps the curve when the text must stay editable.

Related: text lies flat in XY, so a **front** view draws its extruded edge — a
thin band — and the **top** view is the one that reads it. `wireframe` was
right both times; the request was wrong.

## A boolean whose cutter contains the object deletes it

```
MCP.001 difference Cube: faces 499 -> 0
the result is empty: check that the two objects overlap
```

A 0.5 m cube added at the subject's own centre encloses it, and the difference
of a containing solid is nothing. The tool reported the count and the likely
cause rather than claiming success. A cutter wants to be a slab: 0.06 m wide
through the glyphs gave `499 -> 456` and five loose parts.

## Modifiers are not the mesh

`array`, `boolean` (with `apply: false`) and any other modifier live *on top of*
the mesh. Reports that read `ob.data` — `mesh_report`, `wireframe` — describe the
base mesh, so a four-copy array still reads as `faces 499`. Renders and exports
apply modifiers, so what is rendered and exported is the array. The array tool
states both numbers: `faces 499 in the mesh, 1996 with the modifier applied`.

## The addon answers `status: "success"` for handler errors

The socket protocol wraps a handler exception as a **successful** reply whose
payload is `{"error": "..."}`. Every request path therefore inspects the payload
rather than trusting the status. A tool that skipped this would report a failed
command as a successful one.

## Orphaned data outlives the object

Deleting an object leaves its mesh and material in the file with no user. They
are not visible in the scene, they are saved into the `.blend`, and they make
"the file is clean" false until purged. `remove` runs
`bpy.data.orphans_purge(do_recursive=True)` and reports what it freed — `purged
data with no user left: 6 mesh(es), 1 material(s)` — and with `purge: false` it
says plainly that the data is still there.

## Lighting is a separate problem from geometry

An object can be perfectly placed and still render dark: the scene's default
light may point elsewhere, and the world contributes flat ambient. The energy
unit changes meaning with the type — a sun is irradiance in W/m² where about 3
reads as daylight, while point, area and spot are watts where 1000 is a lamp —
so `light` reports the type, the energy and what it aimed at, and lists every
light in the file rather than assuming the one it just made is the only one.

## numpy is in Blender's Python, and `foreach_get` is the way in

Blender bundles numpy — not an addon, not optional — so a script can move bulk
data instead of looping over it one element at a time. The bridge is the
`foreach_*` family, which reads or writes a flat buffer in one call:

- `img.pixels.foreach_get(buf)` — what `image_report` uses to read a whole image
  into an array; pixels are `float32`, RGBA, bottom-up.
- `mesh.vertices.foreach_get("co", arr)` — vertex positions in one call, with
  `foreach_set` for the way back; `mesh.polygons.foreach_get("material_index", …)`
  and `mesh.attributes[...].data.foreach_get(...)` work the same way.
- `mathutils` interops: `np.asarray(vector)` works, and for bulk work it is
  cheaper to take the object's matrix once and do `coords @ M.T` than to multiply
  per vertex inside a Python loop.

Gotchas worth knowing before trusting a fast path:

- **The dtype has to match.** Vertex coordinates are `float32`; a `float64` array
  raises instead of converting quietly. Same for pixels.
- **`ob.data` is the base mesh.** Modifiers are not in it — the evaluated object
  from the depsgraph is — which is why `array` and `modifier` report two face
  counts, and why `wireframe`/`mesh_report` see the unmodifiered shape.
- **The loops, not the reads, are what crawl.** `wireframe`'s rasterisation and
  `image_report`'s per-cell reduction are Python loops over a grid, while the
  array reads feeding them are already a single call each. Vectorising those two
  with `np.add.reduceat` / `np.histogram2d` is the cheap win when a generated
  import makes them slow.

Upstream's own guides — seven of them, in the vendored package — never mention
numpy or `foreach_get`, so this is one place their skill material is thinner than
the API deserves.

## The tool surface, compared with the upstream Python server

The Python server (`src/blender_mcp/server.py`) exposes ~14 MCP tools that wrap
the addon's ~37 socket commands. The Rust server (`blender.rmcp.rb`) exposes 29
tools: twenty-eight typed tools, plus one generic `command`
tool carrying every command name as an enum and a JSON `args` string.

### Tool mapping

| Python MCP tool | addon command(s) | Rust server | how |
|---|---|---|---|
| `execute_blender_code` | `execute_code` | `execute_code` | typed (`code` → `output`) |
| `get_scene_info` | `execute_code` → `SCENE_SUMMARY` script | `scene_info` | typed (`query`, `root`, `detail`, `limit`); returns the script's `{header, lines, total, shown}` |
| `look` | `execute_code` → `LOOK` script, or `get_viewport_screenshot` | `look` | typed (`mode`, `shading`, `targets`, `views`, `frames`, `view`, `image`, `distance`, `frame_count`, `max_size`) → `image` + the script's `info` as text |
| `viewport_capture` (app-only) | `get_viewport_screenshot` | `screenshot` | typed, returns an `image` content block |
| `search_mentions` | `list_scene_items` | `scene` | typed (`query`, `limit` → `items`) |
| — (addon only) | `get_object_info` | `object_info` | typed (`name`) |
| `get_addon_status` | `get_addon_info` + `get_*_status` | `command` | generic |
| `disable_telemetry` | `set_telemetry_consent` | `command` | generic |
| `generate_3d` | `create_rodin_job`, `poll_rodin_job_status`, `import_generated_asset`, `create_hunyuan_job`, … | `generate_3d` | typed (`prompt`, `image`, `name`, `provider`, `quality`, `bbox_condition`, `job`, `wait_seconds`); blocks up to 45 s per call, then hands back a handle to resume waiting |
| — (the Python tool covers both paths) | `create_*` + `poll_*` + `import_generated_asset` | `make_3d` | typed (`prompt`, `name`, `job`); the quick path, which picks the provider itself |
| `search_assets` | `search_polyhaven_assets`, `search_sketchfab_models`, `search_polypizza_models` | `search_assets` | typed (`source`, `query`, `asset_type`, `category`, `min_size_m`, `licence`, `animated`, `limit`); returns the addon's listing |
| `import_asset` | `download_polyhaven_asset`, `download_sketchfab_model`, `download_polypizza_model`, `set_texture` | `import_asset` | typed (`source`, `id`, `asset_type`, `target_size`, `apply_to`, `resolution`, `file_format`) |
| `viewport_pick` (app-only) | `pick_viewport_object` | `command` | generic; **not yet typed** |
| — (no Python equivalent) | — | `wireframe` | extension: an object's mesh drawn as text, front/side/top at true proportions |
| — (no Python equivalent) | — | `mesh_report` | extension: dimensions, bbox, loose parts and a face-orientation histogram, as text |
| — (no Python equivalent) | — | `image_report` | extension: any image it can read (path, URL or data URI) as dimensions, aspect, mean and top colours and two character grids, as text |
| — (no Python equivalent) | — | `reveal` | extension: why an object is not on screen (the file, scene, view layer, local view, camera view, hidden collections), what was cleared, and a frame |
| — (no Python equivalent) | — | `text` | extension: one 3D text object from a string, converted to a mesh so the mesh tools and the export can read it |
| — (no Python equivalent) | — | `place` | extension: location, rotation or uniform scale, absolute or relative, touching only the axes given |
| — (no Python equivalent) | — | `material` | extension: set or create a material from a hex colour or a name, on both the Principled base colour and the flat viewport colour, saying which slot the faces use |
| — (no Python equivalent) | — | `render` | extension: render to a PNG at a chosen resolution and sample count and leave the file on disk |
| — (Python exposes none) | `export_scene` | `export` | script: named objects with their children to glb or fbx, path resolved beside the .blend, reporting what was skipped |
| — (no Python equivalent) | — | `remove` | extension: delete named objects and report the cost — children left unparented, data the orphan purge freed, what remains |
| — (no Python equivalent) | — | `duplicate` | extension: copy objects with a fixed offset per copy, whole or linked to the original's mesh |
| `array` modifier | — | `array` | extension: add or update an array modifier (count, axis, constant or relative offsets), reporting base and evaluated face counts |
| `boolean` modifier | — | `boolean` | extension: difference, union or intersect against a named operand, applied or live, with a face count that shows a cut that missed |
| — (no Python equivalent) | — | `aim` | extension: place and orient a camera to frame a target from a named side, fitting its size to the lens |
| — (no Python equivalent) | — | `light` | extension: create or adjust a light, aimed at an object or the scene, reporting type, energy and every light in the file |
| `subdivision`, `bevel`, `mirror`, `solidify`, `decimate`, `wireframe` modifiers | — | `modifier` | extension: add, remove or list one modifier with the setting that matters for that kind typed, reporting base and evaluated face counts |
| — (no Python equivalent) | — | `image_report_rust` | extension: the image facts, tone grid, hue-and-strength grid, hue-ordered spectrum and a summary sentence — computed in its own Rust, so it needs no Blender session at all |
| — (no Python equivalent) | — | `image_view` | extension: the image itself as truecolour half-blocks for a human to look at, which is what the Python server can only do with an app viewport |
| `open_viewport` (app-only) | viewport resource | `screenshot` | the image is returned inline instead of beside the chat |
| `viewport_latest` (app-only) | — | — | an MCP resource/UI concept, not an agent tool |
| `record_trajectory_feedback` | trajectory/telemetry | — | intentionally out of scope |

Addon commands with no Python-server equivalent that the Rust server *does*
reach through `command`: `ping`, `get_world_state_snapshot`, `bpy_api_lookup`,
`describe_node_type`, `drain_human_activity`, `get_telemetry_consent`, the five
`get_*_status` commands, `export_scene`, `get_polyhaven_asset_preview`.

### Faithfulness notes

- `params` are passed to the addon as `**kwargs`, so the Rust server sends only
  the keys a handler accepts; unknown keys would make the addon raise.
- Asset and generation commands are only registered in the addon when their
  sidebar toggles are on; with a toggle off, `command` returns the addon's
  "Unknown command type" error.
- The Python server's app-only tools (`open_viewport`, `viewport_*`) are MCP Apps
  affordances (an inline viewport in the chat); the Rust server has no Apps
  support and returns the screenshot inline instead.

## Decision log

### Where the Rust server differs on purpose

- **Structured, not flattened.** `scene_info` returns the script's header, lines
  and totals as `structuredContent` where the Python server renders a text table.
  `look` returns the script's `info` (`views`, `frames`, `size`, `targets`,
  `center`) as a text block beside the image, where the Python server writes a
  prose caption. The underlying data is the same.
- **Enums instead of free-form strings.** `detail`, `mode`, `shading`, `view`
  and the command `name` are constrained; the Python server's free-form `fields`
  list is replaced by a `detail` enum that maps to the same field sets.
- **Strong typing on arguments** generally: numbers are numbers, lists are lists
  (`:string_list`, `:i64_list`), and the constraints ride in the schema.
- **The script source is installed into Blender once.** The Python server ships
  the whole `SCENE_SUMMARY` / `LOOK` source in every `execute_code` call; the
  Rust server installs it into `sys.modules` on first use and then sends only a
  short invocation, with a cold-cache marker so a restarted Blender self-heals.
- **The socket is kept between calls**, as the Python server keeps one. A request
  that was written is never sent twice, and the connection is dropped when its
  write fails or a reply will not parse.
- **Three text-vision tools with no Python equivalent.** `wireframe` and
  `mesh_report` give a text-only agent sight and measurement of a mesh as text,
  and `image_report` gives it the same for any image it can read; the Python
  server can only return images whose base64 the agent cannot read (see
  `docs/text-vision.md`). A 78x34 wireframe is ~1 KB; a 600x381 screenshot is
  ~80 KB.
- **Twelve scene and output tools with no Python equivalent.** `reveal`, `text`,
  `place`, `material`, `remove`, `duplicate`, `array`, `boolean`, `aim`, `light`,
  `render` and `export` cover the loop the Python server leaves to
  `execute_blender_code`: find out why nothing is on screen, make something,
  copy and stack it, cut it, position it, aim a camera at it, light it, colour
  it, delete it again, render it, and hand the result over as a file. They run
  `python/mcp_scripts.py`, a real Python module rather than a string constant,
  installed into Blender once per content hash.
- **Agent-facing material ships with the tools.** Upstream carries seven guides
  (`scene`, `materials`, `rigging`, `animation`, `retopology`, `level-design`,
  `bpy`) and a Codex plugin whose manifest carries default prompts
  (`"Add a wooden chair from Poly Pizza"`). This server's equivalent is
  `blender-tools/SKILL.md`: the tool-by-task map, the loop that works, and the
  report signatures worth recognising — a flat grey render, `faces 499 -> 0`, a
  loose-part count, and the two face counts a modifier reports.
- **Some of the work runs in the server, in Rust, with tests.** `textvision.rs` reads
  an image file directly and computes the facts, the grids, the spectrum and the
  summary; `ImageFile.size` and the socket bridge are Rust too. The difference from
  the Python scripts is not just speed: this half needs no Blender session, so it
  keeps working while the addon is stopped, and it carries unit tests (`cargo test`)
  where everything reaching Blender can only be checked by calling Blender and
  reading a report.
- **Captures are per-call.** `look`/`screenshot` write
  `$TMPDIR/mcp-blender-<kind>-<pid>-<n>.png` and delete the file after reading,
  so concurrent callers cannot read each other's image. The Python server uses
  one fixed temp path per process.

### What the generic tool still buys

`command(name, args)` remains the long tail:

- it covers **every** command, including the argument-less ones the DSL cannot
  express as tools directly (gap #1 in `docs/build-and-transport.md`);
- it keeps the surface at 14 tools rather than ~37, so the model holds a
  small, stable schema while retaining full reach;
- it loses per-command typing: `args` is a JSON blob with no schema, enums or
  completion. The typed tools exist for the operations that deserve that, and
  `generate_3d` and `pick` are the remaining candidates. Asset thumbnails
  (`previews`) and polyhaven `attributes` stay on the generic tool by design.

### Status

The mapping above is current: 26 Rust tools against the Python server's ~14.
Every Python agent tool has a typed counterpart, and the six scene and output
tools have no Python equivalent at all; the Python server's app-only viewport
tools (`viewport_capture` via `screenshot`, `viewport_pick` via `command`) stay
untyped or unreached on purpose, since they are UI plumbing, and
`record_trajectory_feedback` is out of scope.

The new tools were exercised against a live Blender — `reveal`, `text`,
`material`, `place`, `wireframe`, `render`, `image_report` and `export` each got
a real scene and a real report — and `remove` through the module itself, before
its wrapper went live, which is also the argument for the module refactor: the
Python half can be exercised entire with `execute_code`, with no rebuild and no
save, because the server reads the file from disk and the harness calls the same
entry point `run_module` calls. The reports earned their keep twice: the schema
rejected a wireframe `height` of 12 before Blender saw it (minimum 20), and a
render that came back as 97% flat grey — `image_report`'s palette and mean — was
a camera left holding an inherited 36.87 degrees of yaw, which `place`'s own
report had named and the driver had missed. Expect a picture of nothing to say
so in those terms.

What is *not* proved is the generation success path. `generate_3d` and `make_3d`
are typed and their failure paths were exercised for real — Tripo answers with a
Premium refusal, the Rodin trial key reports `API_INSUFFICIENT_FUNDS`, and the
Hunyuan3D `LOCAL_API` refuses connections — but no provider has yet been watched
through to an imported model.

An `undo` tool was written and then **removed**. The boundary mechanism works:
every mutating tool opens an undo step via `bpy.ops.ed.undo_push`, and one step
reverted a `text` call exactly. But a removal made through Blender's data API did
not come back, and a single-step test ended the session — Blender turned off. The
details, and the operator-versus-data-API hypothesis behind the asymmetry, are in
"Undo is the whole file's history, not one tool's", above. The boundary decorator
stays, because it makes the user's own undo land on a tool call's boundary; the
tool does not.
