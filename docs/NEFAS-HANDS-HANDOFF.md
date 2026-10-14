# NEFAS hands — handoff and change log

Durable, append-only record of the NEFAS album-cover rebuild (both hands plus the
scene's annotated issues), so the next agent or a fresh session can continue
without re-deriving the scene. Read this before touching the .blend. Per-note
detail lives in `docs/NEFAS-SCENE-ANNOTATIONS.md`; this file stays short — log the
change, not the session transcript. New entries go under *Change log* by date;
correct an earlier claim in place rather than appending a contradiction.

## Owner feedback and direction (current)

- Pass-1 clay of the frame-LEFT hand was praised: "looking great so far in terms
  of the models" — palm/thumb placement endorsed; extend, do not restart.
- The owner then asked explicitly: "make the other hand and fix the rest". The
  frame-RIGHT hand is built; this **supersedes** the old "DO NOT start the right
  hand until the owner approves" line (keep the history, not the prohibition).
- Bottom TITLE area excluded: "ignore those".
- The whole-lookdev direction was criticized as a quality drop; the owner chose
  **DISCUSS**, not rollback. Grain is **not a priority**.
- The owner annotated 10 scene notes on `renders/hand3d_live.png`, discussed them,
  and expressly approved proceeding.
- An endorsement is not final approval and renders are evidence, not approval.
  Nothing here is owner-accepted unless the owner says so.

## Hard constraints (owner + reference photos, these win)

- PALM faces the front / camera.
- THUMB points UP / up-right, behind `Beam_UpLeft`.
- NO visible wrist.
- FOUR separately curled fingers along the left / top edge, plus the thumb.
- The up-right spear at u~0.47, v~0.40 is the THUMB, not the wrist.
- Superseded — do NOT trust: earlier peer labels "4 digits", "top curl is the
  thumb", "back faces camera".
- Both hands are now in scope: frame-LEFT was worked first, frame-RIGHT built
  after the owner's explicit request.

## Scene and frame facts (verified live)

- Blend: /Users/rajandavis/Desktop/NEFAS/ooo_cover_scene2.blend, scene `Scene`.
- Blender 4.2.18 LTS, EEVEE_NEXT, 1080x1080.
- Camera at (0,-30,0), looks +Y, rotation (pi/2,0,0), 50mm lens, 36mm sensor.
- Frame uv (top-left origin) -> world, W = (y+30)*0.72:
  x = (u-0.5)*W;  z = (0.5-v)*W.
  Use this to MEASURE landmarks. Do not bbox-fit a mesh and call its extrema a
  wrist or a fingertip — that mistake is behind the earlier failed attempts.
- Images already in bpy.data.images: 'Nefas front cover art final.png';
  'right hand, left side real.png' (the correct anatomical RIGHT hand for the
  frame-LEFT side); 'left hand, right side real.png' (frame-RIGHT).
- Frame side is not body side: pick the reference by the subject's own side.
- `HandMask` has `poly_left`/`poly_right`, but those polygons include glow and
  background and must NOT dictate anatomy; it is used only as a bounded blend gate.

## Objects and data (live)

Collection `Hands_Astra`:
- `Astra.Hand.Source` — clean appended mesh, hidden in viewport and render,
  retained unchanged. 871 verts, `.sculpt_face_set` anatomical segments. Source
  palmar normal +Y maps toward camera (-Y); palm side was verified by a live look.
- `Astra.Hand.L` — posed closed mesh. 782 verts / 771 base faces; subdivision
  `Pose smoothing` levels 2 / render 2. Wrist stub removed (source face sets 262
  and 287 deleted from the WORKING mesh, the opening capped; the original is
  retained). Custom props `pose_targets_uv_depth`, `construction`.
- `Astra.Hand.R` — built independently from the clean `Astra.Hand.Source`;
  `mirror sourceX` for chirality; same anatomical face-set method as L; cutoff
  sources 262/287 plus cap; 782 verts / 771 faces / subdiv 2; source preserved.
  Baseline mesh `Astra.Hand.R.ClayPass1` (fake user); the full R target JSON is
  stored on the object — not duplicated here.
- Nails: `Astra.Claw.Index`, `.Middle`, `.Ring`, `.Little`, `.Thumb` (left) and
  `Astra.Claw.R.*` (right; metadata `belongs_to` `Astra.Hand.R`) — tapered swept
  cubic curves, 24 rings x 12 sides, closed, smooth, `Astra.Keratin` /
  `Astra.Keratin.Teal`.
- Materials: `Astra.Clay` (grey, unpainted base). The skin shading on both hands is
  **approximate and not accepted** — backup `Astra.Skin.BeforeNote10`, the
  `skin_creases` attribute and the `Astra.ReferenceUV` reference-colour blend;
  detail in the annotations log.
- Collection `Astra.SceneNotes` holds the owner-note objects (arched rock, floating
  rocks, mist, fog, stars, fragments, beam). A separate broad lookdev candidate
  (`Astra.Atmosphere`, `Astra.Orb.*`, palette copies) exists but was **not
  approved**; the owner called the overall direction a quality drop — see the
  annotations log, do not promote it as best practice.

Segmentation source face sets (unchanged method): palm 273; index [278,283,282];
middle [277,279,272]; ring [280,274,275]; little [281,286,276];
thumb [288,285,284]. Vertex weights come from face membership plus 2
adjacency-smoothing iterations (70% self / 30% neighbors), then independent
per-segment transforms toward the explicit uv/depth joints. The broad palm was
fitted to the actual digit roots; no guessed coordinate cluster was rotated
arbitrarily.

## Current target chains (u, v, depth) — root / PIP / DIP / end (frame-LEFT)

- index  [[.268,.465,.45], [.278,.370,-.9],  [.313,.399,-1.8],  [.331,.428,-1.35]]
- middle [[.211,.498,.50], [.176,.418,-1.0], [.208,.452,-2.0],  [.224,.480,-1.4]]
- ring   [[.193,.553,.60], [.140,.530,-1.05],[.176,.562,-2.05], [.199,.590,-1.5]]
- little [[.204,.601,.80], [.175,.605,-.90], [.204,.639,-1.65], [.227,.661,-1.1]]
- thumb  [[.309,.537,.65], [.365,.493,1.3],  [.427,.454,1.45],  [.477,.403,1.2]]

Positive thumb Y puts the thumb behind the beam. This is a blockout, not an
anatomically exact scan. Nail curve tips in full-frame uv: index (.365,.453),
middle (.264,.512), ring (.242,.625), little (.270,.698), thumb (.487,.375);
nail bases were seated to the evaluated finger surface by camera-ray hits with
offsets 0.065-0.222 units.

## Rollback and safety

- Baseline: mesh datablock `Astra.Hand.ClayPass1`, fake user on, exact name in
  `Astra.Hand.L['astra_pass1_mesh']`. `Astra.Hand.Source` is the second fallback;
  `Astra.Hand.R.ClayPass1` is the right hand's baseline.
- Wave snapshots: per-object `.BeforeNotes3_10` meshes (exact names in
  `Scene['astra_notes3_10_backup']`), material `Astra.Skin.BeforeNote10`,
  `Astra.Beam.RightHigh.BeforeNote9`, `Astra.ArchedRock.GridCheckpoint`, and JSON
  `Scene['astra_note5_before']` / `Scene['astra_scene_backup']`. A mesh rollback
  does not undo the later materials, modifiers or pose metadata.
- Hidden prior attempts: 'Hand - Stylized ', 'Hand - Stylized .001',
  'Hand 180 test' (prior visibility in `Scene['astra_attempt_visibility']`).
  `Hands3D` stays hidden; `HandCard.L` and `HandCard.R` are retained hidden.
- The current changes are LIVE and UNSAVED in the .blend. Never assert the blend
  was saved; saving is the owner's action. Do not run global undo or purge, do not
  alter the owner's assets in place, and copy a mesh before deforming it.

## Pass history

- Pass 1 — blockout (frame-left). The clean asset was appended anew (Asset Browser
  source
  /Users/rajandavis/Documents/BlenderAssets/human-base-meshes-bundle-v1.4.1/human_base_meshes_bundle.blend,
  object 'Hand - Stylized ' with a trailing space). Segment-weighted pose to the
  chains above; wrist stub removed; baseline datablock stored. Failed attempts
  behind this: wrong anatomy/placement, collective vertex deformation,
  flipped/projected texture, bas-relief.
- Pass 2 — after the owner liked the model. Smoothed ONLY the 194 interior palm
  vertices (4 iterations, factor 0.25), keeping finger endpoints and the overall
  placement, and added the five nail meshes.
- Pass 3 — the owner's explicit "make the other hand and fix the rest": built
  `Astra.Hand.R` independently from the clean source, then worked the 10 annotated
  notes across three batches (note-numbered detail, backups and superseded attempts
  in `docs/NEFAS-SCENE-ANNOTATIONS.md`). Latest BASE mesh QA (parent-verified): the four
  meshes `Astra.Hand.L` 782 verts / 771 faces, `Astra.Hand.R` 782/771, `Astra.ArchedRock`
  4987/1494 and `Astra.Boulder` 162/320 all check at 0 non-manifold edges, 0 loose verts
  and 0 zero-area faces. That is a separate check from the earlier twelve hand/claw meshes
  and does not rule out self-intersections or prove an exact visual match; `Astra.Hand.Source`
  is unchanged at 871 verts.

## Outputs

Under /Users/rajandavis/Desktop/projects/rmcp-for-blender/renders/:
- `hand3d_live.png` — current primary preview: main-scene 1080x1080 frame 1, 64
  samples EEVEE, full cover; the last current render followed the rock-lighting
  500 W change.
- `astra_left_clay.png` — historical isolated neutral-lit hand crop (464x421).
- `astra_notes_clean_review.png` — temporary NO-GRAIN diagnostic from an earlier
  batch-3 render; **stale now** against the final rock geometry/material and the
  hand reference-colour blend. The parent may refresh it; do not claim it current.
- Dedicated review scene `Astra.Hand.Review` shares the new hand and claws with
  independent lights, world and camera; render border u[.09,.52] v[.33,.72]; its
  camera copies the main one. After rendering, return window.scene to `Scene` — do
  not leave the owner switched inadvertently. Currently restored: active scene
  `Scene`, camera `Camera`, frame 1, and the old grain setting after the diagnostic.
- STALE, not validation: `compare.png`, `cmp_zoom.png` and earlier `hand3d_v*.png`.
  `compare_reference` has returned images whose persistence differed between the
  MCP server and the Blender-host files, so never assert a file exists from a tool
  caption alone — use render output and a live `look`.

## Validating a change

Actually use `look` (live camera, plus isolated front / right / top /
three-quarter views) — not measurements alone; every annotation batch used a live
look plus a real render and `compare_reference`. Bottom-title comparisons use the
full-frame polygon '.22 .88,.80 .88,.80 .98,.22 .98'. The latest live views show
two palm-facing claw hands with real depth, separate curled fingers, raised thumbs
and no cuff. Side views are what confirm volume.

## Coordination

- A live JSON note `Scene['agent_handoff']` in the .blend records the owner
  (`raj-66726630`), the reviewer (`raj-claude`), this document's path, the current
  stage, the tracked objects, the backup, the hard constraints, the output paths
  and the unsaved/stale warnings — read it alongside this handoff.
- Identities: main `raj-66726630`; Claude `raj-claude`. Each agent registers its
  own key and passes `--as` on every call.
- **The parent (`raj-66726630`) owns ALL Blender mutations.** Peer Claude (author 5)
  is a read-only reviewer; its messages were mostly queued and **no current-wave
  review has returned**, so do not claim the review is complete.
- Only one agent mutates the scene at a time; coordinate through the editor mailbox
  rather than switching scenes under another agent.
- Read the live scene before editing it. Preserve `Astra.Hand.Source` and the
  `ClayPass1` baselines. No global undo or purge. Copy a mesh before deforming.

## Next work

1. Owner/peer review of every annotated note; #1 (foreground rock appearance) and
   #10 (hands' fullness/texture) are the strongest remaining gaps. Statuses are
   owner-only — read the live owner file `renders/notes/hand3d_live.png.json` (never
   edit it) instead of labelling a note fixed or accepted here.
2. Grain remains deprioritized by the owner; not tuned in this wave.
3. Keep the .blend unsaved for the owner; no scene fix is final.

## Change log

### 2026-10-13 — Pass 2: nails + palm smoothing (main, raj-66726630)
- Intent: add fingernails and soften the palm without moving the approved fingers.
- Touched: `Astra.Hand.L` mesh (palm vertices only); new curves `Astra.Claw.*`;
  materials `Astra.Clay`, `Astra.Keratin`; new scene `Astra.Hand.Review`.
- Changes: as described in Pass 2 above.
- Validated: `look` plus isolated front/right/top/three-quarter views; nail
  shells inspected front/right/three-quarter; side views confirm volume;
  outputs `hand3d_live.png`, `astra_left_clay.png`.
- Pending: owner/peer review of the claw pose; .blend unsaved.

### 2026-10-13 — Pass 3: frame-right hand + owner notes 1-10 (main, raj-66726630)
- Intent: build the frame-right hand and address the owner's 10 annotated issues
  without restarting or moving the endorsed left-hand placement; owner asked to
  ignore the bottom TITLE area and deprioritized global grain.
- Touched: `Astra.Hand.R` + right claws + `Astra.Hand.R.ClayPass1`; both hands'
  meshes and skin materials (notes 3, 10); `Astra.SceneNotes` and the note objects
  (`Astra.ArchedRock`, `Astra.FloatingRock.*`, `Astra.HandMist.*`, `Astra.LowFog`,
  `Astra.UpperRightStars`, `Astra.Fragment.*`, `Astra.Boulder`,
  `Astra.Beam.RightHigh`, `Astra.ForegroundFill`).
- Changes: note-numbered detail in `docs/NEFAS-SCENE-ANNOTATIONS.md`.
- Validated: per-batch live look (front / right / three-quarter), a real render and
  `compare_reference`; measurements not substituted for seeing. The latest mesh
  health check is the parent's to run — no new counts claimed here.
- Pending: owner/peer review of all notes; .blend unsaved; this document awaits
  editor acceptance and save.

### 2026-10-13 — Docs: note-numbered delta log (raj-notes-doc)
- Added `docs/NEFAS-SCENE-ANNOTATIONS.md` (append-only per-note log) so this
  handoff stays short, and corrected the handoff wording that forbade the
  frame-right hand.

### 2026-10-13 — Docs: owner renumber + rock split (raj-notes-doc)
- The owner renumbered `renders/notes/hand3d_live.png.json` (canon; never edit). Its
  live open items are now #4–#11 and no note is checked. Per-note detail and the
  old→new map are in `docs/NEFAS-SCENE-ANNOTATIONS.md`.
- Labour split: the parent does hands + atmosphere (#4/#7/#10); Claude (`raj-claude`)
  owns all `Astra.Rocks` objects for #5/#6/#8/#9, serialized by its `claim render` /
  `render done` messages. The "parent owns ALL mutations / Claude is read-only" line
  under *Coordination* above is **superseded** for the rocks. Statuses stay owner-only;
  proposals only, .blend unsaved.

