# Reference reconstruction

**Rebuilding a posed 3D asset from a cover image and reference photos through this
repo's Blender MCP server.**

This is a field guide, not a session log. It distils the *NEFAS hands* rebuild — the
frame-left hand of an album cover — into a method you can apply to the next
reconstruction: what to inspect first, how to read anatomy from a reference, how to map
frame coordinates to world coordinates, how to segment and deform a clean source mesh,
how to build nails, how to review in an isolated scene, and how to validate and hand off.
It also records the failures from that rebuild and their causes, because several were
expensive.

## Provenance and confidence markers — read before quoting a number

- **Source of record:** `docs/NEFAS-HANDS-HANDOFF.md`, the append-only handoff for this
  asset, and the verified-live brief supplied for the rebuild. Case-study facts come from
  those two; `docs/techniques.md` and `docs/scene-craft.md` supply the sibling techniques
  and the island scene. Where this guide sharpens a statement, it says so.
- **Status:** the owner endorsed the *pass-1 clay blockout* and the palm/thumb placement
  ("looking great so far in terms of the models"). That is an endorsement, **not** final
  approval and **not** a photorealism benchmark. The claws and the skin material are not
  signed off. The owner has since approved the second (frame-right) hand and the rest of the
  scene, and both hands now exist; **that work is ongoing and is not recorded here as
  finished.**
- **[FIELD-TESTED]** — observed on this asset (or on the island scene in
  `scene-craft.md`), with the number actually used.
- **[GENERAL]** — a standard technique stated correctly but not exercised end-to-end here.
- **[UNVERIFIED]** — a plausible generalization the session did **not** prove. Treat as a
  hypothesis and test before relying on it.
- **Code blocks are illustrative, not a verbatim run log** — pseudo-Python, elided helpers
  and all. Treat every snippet as illustrative unless it is marked `[RUN]`, reproduce it
  against the live guard before relying on it, and replace any disk access with a tool call
  (§13).
- Absolute asset paths and datablock names below are *case-study provenance*. Do not bake
  them into a reusable skill, and do not assume another `.blend` has them.

## Contents

1. First contact: the live-scene inspection protocol
2. Reading the reference: the anatomy contract
3. Provenance: importing a clean asset without guessing
4. Pipeline order: reference first, materials last
5. Frame ↔ world: the landmark mapping
6. Segmentation: face sets, joints and tips
7. Deformation: weights, diffusion, the palm fit, finger rotation
8. Output mesh hygiene
9. Nails and claws
10. The isolated review scene
11. The visual validation loop
12. Shading, materials and compositing
13. Runtime, guards and scripting discipline
14. Mesh health checks
15. Documentation and handoff
16. Failure table
17. Reproducibility and review exercises
18. Reusable checklists
19. Open items

---

## 1. First contact: the live-scene inspection protocol

Never act on a summary, a screenshot caption, or an ASCII view of a scene you are about
to change. **Start with `scene_info`**, read the returned facts, then confirm them with a
real look. `reveal` answers "which Blender, which file, which view layer, and which
object am I about to touch", and `object_info` gives one object in full. [FIELD-TESTED]

Confirm, from the data rather than from memory:

- **File, scene, view layer.** Case study: `ooo_cover_scene2.blend`, scene `Scene`,
  Blender 4.2.18 LTS, EEVEE_NEXT, 1080×1080. A different scene in the same window is a
  different job — resolve the scene by name (`bpy.data.scenes["Scene"]`), never trust
  `bpy.context.scene`, because the owner or another agent can switch it.
- **Camera and framing.** Case study camera: location `(0, -30, 0)`, rotation
  `(pi/2, 0, 0)` (looks `+Y`), 50 mm lens, 36 mm sensor, square frame. Record all of
  these; the mapping in §5 depends on them.
- **Resolution and frame range.** Render resolution and the current frame decide what a
  render or a `compare_reference` call actually shows.
- **Object → data sharing.** Two objects can share one mesh datablock; deforming one
  edits both. `object_info` exposes the mesh datablock name — compare them. Blender reuses
  `.data` for linked duplicates; a **copy** is `obj.data = obj.data.copy()`. Materials and
  node groups can be shared the same way. This is the single most under-noticed trap in a
  live scene. [FIELD-TESTED — a shared mesh produced a doubled deformation]
- **Exact object names, including trailing spaces.** The source hand was appended as
  `'Hand - Stylized '` — **with a trailing space**. Names are also global across scenes in
  a `.blend`, so a helper that recreates `"title"` can clobber another scene's `"title"`.
  Match names byte-for-byte.
- **Lights, materials, modifiers.** Which lights exist, which materials are assigned, and
  which modifiers are on which object — read the real values, not the names. The posed
  hand carried a subdivision modifier `Pose smoothing` at levels 2 / render 2; the number
  that matters in a render is the evaluated one.
