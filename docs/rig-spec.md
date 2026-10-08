# Rig spec: the rc-Trio figures, the smoke and the logo

The intended rig for the scene the print *Gigan T-Shirt 2018.jpg* describes: a
black ground, white line hatching, three hooded robed figures whose faces hang
as tendril masses, each holding a censer under one smoke cloud that carries the
GIGAN logotype. The reader is a rigger building it, and — once it is exported —
TouchDesigner driving it live (`docs/audio-map.md`).

The names below are the objects already in the scene; nothing here invents
geometry. Three things do **not** exist yet and this rig has to create them: the
control empties `smoke_ctrl_C` / `smoke_ctrl_L` / `smoke_ctrl_R`, the
`smoke_C` / `smoke_L` / `smoke_R` vertex groups on `rc-Smoke`, and the cloud
armature itself. The scene does contain three other Empties — `Empty`,
`Empty.001` and `Empty.002` — but those are the user's reference-image
holders, off-limits, and must never be treated as the smoke controls.

## What is in the scene

| Object | What it is |
|---|---|
| `rc-Trio` (collection) | the three figures |
| `rc-Body-<X>` | a human body, arms removed |
| `rc-Robe-<X>` | the robe, fitted to the body, sloped shoulders |
| `rc-Hood-<X>` | the hood |
| `rc-Sleeves-<X>` | the draped bell sleeve: two tubes per figure, one per side, shoulder to censer and past it (384 verts each, `rc-Cloth`, fold ridges, flared opening; bottoms at z ≈ 6.1–6.2) |
| `rc-Tendrils-<X>` | the hanging tendril mass, carrying the rig's vertex groups |
| `rc-Censer-<X>` | the censer each figure holds |
| `rc-Smoke` | one cloud at z ≈ 33, fed by three thin streams from the censers |
| `rc-GIGAN-Logo` | a solid 3D logo traced from `logo.png`, at (40, −1.2, 33) |

`<X>` is the figure: **C** at x = 40, height ≈ 20.7 m; **L** at x = 26.5 and
**R** at x = 53.5, height ≈ 18.3 m. Every figure object is `rc-<Part>-<X>`.

Materials: `rc-Cloth` (white line hatching on a black ground, emission),
`rc-Tendril`, `rc-Smoke`, `rc-Ink`.

## The rig at a glance

One armature per figure — `rig_C`, `rig_L`, `rig_R` — and one for the cloud,
`rig_Smoke`: four armatures, 133 bones.

- **43 bones per figure** — a body chain, a hood, two arm chains, a censer
  bone, and **26 tendril bones**, one per vertex group already on
  `rc-Tendrils-<X>`.
- **4 bones for the cloud** — a root and one deform bone per stream.
- Each figure's six meshes are skinned to `rig_<X>` with an Armature modifier.
- The three smoke handles `smoke_ctrl_C` / `smoke_ctrl_L` / `smoke_ctrl_R` are
  empties the rig adds; `rc-GIGAN-Logo` is rigid and parented to the centre one.

## Figure armature: `rig_<X>`

Bones are named for the thing they drive. `<X>` is `C`, `L` or `R`; a `L`/`R`
in a bone name is the *side* (left/right arm) and is unrelated to the flank
figures.

### Body, robe, head

| Bone | Parent | Deforms |
|---|---|---|
| `root_<X>` | — | nothing; the armature root, at the figure's base on the ground |
| `pelvis_<X>` | `root_<X>` | `rc-Body-<X>` hips and lower torso |
| `spine_<X>` | `pelvis_<X>` | `rc-Body-<X>` mid torso |
| `chest_<X>` | `spine_<X>` | `rc-Body-<X>` upper torso; parent of both arms and the head |
| `robe_<X>` | `pelvis_<X>` | `rc-Robe-<X>` main body and shoulder line |
| `robe_sway_<X>` | `robe_<X>` | `rc-Robe-<X>` hem and lower drape — the sway target |
| `head_<X>` | `chest_<X>` | `rc-Body-<X>` head; parent of every face tendril |
| `hood_<X>` | `head_<X>` | `rc-Hood-<X>` |

If the hem needs two bones rather than one, split `robe_sway_<X>` into
`robe_sway_<X>` and a `robe_hem_<X>` child of it; keep the sway target on
`robe_sway_<X>`.

### Arms (side `S` ∈ {`L`, `R`})

| Bone | Parent | Deforms |
|---|---|---|
| `shoulder_<X>_S` | `chest_<X>` | `rc-Sleeves-<X>` tube at the shoulder |
| `upperarm_<X>_S` | `shoulder_<X>_S` | `rc-Sleeves-<X>` tube, upper length |
| `forearm_<X>_S` | `upperarm_<X>_S` | `rc-Sleeves-<X>` tube, lower length |
| `hand_<X>_S` | `forearm_<X>_S` | `rc-Sleeves-<X>` flared opening and bottom; the anchor for that side's hand tendrils and the censer (there is no hand mesh — `rc-Body-<X>` has no arms) |

So `hand_<X>_L` and `hand_<X>_R` are the parents called out below.

### Censer

| Bone | Parent | Deforms |
|---|---|---|
| `censer_<X>` | `hand_<X>_L` | `rc-Censer-<X>` |

The censer hangs at the bottom of the holding sleeve; `hand_<X>_L` is the
default. Check which side holds it against the print and reparent to
`hand_<X>_R` if it is the right one. There is no separate hand object: the arm
bones deform the `rc-Sleeves-<X>` bell, and the flared opening is where the
`hand` bone sits.

