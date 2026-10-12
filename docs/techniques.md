# Blender Techniques Digest

Provenance: this is a paraphrased digest mined from the vendored skills pack at
`vendor/blender-skills`, version **v1.3.0** (94 skills). Licensed **MIT**,
copyright **© 2026 blender-skills contributors**. Numeric values are kept from the
source; wording is condensed. No source code is copied.

## From blender-skills

### Three-point and product light rigs
- Three-point: key area ~1 m² at 45° elevation / 30° azimuth, 5500K, ~500W; fill opposite at ~2 m², 5500K, ~150W (about 30% of key); rim spot ~135° behind, warm 3200K, ~300W.
- Product hero: large soft area key (~2 m²), two rim spots L/R behind for edges, gradient or seamless backdrop, 85mm at f/2.8 focused on hero detail.
- Golden hour environment: sun 3000K ~5° above horizon, warm sky HDRI fill ~0.3, volumetric density ~0.01 for haze.
- Turntable: key parented to camera, neutral studio HDRI fill, subtle rim behind; orbit an empty 360° over 120 frames on mid-gray for PBR accuracy.
- Pair with Cycles 256+ samples, denoise on, AgX view transform, Medium Contrast look.
source: vendor/blender-skills/.claude/skills/lighting/SKILL.md; vendor/blender-skills/.claude/skills/lighting/references/cinematic-light-rigs.md

### Color temperature and HDRI mood
- Kelvin map: candle/warm 1800K, tungsten 3200K, daylight 5500K, overcast 6500K, moonlight 8000K+.
- Horror mixes warm interior tungsten against cold exterior moonlight.
- HDRI workflow: pick an HDRI matching mood (overcast for horror, clear for hero), rotate the brightest area to serve as key, set strength 0.5–2.0, supplement with area lights for separation, and hide the HDRI behind solid color/fog.
source: vendor/blender-skills/.claude/skills/lighting/SKILL.md

### Horror lighting setups
- Fluorescent corridor: 6500K area tube ~1.2 m × 0.1 m, ~50W every 3 m, volumetric density 0.03, flicker noise, no fill or 5% ambient only.
- Single bare bulb: 2800K point ~100W at ceiling center with visible emissive bulb, hard high-contrast shadows, no fill.
- Analog TV glow: 5000K green-tinted area ~20W low and facing into the room, emissive screen material, room otherwise dark.
- Exit accent: narrow green spot ~30W above the sign as false safety before a threat reveal.
- Window moonlight: night HDRI strength 0.1 plus an 8000K area ~20W through the opening; interior near black except rim highlights.
- Flicker: noise/driver on light energy, amplitude ±30%, random offset per light; flicker only 1–2 lights, never all at once.
source: vendor/blender-skills/.claude/skills/lighting/references/horror-lighting-setups.md

### PBR value ranges
- Polished metal metallic 1.0, roughness 0.1–0.3; brushed metal 1.0, 0.4–0.6 (anisotropic if available); painted metal 0.0, 0.3–0.5 with base color = paint.
- Plastic 0.0 / 0.3–0.6; rubber 0.0 / 0.7–0.9; concrete 0.0 / 0.8–0.95; raw wood 0.0 / 0.5–0.7.
- Glass 0.0 / 0.0 with transmission 1; skin 0.0 / 0.4–0.6 with subsurface 0.1–0.3; fabric 0.0 / 0.7–0.9 with sheen.
source: vendor/blender-skills/.claude/skills/materials/SKILL.md

### Master materials and budgets
- Build reusable masters prefixed `MAT_` (Metal, Plastic, Fabric+Sheen, Glass IOR 1.45, Emissive, Organic+SSS); instance variations duplicate a master and adjust parameters only.
- Material budgets: hero prop 3–5, standard prop 1–2, modular piece 1 (atlas), character 3–8 (body/cloth/eyes/hair), environment module 1–2.
- Vertex colors: RGB variation masks; R wear, G dirt, B wetness; document the channel usage.
- Never finalize materials before UVs are complete; test each material in its target lighting setup.
source: vendor/blender-skills/.claude/skills/materials/SKILL.md