- **Inspect the actual live look.** `look` returns a real image; read it. A `scene_info`
  dump supports the look, it does not replace it. Numbers pass while the picture fails
  (§16, the "empty grey match" entry).

## 2. Reading the reference: the anatomy contract

A reference photo and a cover image are evidence, and evidence can be misread. Write down
the anatomy **before** you touch geometry.

- **State the side explicitly: "left of frame" vs "anatomical left".** The case study
  worked the hand on the **frame-left** side, which is the subject's **anatomical right**
  hand. The correct reference image was literally named `right hand, left side real.png`
  (the anatomical right hand, for the frame-left position) and `left hand, right side
  real.png` was the frame-right one. Conflating frame-side with body-side is the root of
  the worst class of miss here. [FIELD-TESTED]
- **The owner's words override a peer's read.** Stated requirements for this asset:
  palm faces the camera; the thumb points up / up-right and sits behind `Beam_UpLeft`;
  **no visible wrist**; four separately curled fingers plus the thumb. A peer's labels
  ("4 digits", "top curl is the thumb", "back faces camera") were **superseded** and must
  not be trusted. When the owner and a peer disagree, the owner wins. [FIELD-TESTED]
- **Name the anatomical landmarks before changing anything.** Palm, thumb (with its
  proximal/distal phalanges), index, middle, ring, little; the wrist cuff; each finger's
  root / PIP / DIP / tip. Say which is which in frame coordinates. A landmark you cannot
  name is a landmark you will mis-place.
- **Extrema and bounding-box centres are not anatomy.** A mesh's coordinate extrema, its
  bbox centre, or its mean tip-Y are not a wrist and not a fingertip. The up-right spear
  at `u≈0.47, v≈0.40` is the **thumb**, not the wrist. Bbox-fitting a mesh and calling
  its extreme a joint produced the earlier failed attempts. [FIELD-TESTED]
- **Pose identity and occlusion beat scalar metrics.** Two different poses can share a
  bbox. A fingertip hidden behind the palm is still there. Judge the *posed* silhouette
  from multiple views and from the photographs; do not reduce a hand to a number.
- **An empty grey match is not success.** Matching a compute metric against a mostly
  empty grey region rewards flatness. Judge by eye; ask the owner when a busy area is
  ambiguous, because a wrong read costs a whole pass.

## 3. Provenance: importing a clean asset without guessing

Get the exact source path from the running app, not from a filename brute-force.

- **Ask the Asset Browser context for the real path.** `bpy.context.asset.full_library_path`
  and `full_path` returned the exact bundle:
  `.../human-base-meshes-bundle-v1.4.1/human_base_meshes_bundle.blend`. No guessing.
  [FIELD-TESTED]
- **Append the named object into a new collection.** The pass-1 protocol appended the
  exact object `'Hand - Stylized '` (trailing space) into a fresh collection
  (`Hands_Astra`) under the approved read roots, leaving the source library file
  untouched. Your imported object is a **copy inside this file**; the library on disk does
  not change.
- **Never mutate the source in place; work on your own copy.** The clean source
  (`Astra.Hand.Source`, 871 verts with `.sculpt_face_set` anatomical segments) was kept
  hidden in viewport *and* render and **retained unchanged** as the second fallback.
  Deform the copy. [FIELD-TESTED]
- **Hide old failures; do not delete them.** `'Hand - Stylized '`, `'Hand - Stylized .001'`,
  `'Hand 180 test'`, `Hands3D`, `HandCard.L` stay hidden, with their prior visibility saved
  in `Scene['astra_attempt_visibility']`. The owner's assets are not yours to erase.
- **Do not run a global undo in someone else's live session.** Undo is global and can
  destroy work you cannot see. Prefer expressible inverses (re-create, re-import) and
  explicit backups.
- **Back up before you sculpt.** Before palm polish, the mesh datablock
  `Astra.Hand.ClayPass1` was stored with a **fake user** on and the exact name recorded in
  `Astra.Hand.L['astra_pass1_mesh']` for rollback. Rollback order: `ClayPass1` first,
  `Astra.Hand.Source` second. [FIELD-TESTED]
- **Copy a mesh before deforming it** — `obj.data = obj.data.copy()` — so a linked
  duplicate is not deformed twice.

## 4. Pipeline order: reference first, materials last

The order that worked, and the reason for each step:

1. **Neutral clay isolate.** Pose the hero in a plain grey material so silhouette, volume
   and anatomy are judged without colour distraction. The case study's `Astra.Clay` is
   grey and unpainted. **White clay is not a finished skin** — do not mistake a clean clay
   render for the finished look.
2. **Match the palm, thumb and finger pose.** Landmarks first (§2), then the blockout.
3. **Check independently in front, side, top and three-quarter views.** Side views are
   what confirm volume. Fingers that read correctly front-on can fuse or float in profile.
