# MCP for Blender (Python) vs the rmcp_dsl Rust server

The Python server (`src/blender_mcp/server.py`) exposes ~14 MCP tools that wrap
the addon's ~37 socket commands. The Rust server (`blender.rmcp.rb`) exposes 26
tools: twenty-five typed tools, plus one generic `command`
tool carrying every command name as an enum and a JSON `args` string.

## Tool mapping

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
| `open_viewport` (app-only) | viewport resource | `screenshot` | the image is returned inline instead of beside the chat |
| `viewport_latest` (app-only) | — | — | an MCP resource/UI concept, not an agent tool |
| `record_trajectory_feedback` | trajectory/telemetry | — | intentionally out of scope |

Addon commands with no Python-server equivalent that the Rust server *does*
reach through `command`: `ping`, `get_world_state_snapshot`, `bpy_api_lookup`,
`describe_node_type`, `drain_human_activity`, `get_telemetry_consent`, the five
`get_*_status` commands, `export_scene`, `get_polyhaven_asset_preview`.

## Where the Rust server differs on purpose

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
  `text-vision-tools.md`). A 78x34 wireframe is ~1 KB; a 600x381 screenshot is
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
- **Captures are per-call.** `look`/`screenshot` write
  `$TMPDIR/mcp-blender-<kind>-<pid>-<n>.png` and delete the file after reading,
  so concurrent callers cannot read each other's image. The Python server uses
  one fixed temp path per process.

## What the generic tool still buys

`command(name, args)` remains the long tail:

- it covers **every** command, including the argument-less ones the DSL cannot
  express as tools directly (gap #1 in `rmcp-dsl-gaps.md`);
- it keeps the surface at 14 tools rather than ~37, so the model holds a
  small, stable schema while retaining full reach;
- it loses per-command typing: `args` is a JSON blob with no schema, enums or
  completion. The typed tools exist for the operations that deserve that, and
  `generate_3d` and `pick` are the remaining candidates. Asset thumbnails
  (`previews`) and polyhaven `attributes` stay on the generic tool by design.

## Faithfulness notes

- `params` are passed to the addon as `**kwargs`, so the Rust server sends only
  the keys a handler accepts; unknown keys would make the addon raise.
- Asset and generation commands are only registered in the addon when their
  sidebar toggles are on; with a toggle off, `command` returns the addon's
  "Unknown command type" error.
- The Python server's app-only tools (`open_viewport`, `viewport_*`) are MCP Apps
  affordances (an inline viewport in the chat); the Rust server has no Apps
  support and returns the screenshot inline instead.

## Status

The mapping above is current: 26 Rust tools against the Python server's ~14.
Every Python agent tool has a typed counterpart, and the six scene and output
tools have no Python equivalent at all; the Python server's app-only viewport
tools (`viewport_capture` via `screenshot`, `viewport_pick` via `command`) stay
untyped or unreached on purpose, since they are UI plumbing, and
`record_trajectory_feedback` is out of scope.

The six new tools were exercised against a live Blender: `reveal` reported the
empty scene's file, view layer, window and viewport; `text` created and converted
the mesh; `material` set base colour, roughness and the viewport colour and
confirmed all 2405 faces use slot 0; `place` moved the object relatively and the
camera absolutely; `wireframe` read the text back from the top view; `render`
wrote a 640x360 PNG in 0.3 s; `image_report` read that PNG back as text; and
`export` wrote a 0.12 MB GLB.

The reports earned their keep twice: the schema rejected a wireframe `height` of
12 before Blender saw it (minimum 20), and a render that came back as 97% flat
grey — `image_report`'s palette and mean — was a camera left holding an inherited
36.87 degrees of yaw, which `place`'s own report had named and the driver had
missed. Expect a picture of nothing to say so in those terms.

`remove` was exercised through the module itself, before its tool wrapper went
live: it removed the test object, reported `purged data with no user left: 1
mesh(es), 1 material(s)`, and left `Camera` and `Light`; a second call with one
real name and one typo answered `no object named ...; nothing was removed`. The
file afterwards held no meshes and only Blender's own `Dots Stroke` material.
That path is also the argument for the module refactor: the Python half could be
exercised entire with `execute_code`, with no rebuild and no save, because the
server reads the file from disk and the harness calls the same entry point
`run_module` calls.

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
`blender-notes.md`. The boundary decorator stays, because it makes the user's own
undo land on a tool call's boundary; the tool does not.