### Procedural wear and dirt patterns
- Edge wear: Pointiness or Bevel → ColorRamp → mix base color/roughness; a high-IOR Fresnel gives edge-only wear.
- Dirt: inverted AO multiplied by dirt brown, combined with a curvature/cavity mask, applied mainly to roughness rather than albedo.
- Rust: noise scale 5–20 → ColorRamp threshold, orange-brown over the metal base, metallic 0 and higher roughness inside rust zones.
- Moss: AO plus upward normal (Z+) → green overlay with higher roughness.
- Water staining: vertical gradient plus noise darkens albedo on concrete/plaster/ceiling corners.
- Panel variation: Object Info random per object → HSV with subtle ±5% hue and ±10% value. Keep wear/dirt as reusable node groups plugged into masters.
source: vendor/blender-skills/.claude/skills/materials/references/procedural-patterns.md

### Surface recipes
- Worn painted metal: metallic 0, roughness 0.5–0.7, procedural edge-wear mask on roughness.
- Weathered concrete: base desaturated gray 0.4–0.5, roughness 0.85–0.95, subtle noise bump.
- Oiled wood: warm brown, roughness 0.4–0.6, anisotropic rotation along the grain if available.
- Cotton fabric: roughness 0.8, sheen 0.3, optional subsurface 0.05.
- Standard glass: transmission 1, IOR 1.45, roughness 0.02–0.1.
source: vendor/blender-skills/.claude/skills/materials/references/surface-recipes.md

### Beauty stack and grading
- Default stack: Combined → exposure/color balance (AgX-aware) → glare sparingly (fog glow/streaks) → subtle lens distortion → subtle vignette → output.
- Rule: fix exposure before creative grade; prefer lift/gamma/gain or color balance over crushed curves; keep skin/product hues plausible; match reference stills side-by-side.
- Grade presets: neutral product (exposure only); cinematic cool (cyan shadows, warm highlights); horror sick (desaturate, green-pushed shadows, crushed but not clipped); neon night (magenta/cyan contrast, controlled bloom); archviz clean (soft contrast, accurate whites).
- Outputs `OUT_Beauty_[Shot]`, optional `OUT_Alpha`/`OUT_CryptoID`; EXR for archival, PNG/JPEG for review.
source: vendor/blender-skills/.claude/skills/compositing/SKILL.md; vendor/blender-skills/.claude/skills/compositing/references/grade-presets.md; vendor/blender-skills/.claude/skills/compositing/references/pass-stack.md

### Render pass set
- Essential Cycles passes: Combined, Diffuse Direct/Indirect, Glossy Direct, Normal, Z-depth, AO, Cryptomatte, Emission.
- Basic composite: Combined + AO multiplied (factor 0.3) + glare on the emission pass + exposure/contrast.
- Cryptomatte isolates objects in the compositor without re-rendering; multi-layer OpenEXR feeds Nuke/After Effects/Fusion pipelines.
- Denoise the Combined pass with OpenImageDenoise; keep Normal + Albedo passes when post-denoising.
- Game assets need only the Combined turntable pass; portfolio work uses the full set for relight flexibility.
source: vendor/blender-skills/.claude/skills/rendering/references/render-passes.md

### Render engine settings
- Cycles: preview 64–128 samples, production 512–2048; OpenImageDenoise; max bounces 8 preview / 12 production; caustics off unless glass or water is hero.
- Eevee: SSR on for metals, AO on, bloom for stylized/emissive scenes, shadow resolution 2048+, contact shadows for ground contact.
- Color management: AgX (Blender 4+) or Filmic; Medium Contrast default, High Contrast for drama; adjust exposure in the compositor, not by blowing lights.
- Camera focal lengths: 35mm environment, 85mm hero detail, 24mm wide horror; organize cameras in `COL_Cameras`; use render region and adaptive sampling for tests.
source: vendor/blender-skills/.claude/skills/rendering/SKILL.md

