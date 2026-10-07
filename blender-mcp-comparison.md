# MCP for Blender (Python) vs the rmcp_dsl Rust server

The Python server (`src/blender_mcp/server.py`) exposes ~14 MCP tools that wrap
the addon's ~37 socket commands. The Rust server (`blender.rmcp.rb`) exposes 11
tools: ten typed tools, plus one generic `command`
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
| `generate_3d` | `create_rodin_job`, `poll_rodin_job_status`, `import_generated_asset`, `create_hunyuan_job`, … | `command` | generic; **not yet typed** |
| `search_assets` | `search_polyhaven_assets`, `search_sketchfab_models`, `search_polypizza_models` | `search_assets` | typed (`source`, `query`, `asset_type`, `category`, `min_size_m`, `licence`, `animated`, `limit`); returns the addon's listing |
| `import_asset` | `download_polyhaven_asset`, `download_sketchfab_model`, `download_polypizza_model`, `set_texture` | `import_asset` | typed (`source`, `id`, `asset_type`, `target_size`, `apply_to`, `resolution`, `file_format`) |
| `viewport_pick` (app-only) | `pick_viewport_object` | `command` | generic; **not yet typed** |
| — (no Python equivalent) | — | `wireframe` | extension: an object's mesh drawn as text, front/side/top at true proportions |
| — (no Python equivalent) | — | `mesh_report` | extension: dimensions, bbox, loose parts and a face-orientation histogram, as text |
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
- **Two text-vision tools with no Python equivalent.** `wireframe` and
  `mesh_report` give a text-only agent sight and measurement of a mesh as text,
  where the Python server can only return images whose base64 the agent cannot
  read (see `text-vision-tools.md`). A 78x34 wireframe is ~1 KB; a 600x381
  screenshot is ~80 KB.
- **Captures are per-call.** `look`/`screenshot` write
  `$TMPDIR/mcp-blender-<kind>-<pid>-<n>.png` and delete the file after reading,
  so concurrent callers cannot read each other's image. The Python server uses
  one fixed temp path per process.

## What the generic tool still buys

`command(name, args)` remains the long tail:

- it covers **every** command, including the argument-less ones the DSL cannot
  express as tools directly (gap #1 in `rmcp-dsl-gaps.md`);
- it keeps the surface at 7 tools rather than ~14 (or ~37), so the model holds a
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