### Tendrils — one bone per vertex group

`rc-Tendrils-<X>` already carries the vertex groups, and those groups **are** the
rig units: each bone takes the group's exact name. A bone deforms exactly its
own group, weight 1.0, and nothing else. **8 per hand, 10 per face** — do not
add a ninth or an eleventh.

| Bones (exact names) | Count | Parent |
|---|---|---|
| `tendril_<X>_handL_01` … `tendril_<X>_handL_08` | 8 | `hand_<X>_L` |
| `tendril_<X>_handR_01` … `tendril_<X>_handR_08` | 8 | `hand_<X>_R` |
| `tendril_<X>_face_01` … `tendril_<X>_face_10` | 10 | `head_<X>` |

Every tendril bone points down the tendril it drives — head at the anchor (the
lower end of a sleeve, or the head), tail at the hanging tip — which gives a
natural flick axis around its own local Z. That is 26 tendril bones per figure.

## Cloud armature: `rig_Smoke`

`rc-Smoke` is one object, fed by three streams. It is skinned to three deform
bones, one per stream; the vertex groups these bones need — `smoke_C`,
`smoke_L`, `smoke_R`, one per stream and the cloud sector above it — are added
for this rig.

| Bone | Parent | Deforms |
|---|---|---|
| `smoke_root` | — | nothing; the rig root at the cloud, z ≈ 33 |
| `smoke_C` | `smoke_root` | vertex group `smoke_C` on `rc-Smoke` |
| `smoke_L` | `smoke_root` | vertex group `smoke_L` on `rc-Smoke` |
| `smoke_R` | `smoke_root` | vertex group `smoke_R` on `rc-Smoke` |

Each bone runs from the cloud down its stream toward that censer, so
translating it lifts and drops that stream and the cloud sector over it.

### The three Empties

The rig adds three handles, `smoke_ctrl_C`, `smoke_ctrl_L` and `smoke_ctrl_R`;
none of them exists in the scene yet. Each empty is the control for one stream
and is wired to the matching deform bone with a **Copy Transforms** constraint
(`smoke_C` copies `smoke_ctrl_C`, and so on), so grabbing an empty moves the
stream in Blender. They are not the scene's `Empty`, `Empty.001` or
`Empty.002`, which belong to the user's reference images.

For the export the constraint is **baked** (see below): the FBX carries the bone
motion, and TouchDesigner drives the bones `smoke_C` / `smoke_L` / `smoke_R`,
because they own the skin. The three empties still export, as FBX Nulls of the
same names, so both sides share the naming and the logo has a parent.

### The logo

`rc-GIGAN-Logo` is solid and must stay rigid. Parent it to the **centre** cloud
handle, `smoke_ctrl_C` (created by this rig): both sit at x = 40, so the
logotype rides the centre of the cloud as the print has it. It needs no
armature and no weights — a rigid mesh child of the empty. If the logo must move
independently of the cloud, add a dedicated `logo_ctrl` empty under
`smoke_ctrl_C` and parent the logo to that instead; either way the FBX must
carry the empty it hangs from.

## The FBX export

The scene is authored Z-up, 1 unit = 1 m, and is consumed by TouchDesigner in
Y-up. Recommended settings:

| Setting | Value | Why |
|---|---|---|
| Format | FBX, binary 7.4 | what TouchDesigner's importer reads |
| Object types | Armature, Empty, Mesh | the bones, the handles, the geometry |
| Armature | **on** — one per figure, one for the cloud | skinning is the only per-vertex deformation FBX carries |
| Skinning | keep the Armature modifier's weights, ≤ 4 influences | TouchDesigner's bone binding |
| Empties | export as Nulls | the three smoke handles |
| Animation | **bake** the action | resolves the Copy Transforms constraints into the bones |
| Frame rate | **24 fps** | matches the scene and `docs/audio-map.md` |
| Axis | `−Z` forward, `Y` up (Blender → FBX) | TouchDesigner is Y-up |
| Scale | 1.0, apply unit scale | metres stay metres |
| Materials | leave on; `rc-Cloth`'s emission must survive | the white line hatching is emitted, not lit |
| Cameras / lights | off | not part of the rig |

What must survive, exactly and uniquely named across the whole export: every
bone above, the three Nulls `smoke_ctrl_C` / `smoke_ctrl_L` / `smoke_ctrl_R`,
the meshes `rc-*`, and the armatures `rig_C` / `rig_L` / `rig_R` / `rig_Smoke`.
Bone names are already unique per figure (the `_<X>_` segment) and the smoke
bones are unique as written, so no namespacing prefix is needed.

A baked export resolves the empty constraints into `smoke_C` / `smoke_L` /
`smoke_R`; TouchDesigner overrides those bones every frame from the audio CHOPs
(`docs/audio-map.md`), and the baked keys simply give a sane rest pose when
nothing is driving.

## Open points for the rigger

- Which sleeve the censer hangs from — `censer_<X>`'s parent, `hand_<X>_L` or
  `hand_<X>_R`.
- One `robe_sway_<X>` bone or two hem bones.
- Smooth the tendril weights at the anchor so it does not tear when a bone
  flicks.
- `rc-Tendrils-<X>` should hold 8 + 8 + 10 = 26 groups per figure; count them in
  the file before parenting, and treat a missing or extra group as a fault
  rather than adding a bone.