### NPR rendering
- Toon: Principled → Shader to RGB → ColorRamp (2–3 steps) → output; the light threshold controls the cel band count.
- Outline methods: inverted hull (good quality, medium cost), Freestyle (best control, slow), compositor edge (fast, post effect).
- Inverted hull: Solidify with negative thickness, flip normals, pure black emission material, rendered over the toon fill.
- Rim light in shader: Fresnel IOR 2.0 → ColorRamp → mix into emission; warm rim for stylized characters.
- Eevee NPR: bloom on for emissive accents, SSR off (it breaks toon), half/Li-Sun shadow mode for hard shadows.
source: vendor/blender-skills/.claude/skills/rendering/references/npr-rendering.md

### Geometry nodes patterns
- Scatter: distribute points on faces → instance on points → randomize Z rotation → randomize scale → optional realize.
- Randomization ranges: scale 0.8–1.2, Z rotation 0–360°, density 0.1–2.0 per m², integer seed for reproducibility (always expose the seed as a group input).
- Name groups `GN_[System]_[Descriptor]`, version them (`GN_Scatter_Rocks_v02`), and expose only seed/density/scale-range inputs.
- Performance: realize + decimate for game export, keep instances for background scatter, bake hero procedurals; avoid nested realize operations.
- Reusable library: GN_Scatter_Objects, GN_Array_Modular, GN_Curve_Pipe, GN_Wall_Variant, GN_Vegetation_Cluster.
source: vendor/blender-skills/.claude/skills/geometry-nodes/SKILL.md

### Locomotion cycle timings
- At 30fps: walk 24–32 frames (contact/down/pass/up ×2), run 16–24 (contact/drive/flight/recovery), idle 60–120 loop (breathe, weight shift, blink).
- Name actions `AN_[Char]_[Action]_[Variant]`; block in stepped/constant mode before splining to Bezier auto handles, add weighted handles for ease, then verify the loop seam.
- Principles: timing through spacing, arcs, overlap/secondary motion offset, anticipation wind-up, and style-dependent exaggeration.
- Mechanical animation favors constraints over deformation: hinge = limit rotation, pistons = stretch-to/copy location, gears = driver, doors = empty pivot + rotation keys.
source: vendor/blender-skills/.claude/skills/animation/SKILL.md

### NLA and game-ready animation
- Push each action down to an NLA strip, set cycles to Repeat, keep a single strip active for export, scale 1.0, no time remapping unless intentional.
- Game-ready checks: root motion documented (in-place vs root motion), invisible loop seam, no bone scale keyframes, animation length matching the engine state machine, 30fps default, facial animation on a separate layer.
- Camera animation: smooth Bezier always, no sudden direction changes, focal length matched to subject, subtle noise modifier for shake.
source: vendor/blender-skills/.claude/skills/animation/SKILL.md

### Camera lenses and composition
- Lens guide: wide establishing 18–28mm (watch edge distortion), story/product 35–50mm, portrait/hero 85–135mm (compression), tele drama 150mm+.
- Set sensor fit and resolution intentionally because they change FOV.
- Composition checklist: readable silhouette, intentional headroom/lead room, level horizon unless motivated, foreground/mid/background depth, no edge tangent mergers.
- Naming: `CAM_[Shot]_[Angle]`, `EMPTY_CamTarget_[Shot]`, collection `COL_Cameras`.
source: vendor/blender-skills/.claude/skills/camera-cinematography/SKILL.md

### Camera move library
- Slow dolly in = focus/dread (ease both ends); orbit = showcase (keep target empty); crane up = reveal scale (start covered); handheld = unease/documentary (subtle noise only); lock off = product/archviz (perfect level).
source: vendor/blender-skills/.claude/skills/camera-cinematography/references/camera-move-library.md

### Depth of field
- Focus on the subject empty; shallow DoF for hero shots, deeper for environments; preview in Eevee and confirm in Cycles for final; avoid focus hunting mid-shot unless motivated.
source: vendor/blender-skills/.claude/skills/camera-cinematography/references/dof-guide.md