4. **Then the nails/claws.** They seat against the posed finger surface, so they come
   after the pose, never before.
5. **Then materials, lighting and compositing.** Skin texturing is the last stage; the
   handoff explicitly defers painted skin until the geometry and pose are settled.
   [FIELD-TESTED]

Two rules that keep you out of trouble:

- **Do not randomly re-fit a model the user likes.** Pass 1 was endorsed, so pass 2
  smoothed only the interior palm and **left the finger endpoints and overall placement
  alone**. Each pass extends; it does not re-roll the blockout.
- **Compare at the same camera and crop, and record full-frame coordinates.** Coordinates
  are quoted in frame fractions (top-left origin) so the next agent can reproduce the
  measurement. Give actual observations ("the index DIP is 0.02 left of the cover's"),
  not "great progress", when something is wrong.

## 5. Frame ↔ world: the landmark mapping

This is how a landmark in the reference image becomes a point in the scene. It is a
**special case**, valid only for the exact camera described.

**Case study [FIELD-TESTED].** Square perspective camera at `(0, -30, 0)` looking `+Y`,
50 mm lens on a 36 mm sensor. Let `u` be the horizontal frame fraction and `v` the
vertical frame fraction, both with **top-left origin**, and `y` the depth you choose:

```
W = (y + 30) * 0.72          # frame width at depth y, in scene units
X = (u - 0.5) * W
Z = (0.5 - v) * W
```

`0.72 = 2 * 30 * tan(fov_x/2) / 30` for this lens: at 30 units in front of the camera the
frame is `0.72·(distance)` wide. Use it to *measure* landmarks like a wrist or the thumb
spear, never to bbox-fit a mesh.

**Depth is a real input, not a detail.** Changing a landmark's depth while holding `X,Z`
fixed changes where it projects; changing depth with `u,v` fixed changes what occludes
what. Construct each point from the *desired* `u,v` **and** the depth that makes the pose
right — for this asset, positive `y` puts the thumb behind `Beam_UpLeft` (thumb joint at
`y≈1.2` against the beam near `y≈0`). Depth fixes occlusion and parallax; it does **not**
fix anatomy. [FIELD-TESTED]

**With any other camera, invert it properly. [GENERAL]** Do not paste the closed form.
Either invert the camera projection matrix, or work in camera space and convert. For a
camera looking down its local `-Z` with focus distance `d = -z_c` (in front of the lens)
and half-angles `fovx/2`, `fovy/2`:

```
d  = -zc                                  # distance in front of the camera
u  = 0.5 + xc / (2*d*tan(fovx/2))         # frame u, left origin
Vb = 0.5 + yc / (2*d*tan(fovy/2))         # Blender UV, bottom origin
v  = 1 - Vb                               # frame v, top-left origin
```

Compute the half-angles from the **actual** intrinsics — lens, sensor, sensor fit and the
lens shift — not from a remembered FOV. Aspect ratio matters: a non-square render changes
`fovx` for a given sensor if the fit is AUTO. [GENERAL]

**Two shader traps around this:**

- **The Camera Texture Coordinate socket is not a normalized projective UV.** Linking it
  straight into an `ImageTexture` does *not* project the image from the camera. A UV flip
  was a real prior error here (the projector came out upside-down). To project, build the
  transform explicitly (camera inverse matrix, then divide by depth) or use the known
  `u,v` math.
- **Emission strength 1 is not "pixel-exact".** Under AgX, scene lights, material response
  and the compositor, an emission value that "should" reproduce a colour does not land on
  it. Keep coloured emissive faces below about 1.0 and carry the glow in a separate rim or
  halo layer; validate with a look, not with the number. [FIELD-TESTED on the island sign]

## 6. Segmentation: face sets, joints and tips

A clean source with sculpt face sets is a gift: it lets you transform each digit
independently instead of dragging the whole hand. But the IDs are **asset-specific**.

**Case study face sets [FIELD-TESTED]:**

| part | face-set ids |
|---|---|
| palm | 273 |
| index | 278, 283, 282 |
| middle | 277, 279, 272 |
| ring | 280, 274, 275 |
| little | 281, 286, 276 |
| thumb | 288, 285, 284 |
| wrist cuff | 262, 287 |

**Never transplant these IDs to another mesh.** Inspect the target's own face sets —
bounding boxes, adjacency, and a live look — and confirm which island is which digit
before transforming anything. Transplanting blindly moves the wrong vertices.

**Joint between two adjacent segments** = the mean position of the **shared vertex
indices** of the two face-set islands — for a finger, that is the seam ring. The case
study's joints for each finger are the MCP (palm↔proximal), PIP (proximal↔middle) and DIP
(middle↔distal) seams:

