---
name: rmcp-blender-skills
description: Drive this workspace's Blender MCP server in the user's live scene. Use for making, posing, moving, shading, lighting, rendering or exporting Blender work; reconstructing a cover, painting or photo in 3D; reviewing another agent's scene; and diagnosing mismatches between a tool report and the visible result. Includes reference-first visual iteration, safe asset reuse, and multi-agent handoff.
---

# Driving this Blender server

Blender is the user's live application, not a disposable render worker. The
agent, MCP server, editor and Blender may have different filesystem views.
Discover current tool schemas; do not rely on a remembered tool count.

## Start by seeing the actual state

1. Call `scene_info`: file, scene, camera, frame, resolution, object names and
   relevant hierarchy. Inspect object/data sharing before editing an asset.
2. Use **`look`** to inspect the actual image. For a reference task, see both
   the reference and the current camera view before diagnosing the mismatch.
   `mesh_report` and `wireframe` support this; they do not replace seeing it.
3. If an object is missing on screen, `reveal` can diagnose file/view-layer/
   local-view/visibility problems. With an object name it also unhides and
   frames it, so don't use it indiscriminately on deliberately hidden backups.
4. Translate the request into observable constraints: which anatomical side,
   which surface faces the camera, where the thumb/handle/front is, what
   overlaps what, and what must not be visible. Owner corrections take priority
   over an earlier agent's interpretation.

## By task

| job | tools |
|---|---|
| see the actual image | `look` (viewport, camera, angles, frames, image), `screenshot`, `compare_reference` |
| measure / diagnose | `scene`, `scene_info`, `object_info`, `mesh_report`, `wireframe`, `reveal` |
| describe pixels when images cannot be read | `image_report`, `image_report_rust` |
| make / reuse | `text`, `duplicate`, `array`, `modifier`, `boolean`, `search_assets`, `import_asset` |
| place / shade / illuminate | `place`, `aim`, `material`, `light` |
| deliver | `render`, `render_animation`, `export` |
| remove deliberately | `remove` (check `purge` before calling) |
| specialist geometry and node graphs | `execute_code`, within the runtime guard |

## The working loop

**Inspect reference → semantic landmarks → clean source / backup → neutral
geometry → live `look` → render → `compare_reference` → one focused correction.**
After the pose and silhouette work, add material, lighting, then compositing.
Do not tune a painted texture to conceal incorrect geometry. Preserve a pose
the owner likes instead of repeatedly refitting the whole object.

- Use the cover camera to judge composition and `look(mode="angles")` with
  front/right/top/three-quarter views to judge real volume and attachments.
- `look` targets control framing; they do not necessarily isolate other scene
  objects. For a clear hero view, temporarily isolate visibility with a saved
  per-view-layer state, or make a separate review scene sharing the subject.
- Keep a neutral-clay review available. A dark material, busy background or
  misleading projected feature can hide an orientation error.
- Keep the main camera unchanged once matched. `aim` is useful for a new
  camera, not a harmless diagnostic on a carefully matched cover camera.
- Serialize Blender mutations, renders and captures. They share global state;
  parallel state-changing calls can race even when each tool restores its own
  settings. Restore script-owned context/visibility in `finally`.

## Matching a reference picture

1. **Read anatomy and occlusion, not just silhouette.** Frame-left and anatomical
   left are different. Identify thumb, palm, wrist and each digit from the photo
   and clay views. A bounding-box extreme is not an anatomical landmark. Average
   surface normals cannot identify a palm: both sides of a closed hand face out.
2. **Place named landmarks in full-frame coordinates.** Record `(u,v)` from the
   top-left, plus intended depth. A crop is a viewing aid, not a new coordinate
   system. Record its bounds when sending a review.
3. **Use the actual camera model.** For the special case of a square image,
   horizontal 36 mm sensor, 50 mm perspective lens, no shift, and camera at
   `(0,-30,0)` looking along +Y:

   ```text
   W = (y + 30) * 0.72
   x = (u - 0.5) * W
   z = (0.5 - v) * W
   ```

   This is not a universal Blender formula. Different orientation, aspect,
   sensor fit, focal length, shift or orthographic projection needs the actual
   matrices/intrinsics. Changing Y with X/Z fixed changes projected placement.