### VFX path decision and volume domain rules
- Path decision: real-time game → mesh cards/ribbons + emissive materials (+ GN); cinematic → Mantaflow/particles/GN rendered and composited; hybrid → simulate in Blender then bake flipbooks/meshes for the engine.
- Volume rules: make the domain only as large as needed, go low → high resolution after motion is approved, open borders intentionally, and put it in `COL_FX_[Shot]`.
- Naming: emitters `FX_Emit_[Name]`, domains `FX_Domain_[Name]`; document cache frame ranges in the brief.
- Effect approaches: smoke/fire Mantaflow domain + flow; sparks particles + collision + trail; debris rigid-body shards; magic ribbons curves/GN extrude + emissive; dust a short particle burst with soft sprites.
source: vendor/blender-skills/.claude/skills/vfx-fx/SKILL.md

### FX timing brief
- Brief fields: shot, effect, start frame, anticipation, peak frame, tail/dissipate, camera (`CAM_`), silhouette read (yes/no), and game-or-cinematic.
- Approve motion at low domain resolution / low particle count first, then raise the settings.
source: vendor/blender-skills/.claude/skills/vfx-fx/references/fx-timing-brief.md

### Stylized shape language and proportion
- Shape language: circle/oval = friendly (heroes, cute creatures); square/rectangle = stable (architecture, guards); triangle = dynamic/dangerous (villains, spikes, roofs); combine consistently per character/faction.
- Exaggeration: head 25–40% of height, larger hands for expressiveness, enlarged eyes, tapered limbs with simplified joints, oversized weapons for readability.
- Palette: 3–5 core colors plus neutrals; reserve saturated accents for interactive elements; desaturate backgrounds and saturate foreground subjects.
- Materials: hand-painted albedo over PBR accuracy, flat/stepped roughness, rim lighting baked into texture, no photoreal micro-detail.
source: vendor/blender-skills/.claude/skills/stylized-style/SKILL.md

### NPR shader setups
- Cel: Layer Weight or Fresnel → ColorRamp with 3 stops (shadow/mid/highlight) → mix into base color.
- Outline (inverted hull): Solidify −0.02 m, flip normals, black emission material, backface culling off; render as a separate pass and composite over beauty.
- Rim: Fresnel 1.5 → multiply → add to emission; warm `#FFAA66` for heroes, cool for villains.
- Specular 0–0.2 for a flat look, or a hard ColorRamp on the specular output; sun size 0° and small area lights give hard terminators; bake the NPR result to textures for engines without toon shaders.
source: vendor/blender-skills/.claude/skills/stylized-style/references/npr-shaders.md

### Neon, synthwave and vaporwave
- Neon retrofuturism overall: sunset gradients, grid perspective, chrome + neon, 80s future memory.
- Synthwave: purple/orange dusk, grid ground, wireframe mountains, hot neon edges, black chrome.
- Vaporwave: pastel pink/cyan, classical busts, VHS, palms, Japanese type, soft glitch.
source: vendor/blender-skills/.claude/skills/neon-retrofuturism/SKILL.md; vendor/blender-skills/.claude/skills/neon-retrofuturism/references/synthwave.md; vendor/blender-skills/.claude/skills/neon-retrofuturism/references/vaporwave.md

### Dream and surreal devices
- Mood: logic bent, scale play, soft physics, symbolic props; color and light can ignore physical logic.
- Devices: impossible scale, floating objects, mirrored rooms, physics-defying cloth, and color that ignores light logic.
source: vendor/blender-skills/.claude/skills/dream-surreal-mood/SKILL.md; vendor/blender-skills/.claude/skills/dream-surreal-mood/references/surreal-devices.md

### Director workflow and reference-image match
- Workflow: Analyze → Plan → Brief → Delegate → Execute via MCP → Validate → Deliver; never skip planning and prefer MCP execution over UI instructions.
- Analysis questions: asset purpose (hero/standard/background), target (game/cinematic/portfolio), platform, style, animation need, export format.
- Reference-image loop (mandatory when an image is attached): written Reference Analysis before any MCP call → baseline screenshot → camera match (`CAM_*` + `EMPTY_CamTarget_*`) → geometry tiers (silhouette → panel breaks → greebles) → materials → lighting → grading → compare loop ≥1 and ×3 max → visual-match checklist.
- Production brief lists type, target, style, poly/texture budgets, export, pivot, animation, active skills, pipeline phases, and an ordered MCP execution plan.
source: vendor/blender-skills/.claude/skills/blender-director/SKILL.md

