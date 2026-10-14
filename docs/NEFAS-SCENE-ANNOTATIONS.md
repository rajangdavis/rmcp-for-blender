# NEFAS scene annotations — note-numbered delta log

Companion to `docs/NEFAS-HANDS-HANDOFF.md`, which stays the concise handoff. This
file carries the per-note detail from the owner's annotation pass on
`renders/hand3d_live.png`, so the handoff does not have to.

**Canonical markup: `renders/notes/hand3d_live.png.json` (owner-owned).** Agents
must **never edit** it; its `fixed` fields are the owner's own statuses, not agent
claims. The note list below is a copy, for reference only.

## Status — not a completion claim

- Every change below is **proposed, live and unsaved**; the owner evaluates it, and
  their save is what puts it on disk. Agent renders and measurements are evidence,
  not approval.
- **Do not read this log as an acceptance record.** The owner's statuses are canon in
  `renders/notes/hand3d_live.png.json` (never edit it); at an earlier read only the then-#9 carried
  `fixed: true` and every other note was `fixed: false`. A checked note is a status on that
  note, not a verdict on the scene — the global look is not final either way.
- **Not final.** The two strongest remaining qualitative gaps are the foreground
  rock's appearance (#1) and the hands' painterly fullness/texture (#10). **[2026-10-13: the owner has ticked old #1 and old #10 (owner status only); the renumbered file's open items are its #4–#11 — see the dated entry below.]**
- The parallel reviewer (`raj-claude`, author 5) was read-only at the time (2026-10-13: the owner has since assigned Claude every `Astra.*` rock object — see the dated entry below) and had
  **no current-wave review returned** when this was written; its messages were
  mostly queued.

## Owner sequence that supersedes older handoff wording

1. Pass-1 clay of the frame-left hand was praised: *"looking great so far in terms
   of the models"*.
2. The owner then asked explicitly: *"make the other hand and fix the rest"*. The
   handoff's old *"DO NOT start the right hand until the owner approves"* is
   **superseded** — the frame-right hand is built (see *Hands and claws* below).
3. The bottom **TITLE** area is explicitly excluded: *"ignore those"*.
4. The whole-lookdev direction was criticized as a quality drop; the owner chose
   **DISCUSS**, not rollback, and later said grain is **not a priority**.
5. The owner annotated the 10 issues below, discussed them, and expressly approved
   proceeding.

## The owner's OLD 10-note list (frame u,v regions) — numbering superseded

> **2026-10-13 — superseded numbering.** The owner has renumbered
> `renders/notes/hand3d_live.png.json` (canon; never edit). Live open items are its
> #4 mist (whispier/smokier), #5 boulder (background **and bigger**), #6 large
> **singular** rock, #7 fog (cloudier), #8 rocks flowing right, #9 mountain range vs
> source, #10 UpLeft beam behind the logo, #11 logo crispness/flatter. The rows below
> keep the OLD numbers — do not cite them as live ids. Earlier OLD #1/#2/#3/#8/#9/#10
> were ticked; the JSON is canon. See the dated entry at the end.


| # | region | note |
|---|---|---|
| 1 | u 0–.31, v .64–.95 | massive arched foreground rock; arch like the source |
| 2 | u .05–.32, v .23–.40 | "needs some rocks" (floating rocks) |
| 3 | u .58–.94, v .30–.58 | index finger should be **below** the middle finger |
| 4 | u .41–.70, v .39–.62 | green mist from the hand to the glowing orb |
| 5 | u .53–.78, v .67–.90 | that rock needs to go into the background |
| 6 | u .76–.92, v .76–.85 | fragments/shard here |
| 7 | u .31–1, v .63–.98 | a little (lower) fog here |
| 8 | u .62–1, v .02–.26 | more stars (upper right) |
| 9 | u .86–.95, v .34–.50 | the beam should keep going **and be behind the hand** |
| 10 | u .09–.54, v .34–.67 | both hands lack the source's fullness and texture |

Title area and global grain are excluded (owner).

## Rollback snapshots taken for this wave

- Every current hand/claw mesh saved as a fake-user `.BeforeNotes3_10` datablock;
  exact per-object names in `Scene['astra_notes3_10_backup']` (JSON). **Mesh
  rollback only** — it does not undo the materials, modifiers or pose metadata
  applied afterwards.
- Material backup `Astra.Skin.BeforeNote10` (fake user).
- Beam checkpoint mesh `Astra.Beam.RightHigh.BeforeNote9` (fake user), named in
  the object's `['note9_backup']`.
- `Astra.ArchedRock.GridCheckpoint` (fake user) — the superseded first attempt.
- Prior boulder location/scale/material in JSON `Scene['astra_note5_before']`.
- Broad-lookdev old state in JSON `Scene['astra_scene_backup']`.

## Batch 1 — notes 3 and 10, and the hand foundations

**Note 3 — right index below middle.** Independent right-index vertex-set shifts
(from source face sets 278, 283, 282) in screen and depth; **no whole-hand bbox
refit**. Measured on the live frame: right index PIP (0.7144, 0.3793), middle
(0.7673, 0.3314) — the index is now clearly *lower*. The nail moved with it, and
its tip was shortened so it does not touch the thumb.

**Note 10 — fuller / fleshier.** Normal inflation, local and per-region: palms
0.27 world units, proximal digits ~0.145/0.15, middles ~0.13, distal ~0.075, thumb
base 0.20. Interior palm smoothed 2 passes at 0.12. The clean source is unchanged
and the outer placement was not refit. Nails reseated by camera-ray hits.

## Materials for note 10 (approximate — not accepted final)

- New point Float attribute `skin_creases`, derived from the original source joint
  ring distance divided by 0.0036; material crease darkening max 0.38, roughness
  0.9, specular 0.1.
- Later: local colour ramp 1.65x and a small 0.12 material emission so the surface
  reads as flesh; nail material `Astra.Keratin.Teal`, base (0.070, 0.160, 0.145),
  roughness 0.78.
- **Bounded front-facing reference-colour blend**, max 0.28, gated by `HandMask`
  and a `-worldNormalY` clamp; `UV_PROJECT` applied **after** the subdivision on
  each hand; UV layer `Astra.ReferenceUV`; projector = the main Camera. The
  procedural material still shows on the sides and back. No projected mask was
  used as geometry. This is a deliberate **fixed-cover-view** surface tint applied
  after the actual pose — not the rejected bas-relief, and not a guarantee of a
  pixel match. The UV Project is live scene state, not necessarily
  export/animation ready.

## Batch 2 — notes 1, 5, 9

**Note 1 — arched foreground rock.** Collection `Astra.SceneNotes` created.
`Astra.ArchedRock` is intended to fill the bottom-left with a peak near u 0.14,
v 0.722 and a slope to the right; the silhouette knots are stored in the object's
`['silhouette_knots_uv']`.

- The first attempt (an initial closed grid terrain) read as vertical
  columns/ribbon — **superseded; do not reuse it as a recipe**. Its mesh is kept as
  `Astra.ArchedRock.GridCheckpoint` (fake user).
- Current geometry: a clone of the **evaluated original** `RockLeft` (4987 verts /
  1494 faces, as observed) baked into world space; a camera-UV warp driven by the
  **local-u-bin top and bottom silhouette** (70 bins), *not* a single global
  silhouette (which had collapsed the rock's apparent thickness into a ribbon). It
  maps u to [-0.08, 0.64] and its bottom edge to v 1.15, below frame. It preserves the
  real source fractured topology and Y depth; the original `RockLeft` stays hidden and
  untouched.
  `source_geometry`, `profile_source`, `previous_photographic_mesh` and
  `grid_checkpoint` are recorded on the object.
- Material `Astra.ArchedRock.PhotographicStrata` (clone): the original photo
  textures, a reduced cyan crest, slate base floor (0.011, 0.025, 0.035) and 0.35
  small ambient emission to show the dark body.
- Targeted area light `Astra.ForegroundFill` at (-7, -14, -3), 500 W, size 5,
  colour (0.33, 0.52, 0.65), aimed at (-5, -4, -8).
- **This image is still not an exact rock match.** The parent explicitly wants
  owner/peer review here; do not call note 1 fixed.

**Note 5 — boulder to the background.** `Astra.Boulder` moved to y 12, preserving
the desired screen position (0.647, 0.808) at scale 0.95; material
`Astra.Boulder.Background` ramps brightness by 0.62. Prior location, scale and
material in JSON `Scene['astra_note5_before']`. The original boulder stays hidden. **[2026-10-13: the parent later moved `Astra.Boulder` to y 19.5, scale 0.66, dimmed ×0.72 while Claude was offline; Scene['astra_boulder_deepen'] holds the before/after and Scene['astra_note5_before'] is the original (the move was the parent's, not Claude's). Claude is mid batch-3 re-do of #5/#6/#8/#9; its claimed next shape is bigger and further back — not final; the parent's round-3 `Astra.Fragment.*` sit inside owner #6's box.]**

**Note 9 — beam continues, behind the hand.** `Astra.Beam.RightHigh` extended to
end uv (1.045, 0.366); per-longitudinal-t depth y = 6.5 * t^0.8; half-width
0.001 + 0.016 * t. It passes behind the right hand. The original new-ray
checkpoint mesh is `Astra.Beam.RightHigh.BeforeNote9` (fake user), recorded in the
object's `['note9_backup']`. The main camera is unchanged. The owner's annotation
file at an earlier read recorded its then-#9 with `fixed: true`; **[2026-10-13: the owner has renumbered the file and as re-read no note is checked. That beam note is now the file's #10 — "this beam needs to go behind the logo" — which the parent's round-3 `Astra.Beam.UpLeft` change targets.]**; that is the owner's own field, quoted here —
it is not an agent claim of acceptance, for #9 or anything else.

## Batch 3 — notes 2, 4, 6, 7, 8

- **Note 2** — 12 angular floating stones `Astra.FloatingRock.00..11` in the
  annotated upper-left, depths 4..10; the original painted logo occludes them
  naturally. Material `Astra.Floating.Stone`. Tagged `owner_note2`.
- **Note 6** — 22 closed convex slate fragments `Astra.Fragment.00..21` in
  u 0.764–0.917, v 0.771–0.842, depth 3..8; material `Astra.Fragments.Slate`.
  Tag 6. The old source fragments are retained.
- **Note 8** — 100 extra distant stars as one combined mesh
  `Astra.UpperRightStars`, u 0.62–1.01, v 0.015–0.26, depth 26..33, dim cyan
  emission. Tag 8. The existing Stars are retained.
- **Note 4** — 4 transparent/emissive soft mottled ribbons `Astra.HandMist.0..3`
  along (0.682, 0.506) -> (0.443, 0.633), smooth wiggles, UV edge fade / end fade /
  noise, green material `Astra.Mist.Flow`, alpha multiplier final 0.42. Tag 4.
  View-facing FX, not a fluid simulation; the 3D scene geometry is preserved.
- **Note 7** — true bounded 3D low fog `Astra.LowFog`, box centre (5, 10, -8),
  scale (11, 13, 5.3), generated-noise density 0..0.012 with a 3-axis boundary
  fade, slight green emission proportional to density, Principled Volume, material
  `Astra.LowFog.Volume`, display WIRE, tag 7. The fog is intentionally subtle.

## Broad lookdev candidate (pre-annotation — NOT approved)

- Collection `Astra.Atmosphere` with 5 UV-profiled transparent/emissive light
  sheets `Astra.Beam.UpLeft`, `.RightHigh`, `.RightLow`, `.DownRight`, `.DownLeft`
  (parented to Orb with an inverse that preserves world shape); the old `Beam_*`
  hidden and retained.
- `Astra.Orb.Glow` radial soft billboard replaces the hidden `OrbHalo`. Orb's
  final material `Astra.Orb.Filaments` is a **copy of the original `OrbMat`**
  (restoring the original animated amoeba filaments; the intermediate
  `Astra.Orb.Surface` Voronoi try is **superseded**). Ball light 2100, colour
  (0.38, 0.95, 0.80).
- Old lights/materials/hides/transforms recorded in JSON
  `Scene['astra_scene_backup']`. The original Sky/Logo/Rock materials remain; new
  copies `Astra.Sky.Palette`, `Astra.Logo.Olive`, `Astra.Rock.Strata`,
  `Astra.Wisp.Haze`; Stars clone `Astra.Stars.Subdued`; a new standalone angular
  `Astra.Boulder` replaced the original hidden Boulder.
- **The owner called the overall direction a quality drop.** Do not promote any of
  this as best practice, or as an approved look.

## Hands and claws (current state)

- `Astra.Hand.Source` — clean appended source, unchanged, original preserved.
- `Astra.Hand.L` — posed; 782 verts / 771 base faces, subdivision levels 2/2;
  baseline `Astra.Hand.ClayPass1` (fake user). The original left placement is
  preserved.
- `Astra.Hand.R` — built **independently from the clean `Astra.Hand.Source`**;
  `mirror sourceX` for chirality; the same anatomical face-set method as L; cutoff
  sources 262/287 plus cap; 782 verts / 771 faces / subdiv 2; source preserved.
  Baseline mesh `Astra.Hand.R.ClayPass1` (fake user). Claw objects
  `Astra.Claw.R.Index/Middle/Ring/Little/Thumb`, metadata `belongs_to`
  `Astra.Hand.R`. A full right-hand target JSON lives on the object — do not
  duplicate every joint here.
- Reference sides: for frame-**RIGHT** use *'left hand, right side real.png'* (the
  subject's anatomical left); for frame-**LEFT** use *'right hand, left side
  real.png'*. Never conflate frame side with body side.
- A palm-only broadening was applied earlier: frame V span ~0.451 x2 and tail X
  beyond 0.85 compressed to 0.72, smoothing 2x3, metadata `palm_refinement`.
- `HandCard.R` is now hidden and retained; `HandCard.L` was already hidden and
  retained. The old failed objects remain hidden.
- **Latest BASE mesh QA (parent-verified).** `Astra.Hand.L` 782 verts / 771 faces,
  `Astra.Hand.R` 782/771, `Astra.ArchedRock` 4987/1494 and `Astra.Boulder` 162/320 — all
  four at 0 non-manifold edges, 0 loose verts, 0 zero-area faces. Separate from the earlier
  twelve hand/claw checks and not proof of no self-intersection or an exact visual match;
  `Astra.Hand.Source` is unchanged at 871 verts. Do not invent other counts.

## Validation and outputs

- Each batch was checked with the live look (main camera, isolated front / right /
  three-quarter) **plus** an actual render and `compare_reference`. Measurements
  were not substituted for seeing.
- Current primary preview: `renders/hand3d_live.png`, full scene, 1080 square,
  frame 1, 64 samples, EEVEE. The last current render followed the rock-lighting
  change at 500 W.
- Bottom title mask used for comparisons — full-frame polygon
  `'.22 .88,.80 .88,.80 .98,.22 .98'`.
- **Caption is not file.** `compare_reference` captions are not proof that the
  compare PNG exists on the Blender host; keep that warning.
- **Stale now:** `renders/astra_notes_clean_review.png` is a temporary **no-grain**
  diagnostic from an earlier batch-3 render; it is stale against the final rock
  geometry/material and the hand reference-colour blend. The parent may refresh
  it; do not claim it as current. `compare.png`, `cmp_zoom.png` and
  `astra_left_clay.png` are historical.

## Diagnostic: the muted-compositor lesson (CanvasGrain)

Kept because it corrects a false blanket claim in
`docs/reference-reconstruction.md` §12.

- `CanvasOverlay` (type `MIX_RGB`) was **connected AND MUTED**. The image
  `CanvasGrain` genuinely had 1 user — a compositor image linked through
  `CanvasOverlay` to the output — but while the node was muted it **contributed
  nothing to the render**. A real user count and a real link prove *presence*, not
  *influence*: check the mute state along the path.
- It was later enabled with custom packed `Astra.PaperGrain` and factor 0.13
  during the broad lookdev. The owner now says grain is **not a priority**, and
  this correction wave does not tune it.
- Temporary diagnostic renders mute it and restore the state in a `finally`; they
  are not a retained grain change. The main compositor still uses the prior
  grained candidate.
- After the diagnostic, the main scene/camera and the old grain setting were
  restored.

## Housekeeping

- The .blend is **live and UNSAVED**; no agent saves it.
- `renders/notes/hand3d_live.png.json` was **never edited** by agents.
- The main camera was not changed to shift the frame rightward.
- `docs/reference-reconstruction.md` and the primary `rmcp-blender-skills/SKILL.md`
  were already owner-saved; the review guide's groups 3/4/5 were subsequently
  owner-saved too. Do not assume a pending group — check `raj ctl groups` in the
  editor, and re-read the file, which may have moved past this log.

## Open items (do not mark fixed)

- Old #1 (foreground rock) and old #10 (hands' fullness/texture) were the strongest
  remaining gaps; **[2026-10-13: the owner has since ticked both — owner status only. The
  renumbered open items are #4 mist, #5 boulder, #6 singular rock, #7 fog, #8 rocks
  flowing right, #9 mountain range, #10 beam behind logo, #11 logo crispness — see the
  dated entry at the end.]**

- Every other note likewise awaits owner evaluation — none is checked as of 2026-10-13 (all `fixed: false`). An earlier read had the then-#9 checked in the owner's
  file, and a checked note is not scene acceptance.
- Grain: deprioritized by the owner; not tuned in this wave.
- The parent's latest BASE mesh QA (four meshes) is recorded under *Hands and claws* above.

## 2026-10-13 — owner renumber, round-3 atmosphere, and the rock split (PROPOSED, UNSAVED)

**Owner-statuses-only.** `renders/notes/hand3d_live.png.json` is owner canon and
**read-only** for agents: never edit it. Nothing in this entry is owner-accepted, and no
`fixed` field is an agent claim. Agents pass `--as <key>` on every `raj ctl` call.

### The owner renumbered the JSON (canon); the table above uses OLD numbers

| new # | owner note (condensed) | region (u, v) |
|---|---|---|
| 4 | mist hand→orb; more whispy, closer to the smokier source | .405–.702, .393–.617 |
| 5 | rock into the background, **and bigger** | .529–.783, .673–.896 |
| 6 | a large **singular** rock here | .759–.917, .763–.854 |
| 7 | fog cloudier | .314–1, .63–.977 |
| 8 | rocks keep flowing right | 0–.147, .747–1 |
| 9 | mountain range vs source (owner speculates it relates to the title being blocked — i.e. the compare mask) | .017–1, .718–.994 |
| 10 | UpLeft beam behind the logo | .224–.433, .026–.406 |
| 11 | logo crisper/flatter, colour from the reference (also in the JSON) | .081–.856, .034–.347 |

Old→new: OLD #4 mist = new #4; OLD #5 boulder = new #5; OLD #6 fragments ≈ new #6 (now
*singular rock*); OLD #7 fog = new #7; OLD #8 stars has **no new note** (new #8 is rocks
flowing right); OLD #9 beam-behind-hand = new #10 (beam behind **logo**); OLD #1/#2/#3/#10
have no new counterpart; new #9/#11 are new. Earlier OLD #1/#2/#3/#8/#9/#10 were ticked.
**As re-read, no note is checked — all `fixed: false`.**

### Split of labour

- **Parent `raj-66726630` — hands + atmosphere:** new #4 mist, #7 fog, #10 UpLeft beam.
- **Claude `raj-claude` — ALL `Astra.Rocks` objects:** `Astra.ArchedRock`,
  `Astra.FloatingRock.*`, `Astra.Fragment.*`, `Astra.ForegroundFill` (the note-1 rock
  object — **not** "Astra.ForetoldFill"), `Astra.Boulder`, for new #5/#6/#8/#9. Its
  `claim render` / `render done` messages serialize the shared render.

### Parent round 3 (live, unsaved; the .blend save is the owner's)

- **#10** `Astra.Beam.UpLeft`: vertex y ramps −0.30 at the orb to +1.60 at the tip, so it
  crosses behind `NefasLogo` (logo y −0.3..0.3). Object prop `note10`.
- **#4** mist rebuilt as six soft radial-noise "smoke puffs" `Astra.MistPuff.0..5`
  (material `Astra.Mist.Smoke`: radial falloff × two noise scales × opacity 0.55; emission
  0.14/0.235/0.115 at 0.9) plus two faint strands `Astra.HandMist.0..1` (material
  `Astra.Mist.Flow`, opacity 0.34) flowing from the right hand to the orb. The old strand-y
  version is mid-replaced; `Scene['astra_round3']` flags it.
- **#7** fog: `Astra.LowFog.Volume` noise scale 2.2, detail 5, ramp 0.45→0.62, tops
  (0.058, 0.072, 0.044). This **supersedes** the earlier batch-3 density bump.

### Boulder history for new #5 (avoid double-edits)

- The **parent** moved `Astra.Boulder` to y 19.5, scale 0.66, dimmed ×0.72 **while Claude
  was offline**; `Scene['astra_boulder_deepen']` holds the before/after and
  `Scene['astra_note5_before']` the original. This was not a Claude change.
- Claude's `Claude.Boulder.Round` mesh, material `Claude.BoulderPaint` and the
  `SUBSURF`+`DISPLACE` modifiers remain. Claude is mid batch-3 re-do of #5/#6/#8/#9; its
  claimed next shape is **bigger and further back**. Neither is final.
- The parent's `Astra.Fragment.*` (1.85× scale) sit inside owner #6's box; the parent
  offered Claude "fragments out".

### Earlier waves still current (unless superseded)

- #3 index-below-middle and #10 fullness (pads/mounds, ref-colour 42%, creases 0.52, muted
  nails; backups `.BeforeRemaining9`, props `remaining9_*`).
- #7 earlier density bump — superseded by round 3 (above).
- #8 second starfield `Astra.UpperRightStars2`; ambience haze planes `Astra.Haze.*`.
- Grain: the compositor is restored to its **ORIGINAL MUTED** state — the owner
  deprioritized it, and the muted-compositor lesson above still stands.

### Validation

- Each round used the actual look camera **plus** per-note `compare_reference` crops
  (`astra_note4_mist.png`, `astra_note10_beam.png`, `astra_note56_rock.png`, etc.). The
  compare masks cover the title rectangle (the owner excluded the title). Keep the standing
  caveat: a `compare_reference` caption is not proof the host file exists.
- Scene `Scene`, camera `Camera`, frame 1 restored; no camera moves; .blend unsaved.

### QA

- QA for the three new puffs is **not yet run** — do not invent counts.
- Previously verified: both hands 782 v / 771 f with 0 non-manifold / 0 loose / 0 zero-area;
  `Astra.ArchedRock` 4987/1494; `Astra.Boulder` 162/320. These pre-date Claude's batch 3.

### Parent must confirm

- Claude's batch-3 object list and the `claim render`/`render done` handshake; the
  `Astra.ForegroundFill` name; the old→new note mapping; and whether new #11 (logo) is in
  scope — it is in the JSON but was not in the parent's brief.