4. **Compare after each successful render.** Use `compare_reference` with the
   reference and render paths. `region="u0 v0 u1 v1"` crops both consistently;
   `mask` can suppress explicitly unfinished regions. Read the returned picture
   and name the largest remaining differences. A failed render must not be
   followed by a comparison against its stale output.
5. **Judge by eye, not a global score.** SSIM/histogram averages can reward a
   featureless grey wash. Check silhouette, named landmarks, occlusion, value
   hierarchy, materials and mood separately. Numerical fit supports visual
   judgment; it does not overrule a visibly wrong pose.
6. **Ask a focused question when interpretation remains ambiguous.** Don't
   demand the owner diagnose size/rotation while ignoring their explicit
   palm/thumb/wrist instructions. Confirm the disputed feature itself.

For the full method, equations, worked hand-deformation case and failure table,
read **`docs/reference-reconstruction.md`**. For the live NEFAS scene state and
rollback objects, read **`docs/NEFAS-HANDS-HANDOFF.md`**; that is a handoff, not a
universal hand recipe.

## Reuse an asset without damaging it

- Discover the actual selected asset through the Asset Browser context and its
  library path, rather than brute-forcing filenames. Exact names may include
  trailing spaces. External library reads still require the configured roots
  and an allowed tool/call shape; do not weaken a guard to get around a refusal.
- Keep a clean hidden source. `object.copy()` still shares mesh data; copy
  `.data` before vertex edits. Check material, image and node-group sharing too.
- If an existing attempt is deformed, reload the known clean asset rather than
  stacking more guessed transforms onto it. Preserve the previous attempt for
  comparison; do not globally undo another participant's work.
- Inspect meaningful segmentation (face sets, vertex groups, a real rig,
  topology branches). The NEFAS asset's `.sculpt_face_set` groups separated the
  palm and each phalanx. Intersections of adjacent groups supplied joint seams;
  weighted per-segment transforms curled actual fingers independently.
- Asset-specific group IDs and unit scales are not transferable. Verify them
  before using a recipe. A coordinate cutoff or a large X gap can select palm
  or neighboring finger vertices instead of a thumb.
- Preserve source geometry and a named checkpoint before a structural edit.
  A static posed deformation is not automatically an animation-ready rig.

## Shape, depth and material are different problems

- A traced mask filled and inflated is a **bas-relief**. It can be appropriate
  for an agreed fixed-view 2.5D deliverable, but a puffy card is not a volumetric
  hand. Side views reveal this immediately.
- Camera projection cannot invent hidden anatomy. It is useful after geometry
  is correct, with an explicit strategy for sides/back and changing viewpoints.
- Blender image UV V runs bottom-up; image-review frame v runs top-down. For
  normalized frame coordinates, image UV is `(u, 1-v)`. The Texture Coordinate
  **Camera** socket is camera-space data, not a ready-made normalized projector.
- Don't use raw image brightness as anatomical depth. Painting highlights,
  strokes and scanlines become spikes or crumpling; normal-direction displacement
  also moves silhouette edges. Build large forms first, use small controlled bump
  only for surface detail, and verify displacement against mesh resolution.
- Model nails/claws as tapered curved solids/shells with seated roots, not straight
  cone pins. Inspect from the side for floating bases and from the front for the
  intended silhouette. Closed/manifold does not rule out self-intersection.
- Find shader nodes by **type**, not localized node names. Put material colors
  into shader inputs; `diffuse_color` only changes solid viewport appearance.
- Inspect the full data graph before claiming an image is unused. An image with
  no material users may feed the compositor, as `CanvasGrain` initially did in
  NEFAS. Also check render-pipeline flags and node mute/bypass states:
  `CanvasOverlay` was connected but muted, so its image did not affect that
  render. Connections and user counts alone do not prove visual contribution.
- An emission strength of 1 is not a promise of pixel-identical output: BSDF
  lighting, image color space, AgX, exposure, alpha and compositing still matter.

## Review cheaply and honestly

- Render a tight crop with `use_border` and `use_crop_to_border`, preferably in
  an independent review scene. For top-left frame bounds `[u0,u1] × [v0,v1]`,
  Blender's border Y bounds are `[1-v1,1-v0]`. Preserve the camera rays.
- Use a distinct path for each diagnostic or concurrent comparison output.
  Reusing one comparison filename from parallel writers can corrupt the read.