### MCP tool protocol
- Read MCP tool schemas before calling; descriptor names and parameters vary by version, and descriptors are authoritative.
- Protocol: verify the connection → create the collection hierarchy (`COL_`) → execute incrementally → query state after each phase → screenshot the viewport → run validation before export.
- Prefer dedicated MCP tools over `execute_blender_code`; reserve code for modifier stacks, UV editing, batch rename/cleanup, and exports without a tool; always save the `.blend` before code execution.
- Common fallbacks: create collection, rename object + data, apply transforms, merge by distance (threshold 0.0001).
- Error recovery: reconnect on connection loss, split timeouts into smaller steps, re-query the scene when objects are missing, read the traceback and retry; never silently skip a failed operation.
source: vendor/blender-skills/.claude/skills/references/mcp-tools.md

### MCP integration rules
- MCP-first priority: check descriptors → read schemas → execute via MCP → validate via scene queries → fall back to UI instructions only when MCP lacks the capability.
- Establish the collection tree immediately: COL_Reference, COL_Blockout, COL_HighPoly, COL_LowPoly, COL_Collision, COL_Lights, COL_Export.
- Non-destructive defaults: duplicate before destructive operations, hide backups rather than deleting, apply modifiers only at export unless downstream work needs them, and document the modifier stack.
- Query after each phase: object count/names, triangle counts, material count, collection membership, origins, transform application status.
- Anti-patterns: UI walkthroughs, assuming scene state without querying, destructive apply without backup, export without validation.
source: vendor/blender-skills/.claude/skills/references/mcp-integration.md

### Visual match checklist
- Run after geometry, materials, lighting and grading when a reference image was provided; compare at the same camera angle.
- Pass threshold: ≥8/10 categories rated Match or Close; rate each as Match/Close/Miss, add one actionable fix per Miss, and re-run after fixes (max 3 iterations).
- Categories: camera & composition, silhouette & proportions, depth & surface breakup, materials & color, lighting, rendering & grading, plus per-asset hero features.
- Auto-fail conditions: wrong side of the subject shown, hull blows white during playback, only a section shown when the full subject was requested, emission keyframes on structural materials, or an export mesh blocking review.
source: vendor/blender-skills/.claude/skills/references/visual-match-checklist.md

### Asset validation checklist
- Scale & transform: 1 unit = 1m, origin at a logical pivot (floor/grip/hinge), transforms applied, correct forward axis for the target engine.
- Topology: quad-dominant, no n-gons on deforming areas, no duplicates/loose geometry/non-manifold faces, correct normals, weighted normals or sharp edges for hard edges.
- UVs: efficient layout, consistent texel density, seams on hidden/construction edges, no overlap unless intentional, lightmap channel if baked lighting is required.
- Materials: minimal count (props 1–3), plausible PBR or intentionally stylized values, texture resolution within budget (512/1024/2048/4096), no unused slots, `MAT_` names.
- Performance / game-ready: polycount within budget, triangle count verified, LODs if required, instances for repeats, collision proxy in `COL_Collision`, readable silhouette, style consistency.
source: vendor/blender-skills/.claude/skills/references/validation-checklist.md

### Universal asset pipeline
- Order: reference collection → planning → scale planning → primary shapes → secondary shapes → silhouette review → topology strategy → modeling → cleanup → UV planning/unwrap → materials → look dev compare → optimization → rig/animate → collision → export → validation.
- Reference collection: gather ortho views, real dimensions and style refs; extract a 5–8 hex palette, camera angle, key light direction and hero features; note construction logic for hard surface.
- Scale: 1 Blender unit = 1 meter by default; place a 1.8m human reference and lock the pivot/origin strategy before modeling.
- Detail tiers: silhouette first, then tier-2 panel breaks (ribs, belts, recesses), then tier-3 greebles; emissive lights use per-object materials only and are never animated on shared hull materials.
- Per-type pipelines cover hard-surface prop, environment modular kit, character/creature, procedural kit, cinematic set, and reference-image match.
source: vendor/blender-skills/.claude/skills/references/asset-pipeline.md