```python
def face_set_members(mesh, ids):
    """Vertex indices belonging to any face whose .sculpt_face_set is in ids."""
    attr = mesh.attributes[".sculpt_face_set"].data
    ids = set(ids)
    out = set()
    for poly in mesh.polygons:
        if attr[poly.index].value in ids:
            out.update(poly.vertices)
    return out

def segment_joint(mesh, ids_a, ids_b):
    """Mean world/source position of the vertices shared by two adjacent islands."""
    shared = face_set_members(mesh, ids_a) & face_set_members(mesh, ids_b)
    if not shared:
        return None
    total = Vector()
    for vi in shared:
        total += mesh.vertices[vi].co
    return total / len(shared)
```

**Fingertip** = the mean of the distal-segment vertices within `0.004` source units of the
point furthest along the `PIP → DIP` axis:

```python
def segment_tip(mesh, distal_ids, pip_pos, dip_pos):
    axis = (dip_pos - pip_pos).normalized()
    members = face_set_members(mesh, distal_ids)
    best_dot = -1e30
    for vi in members:
        best_dot = max(best_dot, (mesh.vertices[vi].co - pip_pos).dot(axis))
    picked = [vi for vi in members
              if (mesh.vertices[vi].co - pip_pos).dot(axis) > best_dot - 0.004]
    total = Vector()
    for vi in picked:
        total += mesh.vertices[vi].co
    return total / len(picked)
```

The `0.004` is a fixed source-unit tolerance, chosen for this mesh; sanity-check it
against the mesh scale. [FIELD-TESTED for the case study; the tolerance is a judgement
call, so re-derive it per asset.]

## 7. Deformation: weights, diffusion, the palm fit, finger rotation

The method is a **static posed deformation**, not a finished rig. It turns one clean
source into one posed target and stores the targets so the pose can be rebuilt. Source is
retained; the posed mesh carries the target JSON
(`Astra.Hand.L['pose_targets_uv_depth']`) and a `construction` note.

**1. Per-vertex segment weights.** For each vertex, count its incident faces per semantic
segment, then normalise to sum to 1. A vertex on a seam gets a blend; a vertex deep inside
one segment gets weight 1 for it. [FIELD-TESTED]

**2. Diffusion smoothing.** Two passes of `0.70 · self + 0.30 · mean(neighbours)` to
soften the hard seams so the skin does not crease at a face-set boundary. More passes
soften further; two was chosen for this mesh. [FIELD-TESTED]

```python
# weights[v] is a per-segment dict; neighbours from mesh edges
for _ in range(2):
    nxt = {}
    for v in mesh.vertices:
        avg = per_segment_mean(weights, v)
        nxt[v.index] = {s: 0.70*weights[v.index].get(s,0.0)
                          + 0.30*avg.get(s,0.0) for s in segments}
    weights = nxt
```

**3. Palm fit (affine least squares). [FIELD-TESTED]** The broad palm is moved as one
affine block fitted from the source palm vertices to the explicit digit-root targets,
rather than by guessing a cluster to rotate. Using source features `f = (x_src, z_src, 1)`
and target positions `q_k` for each output axis `k`:

```
G      = Σ f fᵀ                     (3×3)
b_k    = Σ f · q_k                  (3×1)
coeff_k = G⁻¹ b_k
```

