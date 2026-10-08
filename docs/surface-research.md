# Surface research — the 29 tools, the vendored pack, and Rust

Four parallel read-only studies (2026-10-08): tool-name mapping vs the vendored
`vendor/blender-skills` pack; over-complication in our surface; new/tweaked tools;
and where Rust should replace Python-inside-Blender, with live benchmarks.
Method: all repo reads through `raj ctl`; the benchmark ran against the live
server (Blender 4.2.18 LTS, addon 1.8 attached).

## 1. Alias mapping (WS1)

The pack references exactly **three** literal MCP tool names — not four:

| upstream name | hits | our nearest tool | alias difficulty |
|---|---|---|---|
| `get_viewport_screenshot` | 22 | `screenshot` (same addon command, image block) | trivial |
| `execute_blender_code` | 13 | `execute_code` (raw stdout vs a prefixed string) | cosmetic |
| `get_scene_info` | 2 | `scene_info` / `scene` (structured vs an arg-less JSON string) | done via the addon command |

`get_object_info` is **not referenced by the pack** (0 hits) — that name is the
classic catalog / our own code. Recommended anyway for completeness, so the alias
set is four. Everything else the pack describes (Poly Haven/Sketchfab/Hyper3D/
Hunyuan3D) is **prose only**, so no alias is required; the generators are lossy
(ours auto-submits→polls→imports and returns a handle), so those stay on `command`.

Four thin aliases make the pack resolve; they return the classic shape (text or
image). The pack's own `.mcp.json` still points at `uvx blender-mcp`, so running it
also needs the client repointed at our HTTP transport.

## 2. Over-complication (WS2)

**Tier A** — high confidence:

- `make_3d` is a **pure preset of `generate_3d`** (which already defaults
  `provider:"auto"`, `wait_seconds:45`, extras optional). Zero unique capability.
- `reveal` is declared `read_only: true` but **mutates** — unhides, un-excludes,
  reselects, reframes, and marks an undo boundary (`@undoable`). Mislabel.
- `screenshot` is a **strict subset** of `look(mode:"viewport")` (same
  `viewport_png`; defaults 800 vs 768).
- `image_report` vs `image_report_rust`: the DSL itself calls the Rust one "the same
  job and more"; the Python one's only unique case is images already in the `.blend`.
- `array`/`boolean` can't be listed or removed by `modifier` (its `KINDS` omits
  them); `boolean.apply` defaults true while `modifier.apply` defaults false.
- `material`'s report always claims the viewport colour was set, even when no
  colour was given.

**Tier B:** `generate_3d.wait_seconds` advertises max 300 but is clamped to 45;
`look` has three overlapping selectors (`mode`/`views`/`view`); `scene_info.detail`
hides a `fields` list; `search_assets`/`import_asset` are three-library union bags
that even document a `command` fallback; the `command` enum has already drifted
(Tripo names missing); `run_script`/`run_module` duplicate ~35 lines of protocol.

**Tier C:** `object_info`/`scene` are raw passthroughs; "wireframe" names three
different things; `look(mode:"viewport")`'s caption carries no information;
`amount` is overloaded; seeing-tool defaults diverge (800/768/116/96/64).

**Removal candidates (a tool only goes if it carries little value):**
1. `make_3d` — zero unique capability. Remove, document the quick path in
   `generate_3d`.
2. `image_report` — conditionally; for file paths the Rust report does more with no
   Blender session. Keep only an in-`.blend` reader, or drop.
3. `screenshot` — *not* little value (short name, in the instructions): alias/merge,
   not delete.

## 3. Opportunities (WS3)

The pack's "query X via MCP" steps dead-end upstream because it has no typed
measurement. Ranked:

1. **`light` rig + Kelvin** (S): `rig`, `temperature`, `colour`, `ratio`, angles,
   target collection; sets `data.color`. Serves ~10 lighting skills + ~40 style ones.
2. **`audit`** (M): tris, non-manifold, unapplied scale, duplicate verts, material
   slots/unused, UV coverage/texel density, `COL_`/`MAT_` naming, budget gate.
   The biggest single cluster (asset-optimization, export-pipeline, qa-review…).
3. **`materials_report`** (S): typed Principled read (by input type), users, unused,
   naming check. Could ship as `audit(detail:"materials")`.
4. **`render` engine + colour management** (S): `engine`, `view_transform`, `look`,
   `denoise`, `transparent`.
5. **`modifier` shrinkwrap + remesh** (S–M): unblocks retopology.
6. `collections` tree/ensure/move (S–M); `look` orbit/turntable (S–M).
7. Very cheap cross-cut: a `naming PASS/FAIL` line in existing reports (~34 skill
   files reference naming).

## 4. Rust and benchmarks (WS4)

Live timings, `tools/call` round trip included, median of 3–4 runs:

| image | `image_report` (Python-in-Blender) | `image_report_rust` (Rust) | ratio |
|---|---|---|---|
| 8×8 | ~100 ms | ~8 ms | fixed overhead only |
| 256² | 378 ms | 134 ms | 2.8× Rust |
| 512² | 448 ms | 437 ms | parity |
| 1024² | 712 ms | 1657 ms | 0.43× — Python faster |
| 2048² | 1707 ms | 6725 ms | 0.25× — Python faster |

**The existing Rust image path is not a win at scale.** It builds the palette with a
per-pixel `HashMap` insert (SipHash) and calls `load()` twice per call; numpy's
vectorised `unique` wins from 512² up. Both agree on mean (rounding). Also: the
first lines do *not* agree — Rust says `grid 1x1`, Python `grid 116x58`, so the
README claim is wrong.

Mesh, Python-in-Blender (no Rust counterpart), 160k verts / 319k edges:
`mesh_report` 1094 ms, `wireframe` 2313 ms (pure-Python union-find + edge sampling).

**Candidates, benchmark-backed:**
1. Fix `textvision.rs`: a 4096-entry `u32` bucket array + one `load` → beats numpy at
   every size, removes the ~100 ms Blender dependency.
2. Move `wireframe` projection/sampling and `mesh_report` loose-parts + face
   histogram into Rust, over a numpy-extracted payload (`foreach_get`).
3. Replace `[mw @ v.co for v in me.vertices]` with `foreach_get` + one 4×4 transform
   (as `tools/garment.py` already does).

Wiring: a new `rust/meshvision.rs` with `rust_fn :mesh_wireframe` / `:mesh_measure`,
fed a compact payload by a new Python `mesh_geometry` entry; `rust_fn` args are
scalars/strings only, so the payload crosses as text.

## 5. Suggested order

1. **Fix `textvision.rs`** (bucket array, one `load`) — makes the existing Rust tool
   actually faster than Python, and the first-lines claim true. Small, testable.
2. **`light` rig + Kelvin** — biggest skill-cluster unlock for the effort.
3. **`audit`** (stage 1: geometry/transform/material/naming; stage 2: UV) — biggest
   cluster overall.
4. **Report/honesty fixes + cheap merges**: `reveal` label, `material` claim,
   `wait_seconds` max, `make_3d` removal, `screenshot` alias, `command` enum.
5. **Rust `meshvision`** — biggest raw speed win (`wireframe` 2.3 s → target <200 ms).
6. **Aliases** — 4 thin tools so the vendored pack resolves.