### Naming conventions
- Prefixes: `COL_` collections, `SM_` meshes, `MAT_` materials, `T_` textures, `AN_` animations, `ARM_` armatures, `GN_` geometry node groups, `CAM_` cameras, `LGT_` lights.
- Mesh `SM_[Category]_[Descriptor]_[Variant]`; material `MAT_[SurfaceType]_[Descriptor]`; texture `T_[Asset]_[MapType]` with map suffixes `_BC`, `_N`, `_ORM`, `_R`, `_M`, `_AO`, `_E`, `_H`.
- Collections nest under `COL_ProjectName` with Reference / Blockout / Geo (Hero, Background, LOD) / Collision / Lights / Cameras / Export.
- LODs `SM_AssetName_LOD0`..`LOD3`; collision `SM_AssetName_COL`, `_COL_UBX` (Unreal box), `_COL_UCX` (Unreal convex).
- Rules: PascalCase after the prefix, underscores not spaces, sequential `_01`/`_02`, descriptive not generic, names under 64 characters for engine compatibility.
source: vendor/blender-skills/.claude/skills/references/naming-conventions.md

## From blenderwright

Paraphrased from the vendored `vendor/blenderwright` project (**MIT**, © 2026
HoldMyBeer-gg). Numeric values and parameter names are kept from the source;
wording is condensed and no source code is copied except the short recipe below,
which is attributed in place.

### render_animation - the frame-range still path
- `render_animation(filepath="", format="PNG")` renders the whole scene frame range to numbered image files. `filepath` is a prefix, not a full name (empty means temp `render_`); formats are PNG, JPEG, OPEN_EXR, TIFF, BMP; engines accepted are BLENDER_EEVEE / BLENDER_EEVEE_NEXT / CYCLES / BLENDER_WORKBENCH.
- The handler stores `scene.render.filepath` and `image_settings.file_format`, sets the prefix+format, runs `bpy.ops.render.render(animation=True)`, then restores both; the range always comes from the scene, never from the call.
- Timeout budget: animation renders allow ANIMATION_TIMEOUT = 43200 s (12 h), a still RENDER_TIMEOUT = 3600 s, default command timeout 30 s. The prefix is resolved absolute because Blender resolves a relative path against the `.blend`.
source: vendor/blenderwright/src/blenderwright/tools/rendering.py:150; vendor/blenderwright/addon/handlers/rendering.py:102; vendor/blenderwright/src/blenderwright/connection.py:29

### Image sequence to video - containers and codecs
- `add_image_sequence_strip(first_frame, name="", channel=1, frame_start=1)` loads every numbered sibling of the first frame that shares its prefix and extension (same folder, number >= first), in numeric order, up to MAX_SEQUENCE_IMAGES = 100000; the strip holds one image per timeline frame. Channel is 1-128, frame_start up to +/-1048574.
- `render_video(filepath="", container="MPEG4", quality="HIGH", audio_codec="AAC")` renders the scene range to one file, using sequencer strips when present (so already-rendered frames assemble in seconds) and the 3D scene otherwise; extension must match the container: MPEG4 -> .mp4, MKV -> .mkv, WEBM -> .webm.
- Codec map: MPEG4 -> H264, MKV -> H264, WEBM -> WEBM. Audio codecs NONE/AAC/MP3/OPUS, but WEBM accepts only OPUS or NONE. Quality presets LOWEST, VERYLOW, LOW, MEDIUM, HIGH, PERC_LOSSLESS, LOSSLESS become ffmpeg `constant_rate_factor`; the renderer is switched to FFMPEG and the previous settings restored in a finally block.
source: vendor/blenderwright/src/blenderwright/tools/sequencer.py:60,178; vendor/blenderwright/addon/handlers/sequencer.py:13,171

### Render an image sequence and encode it in one `execute_code`
Adapted from blenderwright `tools/rendering.py` / `tools/sequencer.py` (MIT © 2026 HoldMyBeer-gg). Renders a PNG sequence, assembles it in the sequencer, then encodes H.264 in MP4; change `ffmpeg.format`/`codec` to MKV+H264 or WEBM+WEBM for the other containers.