Apply `coeff` to every palm vertex; add depth as `world_y = -40 * source_y` (the case
study's depth push toward the camera). **Guard the fit:** the anchors must not be
collinear and the matrix must be well-conditioned, or `G⁻¹` explodes. Check the condition
number (or the determinant) and, if it is ill-conditioned, spread the anchors. Preserve
handedness — a fit that flips the mesh is a failure, not a style. [FIELD-TESTED; the
condition-number guard is [GENERAL]]

**4. Finger rotation. [FIELD-TESTED]** For each finger bone with source rest head `h`,
tail `t`, axis `a = normalise(t - h)` and target head `H`, tail `T`:

```python
# R0: proper basis (det +1) mapping the source palmar +Y to world -Y
R0 = Matrix(((0.5, 0.0, 0.8660254037844386),
             (0.0, -1.0, 0.0),
             (0.8660254037844386, 0.0, -0.5)))

b = (T - H).normalized()
R = rotation_from_to(R0 @ a, b) @ R0        # minimal rotation taking R0·a onto b

for each vertex p with weight w on this segment:
    pr     = p - h
    axial  = a * pr.dot(a)                   # along the bone axis
    radial = pr - axial                      # perpendicular
    longitudinal = (T - H).length / (t - h).length
    q = H + R @ (radial_scale * radial + a * pr.dot(a) * longitudinal)
    accumulate w * q
```

- `radial_scale` is a **stylization choice**, not a universal constant: the case study used
  ≈40 for most fingers, 37 for the little and 38 for the thumb, i.e. source-metre radii
  expanded into the scene's stylized scale. Pick it by look, and note it.
- `rotation_from_to` must be the **minimal** rotation (a `quaternion` between two unit
  vectors), so the finger follows one axis and does not spin. Do not confuse a mirrored
  chirality with a rotation — if the result comes out inside-out, the bug is handedness,
  not an angle.
- Blend the per-segment `q` by the vertex weights so seams move continuously.

**5. Record the targets.** Store the `(u, v, depth)` chains in a custom property so the
pose is reproducible and reviewable. Case study chains (root / PIP / DIP / end):

| finger | chain |
|---|---|
| index | `[[.268,.465,.45],[.278,.370,-.9],[.313,.399,-1.8],[.331,.428,-1.35]]` |
| middle | `[[.211,.498,.50],[.176,.418,-1.0],[.208,.452,-2.0],[.224,.480,-1.4]]` |
| ring | `[[.193,.553,.60],[.140,.530,-1.05],[.176,.562,-2.05],[.199,.590,-1.5]]` |
| little | `[[.204,.601,.80],[.175,.605,-.90],[.204,.639,-1.65],[.227,.661,-1.1]]` |
| thumb | `[[.309,.537,.65],[.365,.493,1.3],[.427,.454,1.45],[.477,.403,1.2]]` |

This is a blockout, not an anatomically exact scan.

## 8. Output mesh hygiene

Build the output as its own mesh and leave the source alone.

- **Omit the cuff working faces.** For this asset, sculpt face sets `262` and `287` (the
  wrist stub) were deleted from the *working* mesh only, and the resulting boundary was
  capped. Source retained intact. [FIELD-TESTED]
- **Remove now-unused vertices** after dropping faces, so no loose geometry ships.
- **Cap the boundary loop** and **recalculate normals outward** on the closed mesh.
- **Keep the source untouched** as the fallback.
- **Modifiers belong to the reviewed object.** The posed hand carried a subdivision
  modifier at levels 2 / render 2. Review what the render evaluates (base vs evaluated
  counts differ).
- **Before palm-only polish, back up.** Store the mesh datablock with a fake user and
  record its exact name (here `Astra.Hand.ClayPass1` /
  `Astra.Hand.L['astra_pass1_mesh']`).
- **Smooth only unambiguously interior palm vertices.** Pass 2 smoothed 194 interior palm
  vertices, 4 iterations, factor 0.25, and did **not** re-fit the endpoints. Averaging
  near a boundary drags the boundary; interior-only is what preserves the endorsed pose.
  [FIELD-TESTED]
- **You cannot infer the palm side from average normals.** Both sides of a shell can have
  outward normals; a mean tip-Y is likewise ambiguous. Determine front/back the way this
  asset did: from the source's front/back faces and from the photograph. [FIELD-TESTED]

## 9. Nails and claws

Each nail is an **individually editable tapered, curved 3D shell** — not a decal, not a
flat card, not a torus.

**Geometry [FIELD-TESTED].**

- Centreline `C(t)` is a **cubic Bézier**; use its derivative for the tangent `t̂` at each
  station.
- **24 rings × 12 cross-section samples**, closed, smooth.
- Ellipse cross-section: half-width ≈ `0.29 · (1-t)^0.65 · (gentle bulge)` in world units
  (little finger `0.25`), half-depth ≈ `0.095 · (1-t)^0.75`. The bulge term is small.
- Finish with a **final apex**, **cap the base**, and **recalculate normals outward**.
- **Width basis:** `(t̂.z, 0, -t̂.x)` works for these curves because they are not
  view-aligned. A **generic** sweep must handle the degenerate case where the tangent is
  near-parallel to the basis axis by falling back or switching to parallel transport —
  otherwise the ring collapses. [GENERAL for the fallback]
- **Radius and curvature must not self-overlap.** At a tight bend the rings can cross
  inside the shape while the mesh stays manifold and watertight, so ordinary mesh checks
  miss it. Keep the ring spacing above the profile radius. [GENERAL, echoed by the vendored
  sweep guidance in `techniques.md`]

**Seating [FIELD-TESTED].** Raycast the *evaluated* hand from the camera through the nail
base; if the hit is within `0.85` units, seat the nail at `surface_point + normal · 0.025`
and apply a quadratic falloff correction over the **first 42%** of the nail. The nail root
must **overlap the seat on the nailbed** — it must not float above the finger and must not
be a pin stuck halfway down the digit. Check **front and profile**: the nearest surface
can be the wrong digit, so a threshold (`0.85`) plus a visual check is not optional.

**Orientation [FIELD-TESTED].** The 5th (thumb) nail points up-right; the other four hook
down-right consistent with the curled fingers. Nail curve tips in full-frame uv were:
index `(.365,.453)`, middle `(.264,.512)`, ring `(.242,.625)`, little `(.270,.698)`,
thumb `(.487,.375)`; bases were seated by camera-ray hits with offsets `0.065–0.222`
units.

**Name and material.** `Astra.Claw.Index/.Middle/.Ring/.Little/.Thumb`, material
`Astra.Keratin`.

## 10. The isolated review scene

Reviewing in the main scene risks moving the owner's camera and lighting. Use a dedicated
review scene that **shares** the objects but owns its inspection setup.

- Create scene `Astra.Hand.Review`, **linked to the same hand and claw objects** (shared
  data, so it shows the current pose), with its **own** neutral world, key/fill/rim lights
  and a **copy** of the camera. Do not mutate the user's main camera or lighting to look
  at something. [FIELD-TESTED]
- **Render border preserves the original rays.** A cropped render of
  `u ∈ [.09,.52]`, `v ∈ [.33,.72]` maps to border (bottom-left origin)
  `min_y = 1-.72 = .28`, `max_y = 1-.33 = .67`; at 1080² this produced the `464×421`
  isolated crop. Border crops show detail for a fraction of the cost.

```python
scene.render.use_border = True
scene.render.use_crop_to_border = True
scene.render.border_min_x, scene.render.border_max_x = 0.09, 0.52
scene.render.border_min_y, scene.render.border_max_y = 0.28, 0.67
```

- **Always restore `window.scene` in a `finally`.** Leave the owner on `Scene`, camera
  `Camera`, as you found them. The same discipline applies to `hide_get` state per view
  layer and to the viewport selection: a tool may restore its own changes, but **your**
  script must restore **its** changes. [FIELD-TESTED]
- **Serialize Blender work.** Blender is a single mutable session: do not parallel-render
  or run two captures that change the same state at once. One mutation, one look, one
  render, in order.
- `look` targets the frame; it does not have to isolate other scene meshes.

## 11. The visual validation loop

- **Render at an explicit resolution** (here 1080²) so crops and comparisons are stable.
- **Compare in the tool, then look at the picture.** `compare_reference(reference_path,
  render_path, region='u0 v0 u1 v1', file=unique_path, size=...)`, then **inspect the
  image**. Never treat the toolbar caption as proof the file reached the host.
- **Give simultaneous compare calls distinct output paths.** Two calls writing the same
  file race and the reader may see a stale or truncated image. And a **failed render must
  abort the compare** — comparing a stale `Render Result` is worse than comparing nothing.
- **Verify captions against actual host output when persistence is suspect.** In this
  session `compare_reference` returned a caption naming a path that the host and the next
  agents could not see. The **root cause was not diagnosed** — do not announce a bug
  theory as proven; prefer the render tool plus a live `look`, and write to distinct
  paths.
- **Peer-review messages must be concrete and short.** Send 2–3 lines: scope, the change,
  and the paths. A queued/async message that was never delivered is not a review, and a
  review in flight is not a completed review — do not claim review is done.
- **Judge by eye, not by a score.** A score-based ranking (SSIM/colour histogram) scored
  a flat grey wash above a contrasty correct render; see the dated note in
  `rust/refcompare.rs`. Metrics can support a decision; they cannot make it.

## 12. Shading, materials and compositing

- **Look shader nodes up by type, never by name.** Node names are localised. Find a
  Principled BSDF with `next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')`.
  [FIELD-TESTED]
- **`diffuse_color` is solid-view only.** Material colour that matters to a render goes on
  the shader node inputs, not on `material.diffuse_color`.
- **White clay is not finished skin.** Keep "is the geometry right" and "is the surface
  right" as separate questions.
- **Do not use a cover-projection to disguise an unposed hand.** Once the silhouette and
  depth are correct, a fixed-view projection *can* be a deliberate technique, but its sides
  smear and it cannot invent occluded anatomy. It is not a substitute for the pose.
- **Bas-relief (2.5D) is a valid choice only if the deliverable is agreed to be a static
  view.** It is not a full 3D hand. Decide with the owner before committing.
- **Painterly skin can come after geometry:** low-frequency mottling plus restrained
  high-frequency bump. **Image brightness is not true depth** — do not feed a reference's
  brightness into displacement; strong displacement on rim normals distorts the silhouette
  (the island's whitewater went from spiky needles to broken froth when it was weakened).
- **Separate the problems.** Material, lighting, colour management and compositor are
  four different causes; do not change all four to chase one mismatch.
- **Inspect the actual graph users — then check what is switched on.** `CanvasGrain` had
  **1 user**: a compositor image linked through `CanvasOverlay` to the output, so it was
  *not* unused just because no material referenced it. But the count was not proof of
  influence: `CanvasOverlay` was connected **and `MUTE`**, so nothing it carried reached
  the render until it was enabled. Read the real user counts before deleting or
  "cleaning up", and check `mute` along the path before claiming a datablock affects the
  image.

## 13. Runtime, guards and scripting discipline

- **Read enums from the RNA** rather than hardcoding identifiers; assigning an unknown
  render engine raises `TypeError` whose message lists the valid values — catch it and
  read the list. [FIELD-TESTED]
- **The `execute_code` guard allows a narrow set of imports** — `bpy`, `bmesh`, `mathutils`,
  `math`, `json` — and in this session rejected `lambda`, `yield`, dynamic `getattr` and
  dunder access. Write plain loops and named functions; keep snippets guard-compatible.
  [FIELD-TESTED]
- **Do not debug via `os`/`subprocess`/direct file IO.** Use the render and export tools
  and the raj editor verbs. Any helper snippet in this guide that appears to touch disk is
  illustrative and must be replaced with a tool call.
- **Change a guard only at an explicitly requested, reviewed policy change** — never as a
  normal modelling escape hatch.
- **Path roots:** `BLENDER_READ_ROOTS` is a **list**; the server process must inherit it,
  and a GUI-launched Blender's environment can differ from a shell's. Verify the roots you
  need are actually in effect, rather than assuming.
- **Datablock or scene modification is not the same as saving the `.blend`.** Changes here
  are live and unsaved until the **owner** saves. Never assert the file was saved.

## 14. Mesh health checks

Run these and report them, but understand their reach.

- **Non-manifold edges and zero-area faces.** All six of the case study's new hand/claw
  meshes checked at **0 non-manifold edges and 0 zero-area faces**. [FIELD-TESTED]
- **Necessary, not sufficient.** A zero count does **not** mean self-intersection-free, and
  it does **not** prove the anatomy correct. Say so; do not overclaim.
- **Also test:** the underside and the wrist cap; negative scales; whether the mesh is
  shared with another object; gross vertex spacing; closed forms; fingertip width; and
  valid sampling. Separate parts that should be connected must be joined; parts that
  should be separate must not merge.
- **Validate the maths too:** paths finite and non-zero, matrices invertible, radii
  positive and non-zero. A NaN that survives into a mesh is very hard to see.

## 15. Documentation and handoff

A reconstruction outlives its session. Record it in two places.

- **Live metadata in the `.blend`:** `Scene['agent_handoff']` stores the owner, the
  reviewer, the saved document's path, the current stage, the tracked objects, the backup,
  the hard constraints, the output paths and the unsaved/stale warnings. Read it alongside
  the saved handoff.
- **A saved, append-only handoff document** (`docs/NEFAS-HANDS-HANDOFF.md`). Keep it near
  150 lines: log the change, not the transcript. Correct an earlier claim in place instead
  of appending a contradiction.
- **Each entry states** intent, touched objects, the change, what validated it, pending
  items, and the output paths. Example: pass 2 — intent "add nails and soften the palm
  without moving the approved fingers"; touched the posed mesh (palm verts only), the five
  claw curves, the materials, and a new review scene; validated by `look` plus
  front/right/top/three-quarter views; outputs `hand3d_live.png`, `astra_left_clay.png`.
  [FIELD-TESTED]
- **Mark renders current vs stale.** `compare.png`, `cmp_zoom.png` and earlier
  `hand3d_v*.png` are **stale** and are not validation for the current pose. Only
  `hand3d_live.png` and `astra_left_clay.png` were current at handoff.
- **Record the rollback chain and the source.** Backup datablock + fake user + exact name;
  clean source retained; failed attempts hidden, listed, restorable.
- **Restore the active scene and camera before you go**, and say so.
- **State what is not done.** The skin material and the second hand were pending; the
  handoff must not imply otherwise.

## 16. Failure table

Each row is a real failure from this rebuild (or the sibling island scene), its cause, and
the repair policy. Diagnosis, not blame.

| # | Symptom | Cause | Repair policy |
|---|---|---|---|
| 1 | Worked the wrong hand / wrong reference photo | Frame-side ("left") conflated with body-side ("anatomical left") | Always name both; pick the reference by the subject's own side |
| 2 | A digit called a wrist | Guessing from position; a label was superseded | State anatomical landmarks; the owner's requirement wins |
| 3 | Bbox extrema read as joints | Treating scalar metrics as anatomy | Use §5 landmark mapping + a live look; never bbox-fit |
| 4 | Repeated ± rotations with no interpretable axes | Unclear rotation axis/space, drifted by trial | Define a bone basis `R0`, take a minimal rotation, log the axis |
| 5 | A deformation doubled | Two objects shared one mesh datablock | `obj.data = obj.data.copy()` before deforming |
| 6 | Work destroyed | Ran a global undo in someone else's live session | No global undo/purge; expressible inverses; fake-user backups |
| 7 | Fingers fused into a mitten | Collective vertex deformation | Per-segment weights + independent transforms |
| 8 | A "puffed card" hand | One mask / bas-relief passed as 3D | Real silhouette + depth; separate fingers; agree 2.5D with the owner |
| 9 | Projector upside-down | UV V (bottom origin) vs frame v (top origin) flip | Convert `v = 1 - Vb`; check orientation with a look |
| 10 | Image not projected from the camera | Linked Camera Texture Coordinate straight to the texture | Build the projection (inverse matrix / explicit uv) |
| 11 | Crumpled surface | Image brightness used as displacement height | Separate shading from height; restrained bump |
| 12 | "Emission 1 is pixel-exact" | Ignoring AgX, lights, material and compositor | Keep emissive < ~1, glow in a rim layer, validate by look |
| 13 | Rotations wildly wrong | Degrees vs radians | Blender euler is radians: `pi/2`, not `90` |
| 14 | Stale or half-written compare image | Two calls writing one file / a stale Render Result | Unique output paths; abort the compare on a failed render |
| 15 | A file "proven" to exist | Trusting a tool caption over host output | Verify host output; prefer `render`/`export` + `look` |

## 17. Reproducibility and review exercises

These are **manual** exercises for a human or agent, not automated benchmarks. None of
them adds a new evaluated claim or an A/B skill test; they reproduce an observed workflow.

1. **Pose-from-photo, in clay.** Take the clean source, do §6 segmentation and §7 pose
   from one reference photo, then inspect the result in a three-quarter view. Does the
   silhouette read as the photographed pose with the digits separate, or did they fuse?
   Report the landmarks you placed and the views you checked.
2. **Cut-mask projection with the correct sign.** Project a face-mask image onto a posed
   head/hand with the §5 mapping, verify the orientation (no upside-down flip, #9), then
   state the 2.5D limits: what smears on the sides, and what occluded anatomy the
   projection cannot invent. Confirm the material is a fixed-view technique, not a pose
   substitute.
3. **Resume a scene from the handoff, read-only.** Open the `.blend`, read
   `Scene['agent_handoff']` and `docs/NEFAS-HANDS-HANDOFF.md`, and reconstruct: the
   current stage, the tracked objects, the rollback chain, which renders are current and
   which are stale, and which constraints are hard. **Do not modify** the source or the
   baseline. Success is an accurate written summary, not a change.

## 18. Reusable checklists

**Pre-flight (before any change)**

- [ ] `scene_info` + `reveal`: file, scene, view layer, camera, frame, resolution.
- [ ] `object_info` on every target; note shared mesh/material/user data and exact names
      (trailing spaces included).
- [ ] A live `look`, not a summary or an ASCII view.
- [ ] The reference side is named (of frame vs anatomical); owner requirements listed.
- [ ] A backup plan exists: exact datablock name + fake user, and the clean source is
      retained.

**During a pass**

- [ ] Operate on a copy; never the shared datablock or the source.
- [ ] Pose from named landmarks; depth chosen for occlusion, not guessed.
- [ ] One change, one look; serial Blender work; restore `window.scene`, hides and
      selection in a `finally`.
- [ ] Do not re-fit a part the owner already endorsed.

**Validation**

- [ ] Front, side, top, three-quarter views inspected as images.
- [ ] Crops via render border (rays preserved) for detail; unique compare output paths; a
      failed render aborts the compare.
- [ ] Mesh checks: 0 non-manifold, 0 zero-area — and explicitly *not* overclaimed.
- [ ] Maths finite and non-zero; matrices invertible.
- [ ] Independent peer review sent as 2–3 concrete lines, and actually returned.

**Handoff**

- [ ] `Scene['agent_handoff']` and the saved doc both updated; renders marked current vs
      stale.
- [ ] Rollback chain, source, constraints, pending items and output paths recorded.
- [ ] Active scene and camera restored; nothing asserted as saved.

## 19. Open items

- **Both hands now exist** — the frame-right hand was built from the clean source — and
  the annotated owner notes and the lookdev are **in progress**: owner-approved, not
  documented here as final.
- The **claw pose** (nail seating, thumb/beam relation) awaits owner/peer review.
- **Skin material** matching `Nefas front cover art final.png` is **approximate and not
  accepted**: an early skin-crease / reference-colour pass is on both hands and the
  annotated notes are being worked. Nothing is signed off.
- The bottom **TITLE** area is excluded by the owner, and **grain is deprioritized**: the
  main compositor effect is retained, while a temporary no-grain diagnostic muted it and
  then restored the state.
- The **`compare_reference` caption-vs-host-file** discrepancy was observed but its **root
  cause is undiagnosed**; do not present a theory as fact.
- The `radial_scale` values, the `0.004` tip tolerance and the `0.85` raycast threshold are
  **tuned to this asset**; re-derive them for a different mesh.