- `render`/`export` are the output-file tools. Verify that a claimed deliverable
  can actually be opened from the expected host context; a reported server path
  is not proof it exists in Blender's or the editor's filesystem view.
- Don't mistake an old file, failed render, thumbnail or frame for the current
  live state. Name the frame, source path and active scene in the handoff.
- Record concrete visual findings: "thumb passes behind the ray; wrist cap no
  longer projects beyond palm", not an unqualified "perfect match".
- Geometry checks (finite coordinates, bounds, normals, boundary/non-manifold
  edges, zero-area faces) complement profile/underside checks; no single metric
  certifies anatomy or absence of self-intersections.

## Safe execution in a shared Blender

Use the live RNA enums rather than guessing enum identifiers, and read the
current render engine before changing it. Shader/node/socket APIs differ by
Blender version; inspect the relevant surface when a recipe fails.

`execute_code` permits bpy, bmesh, mathutils and selected pure-Python helpers;
it is not general host access. This guard can also refuse lambdas, `yield`,
computed `getattr` names and interpreter internals. Use explicit ordinary loops,
small functions and literal attributes. Rewrite within the policy, not around it.

File scope comes from the running server's **`BLENDER_WRITE_ROOTS`** and
**`BLENDER_READ_ROOTS`** (plural). A newly edited shell profile does not update
an already-running server. Don't hardcode an owner's library path into policy.
Never confuse live datablock changes, a PNG render, and saving the `.blend`.
Leave saving/acceptance to the owner's workflow and report unsaved state.

## Coordination and persistent records

- One agent owns scene mutations; reviewers inspect and send recommendations.
  Agree that contract before two agents start changing the same Blender.
- Send each reviewer a brief delta, current output path, camera/crop/frame and
  the question to judge. A queued message is not a completed peer review.
- After a meaningful iteration record intent, changed object/data names, source
  and backup, parameters/landmarks, actual `look`/compare checks, limitations,
  output paths and what remains. Mark superseded diagnoses and stale renders.
- Keep a short live-scene custom-property pointer (for example
  `Scene['agent_handoff']`) plus a durable editor-managed Markdown log. Read it
  before resuming; never assume the last chat summary equals the live scene.

## Report signatures worth recognizing

- **Flat grey render:** it may be an empty/wrong camera or visibility/context
  problem, not bad geometry. Inspect the camera view, file and scene before
  moving the camera or changing materials.
- **`faces 499 -> 0`** after a boolean: the cutter may contain the subject.
  Inspect overlap and operation; don't apply another blind boolean.
- **`loose parts: N`:** disconnected components, not automatically an error.
  Fingernail meshes may be intentional; gaps in a skin may not be.
- **Base vs evaluated counts:** reports may describe the base while renders
  apply modifiers. Inspect the evaluated mesh for final geometry/ray tests.
- **Bridge unreachable or timeout:** the operation may still be running. Once
  reachable, inspect what landed before retrying; don't duplicate a long build.
- **Purged data:** orphan removal is real. Fake-user checkpoints and user assets
  should not be swept away by opportunistic cleanup.

## Deliberate limits

There is no dependable global undo tool: data-API edits and removals need
explicit inverses or retained sources. There is no inline viewport app or
trajectory recorder; visual feedback arrives as image blocks.

The HTTP transport allows configured client hosts (including
`host.docker.internal`, `127.0.0.1`, `localhost`) and requires its token. A
transport failure is not permission to circumvent host checks or expose secrets.
See `docs/build-and-transport.md` and `docs/blender-sec.md` for setup details.

## Further reading

- `docs/reference-reconstruction.md`: detailed reference-to-3D workflow, hand
  case study, deformation/claw math, diagnostics and manual review exercises.
- `docs/NEFAS-HANDS-HANDOFF.md`: current scene-specific state and change log.
- `docs/blender-notes.md`: Blender traps and version-specific findings.
- `docs/techniques.md`: broader technique digest; distinguish generic/vendor
  recipes from what this guarded server and Blender version actually allow.
- `docs/scene-craft.md`, `docs/scene-craft-island.py`: a procedural diorama case.
- `docs/scene-craft-cartoon.md`: fixed-view cartoon construction and animation.
- `docs/text-vision.md`: textual measurements when image blocks are unavailable.