```python
import bpy, os
scene = bpy.context.scene
out = os.path.join(bpy.app.tempdir, "seq"); os.makedirs(out, exist_ok=True)
scene.frame_start, scene.frame_end = 1, 120
scene.render.filepath = os.path.join(out, "f_")
scene.render.image_settings.file_format = "PNG"
bpy.ops.render.render(animation=True)          # writes f_0001.png ... f_0120.png

ed = scene.sequence_editor or scene.sequence_editor_create()
strip = ed.strips.new_image("frames", os.path.join(out, "f_0001.png"), 1, 1)
for n in range(2, 121):
    strip.elements.append(f"f_{n:04d}.png")

r = scene.render
r.image_settings.file_format = "FFMPEG"
if hasattr(r.image_settings, "media_type"):    # Blender 5.x splits image/video
    r.image_settings.media_type = "VIDEO"
r.ffmpeg.format, r.ffmpeg.codec = "MPEG4", "H264"   # MKV=H264, WEBM=WEBM
r.ffmpeg.constant_rate_factor = "HIGH"
r.filepath = os.path.join(bpy.app.tempdir, "anim.mp4")
bpy.ops.render.render(animation=True); print("wrote", r.filepath)
```
source: vendor/blenderwright/src/blenderwright/tools/rendering.py; vendor/blenderwright/src/blenderwright/tools/sequencer.py

### Procedural material patterns
- `create_procedural_material(name, pattern, scale=5.0, detail=2.0, distortion=0.0, roughness=0.5, metallic=0.0, colors=None, banded=False, connect_to_bsdf=True)` builds the full node graph in one call: coordinates -> mapping -> the pattern's texture nodes -> a tuned colour ramp -> Principled BSDF, and returns the node names for later edits.
- Pattern set: gradient, noise, cloud, voronoi, veins, scales, stripes, wood, marble, weave, plasma, fire, sparks (runes is raster-only, not a shader graph). `plasma` = layered noise into a wide colour sweep (energy/magic/heat); `fire` = vertically-masked noise into a heat ramp (flame/lava/embers); `sparks` = sparse bright points (embers/glints/star fields).
- Knobs: `scale` default 5.0 (1-3 for large forms, 20+ for fine detail), `detail` 0-15 (noise, cloud, wood, marble, plasma, fire only), `distortion` warps (same set; 0.5-2.0 makes wood/marble organic), `banded=True` forces CONSTANT ramp interpolation (discrete regions / cel shading). `ignored_params` reports args a pattern cannot use.
source: vendor/blenderwright/src/blenderwright/tools/materials.py:118,881

### ColorRamp controls
- A new ramp is two stops, black at 0.0 and white at 1.0; a ramp holds at most 32 stops. `add_color_ramp_element(position 0-1, color RGB/RGBA)`, `remove_color_ramp_element(index)` (at least one stop must remain), `set_color_ramp_element(index, position?, color?)` to move/recolor, `get_color_ramp` to read indices/positions before editing since moves reorder stops.
- Interpolation set: EASE, CARDINAL, LINEAR, B_SPLINE, CONSTANT. CONSTANT gives hard-edged bands with no blending - the way to turn noise/voronoi into discrete regions (scale plates, cracked mud, cel shading); EASE and B_SPLINE fall off softer than LINEAR. `color_mode` is RGB, HSV or HSL - HSV sweeps through hues between two stops instead of blending through grey.
- Fire ramp recipe from the source: dark red, orange, yellow and white bunched toward the top; rust wants a hard break between metal and oxide.
source: vendor/blenderwright/src/blenderwright/tools/materials.py:113,705,814,858

### Sweeping a profile along a path
- `sweep_profile_along_path(path_points, profile="CIRCLE", radius=1.0, sides=16, resolution=0, twist=0.0, caps=True, name="Sweep")` makes a solid tube/pipe/cable/rope. Parallel transport orients the profile so it does not crease where the path turns vertical. Profiles: CIRCLE, SQUARE, HEXAGON, TRIANGLE.
- Limits: 2-2000 path points, consecutive points must differ (a repeat is a zero-length segment with no direction), all coordinates finite; `radius` 1e-6-10000, `sides` 3-1024, `resolution` 0-1000 (0 uses the points exactly, 8-16 smooths with a centripetal Catmull-Rom spline), `twist` +/-100 rad spread evenly, `caps` for a printable solid.
- `analyze_sweep_path(path_points, radius=1.0, resolution=0)` checks clearance without building. It reports min_clearance_ratio (curvature radius / profile radius at the tightest station), tightest_index/point, self_intersects, and station counts below 1.0 and below 1.5. Below 1.0 the rings overlap inside the bend - still watertight and manifold, so ordinary mesh checks miss it; aim for 1.5+.
source: vendor/blenderwright/src/blenderwright/tools/sweep.py:67,136

### Keyframes, interpolation and follow-path
- Interpolation list: CONSTANT, LINEAR, BEZIER, SINE, QUAD, CUBIC, QUART, QUINT, EXPO, CIRC, BACK, BOUNCE, ELASTIC. Animatable data paths are whitelisted: location, rotation_euler, rotation_quaternion, scale, and the [0]/[1]/[2] indexed variants. Frames run 0-1048574; a `set_frame_range` end must be greater than its start.
- `create_animation_path(object_name, path_object)` attaches a Follow Path constraint so an object rides a curve. Around it: insert_keyframe, delete_keyframe, set_interpolation, list_keyframes, clear_animation.
source: vendor/blenderwright/src/blenderwright/tools/animation.py:32,117,189

### Turntable and studio-lighting prompts
- `animation_turntable`: frame range 1-120 (5 s at 24 fps); rotation-Z keyframe 0 at frame 1 and 6.28318 (360 deg) at frame 120; LINEAR interpolation for smooth rotation; camera pointed at the object.
- `lighting_principles`: three-point rig - key 45 deg above/to one side ~1000 W, fill opposite ~300 W, rim behind toward camera ~500 W; energy ratio Key:Fill:Rim = 3:1:1.5; warm 2700-4000K vs cool 5000-7000K (mix for cinematic contrast); EEVEE for speed/stylised, Cycles for photorealism; HDRI via Environment Texture rotated with a Mapping node.
- `studio_lighting_setup`: 10 m x 10 m infinity-cove backdrop; area key 45 deg above/right at ~3 m, 1000 W; fill opposite at ~2 m, 300 W, larger size for softness; rim behind at ~2 m, 500 W; world background black (0,0,0) or (0.02,0.02,0.02); Cycles 256 samples (512 final) or EEVEE soft shadows, 1920x1080.
source: vendor/blenderwright/src/blenderwright/prompts/workflows.py:84,164,202

### Auto-critique after structural edits
- After any structural operation - add/delete, boolean, modifier apply, sculpt, material or lighting change, camera move, mesh edit - capture `get_viewport_screenshot(mode='fast')` and critique it before the next step. Skip for renames, queries, collection moves, save/export and keyframe-only edits.
- Critique checklist: geometry errors from this angle, proportions against scale references, clean topology (no floating verts, holes or inverted normals), adequate lighting, and the next fix. Budget: 2-3 sentences, ONE screenshot per operation or batch, captured once at the end of a multi-step build, and respect a request to skip screenshots.
source: vendor/blenderwright/src/blenderwright/prompts/workflows.py:294

### Fast OpenGL viewport capture
- `handle_fast_viewport_capture(width=1920, height=1080)` skips the render cycle: it sets the resolution and calls `bpy.ops.render.opengl(write_still=True)` inside a `temp_override` of a VIEW_3D window/area (it walks `window_manager.windows` looking for `area.type == 'VIEW_3D'`).
- It then takes the "Render Result" image, `save_render()`s it to a temp PNG, returns base64 with `mode: "fast"`, and restores resolution in a finally block. The full path, `handle_capture_viewport`, instead runs `bpy.ops.render.render(write_still=True)` and also preserves filepath and file_format around it.
source: vendor/blenderwright/addon/handlers/camera.py:234
