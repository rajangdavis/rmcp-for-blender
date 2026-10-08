# Scene craft: the desert-island diorama, end to end

How Claude built the "STATUS: REAL FUCKIN SICK" island scene on 2026-10-08 through this
repo's Blender server. It covers every number, why each one was picked, what failed first,
and where to read more. It's meant for the next agent that has to turn a prompt into a
picture, especially one that has never seen this scene.

- **Runnable build:** `docs/scene-craft-island.py` (543 lines). It recreates the whole scene
  from an empty file and renders it. It was tested by running it into a throwaway scene
  under a different name prefix and comparing that render with the original.
- **Renders:** `~/Desktop/claude-island.png` (v1, square, thin neon title) and
  `~/Desktop/claude-island-v2.png` (v2, 1200x1600 portrait, the fat Impact sign). They were
  written to the host before the no-host-writes rule (see "Rules for agents" below). New
  renders come back by value instead.
- **In the .blend:** scene `CLAUDE_island`, every datablock prefixed `CL_`. It is not saved
  into the file unless someone saves it. Since v2 it has been polished by the other agent and
  its sub-agents (aviators, no pickguard, darker hardware, froth displacement, sign weight; see
  sections 9, 11 and 13). **The live scene is the source of truth for current numbers.** This
  doc records the decisions and why, and some values below are the v2 build's, not today's.

The prompt, verbatim:

> a small desert island with a small bearded dude playing a BC Rich Mockingbird, no shirt,
> swim trunks, no tattoos, racially ambigious, and the waves are crashing all around him
> and there's a giant text thing that overhangs saying "STATUS: REAL FUCKIN SICK" but with
> line breaks every word in glowing legible thin text

Follow-ups, in order: dusky colour, so you can't tell whether the sun is rising or setting;
"small cube framed shots"; then for v2, text "super thick and bold and obnoxious", "glowing",
"larger".

---

## Rules for agents working on this scene (read first)

Several agents, and sub-agents, now work in the same Blender at once. These rules come from
mistakes made on 2026-10-08.

**Security** (full findings and the fix in `docs/blender-sec.md`):

- **No writes to the host outside the repo.** The owner's words: "agents shouldn't have write
  access on the host". Don't `open()` files, don't render or export to `~/Desktop` or `/tmp`,
  and don't `shutil` anything. To show a picture, use `look`/`screenshot`. The image comes back
  in the reply, and the MCP client stores it on the agent's side. The server is being
  changed to enforce this (path jail, render returning the image, checks on agent Python).
- **Only talk to Blender through the MCP server.** Never connect to the addon's socket
  (:9876) directly. Its new bridge token is held only by the server, by design.
- **Never put a token in mail or in a doc**, whether the MCP bearer token or the bridge
  token. Treat them as passwords.

**Sharing one Blender:**

1. **Own scene, own prefix.** Every datablock (objects, meshes, materials, worlds) gets
   your prefix. Object names are global across scenes.
2. **Resolve your scene explicitly.** `bpy.data.scenes["NAME"]`, never `bpy.context.scene`:
   another agent or the owner may switch the window's scene at any time. That happened in
   this session.
3. **Never delete by pattern across the file.** A cleanup like `startswith("DEMO_")` plus
   "every Camera/Light" would have deleted another scene's objects. Delete by exact name, and
   only inside your own scene.
4. **Polishing someone else's scene:** one change at a time, `look` after each, then report
   every change (object, property, old → new, why) to the scene's owner. The other agent's
   polish pass did exactly this and is the model to follow.
5. **Sub-agents** inherit none of this unless the brief says so. Put the scene name, the
   prefix, the objects they may touch, and these rules into every sub-agent brief. Two
   sub-agents must never edit the same object; split the work by object group.
6. **Seeing.** An agent only sees if its client turns MCP image blocks into images. A client
   that hands the agent the reply as text (through a shell, say) delivers base64 the model
   cannot perceive. The other agent worked blind for hours that way before switching to
   native MCP tools. If you can't see, say so, and ask a seeing agent to judge.

## 1. Working rules (why nothing collided with the other agent)


Another agent was editing the same Blender at the same time. Five rules kept us apart:

1. **Own scene.** `bpy.data.scenes.new("CLAUDE_island")`. Objects are created with
   `bpy.data.objects.new` and linked into that scene's collection. No `bpy.ops` that depend
   on context, so nothing ever lands in the other scene by accident.
2. **Own prefix.** Every object, mesh, material and world is named `CL_*`. Object names are
   global across scenes in a .blend, so a helper that deletes and recreates `"title"` would
   delete the other agent's `"title"`. The prefix is the only thing that prevents that.
3. **Render by name.** `bpy.ops.render.render(write_still=True, scene="CLAUDE_island")`
   renders a scene that is not the window's active scene, so the active scene never changes.
4. **See with `look {"mode":"image","image":PATH}`.** `look mode camera` uses the window's
   scene, so I rendered my own scene to a PNG and looked at the file instead.
5. **Helpers in a text block.** Functions defined in one `execute_code` call do not persist
   to the next one. I stored the helper library in a Blender text block
   (`claude_helpers`) and started every call with
   `exec(bpy.data.texts["claude_helpers"].as_string())`.

A long call outlives the bridge's timeout and returns `Blender bridge unreachable` even
though the work finishes; see `blender-notes.md`. `ping`, then check the output file's
mtime, before re-running anything.

## 2. Build order and why

Environment first (sky, camera, light, water, island), so the hero is judged in its final
light. Then the hero (the guy and the guitar). Then the effects (breakers, whitewater, spray),
which have to be placed relative to the island's shoreline. The type goes last, because it
has to fit into whatever space is left without covering the hero. After each stage I
rendered at 40-60% and looked. That came to about ten looks for the whole scene, and each
one changed something.

## 3. Render and colour

| setting | value | why |
|---|---|---|
| engine | `BLENDER_EEVEE_NEXT` | 2-20 s renders. Fast enough to look after every change |
| samples | 48-64 while iterating, 128 final | |
| view transform | AgX, look `AgX - Punchy` | saturated, contrasty, cartoon-friendly |
| exposure | 0 | |
| bloom | compositor Glare node, `BLOOM`, threshold 1.2 (0.9 in v1), size 6, quality HIGH | EEVEE Next removed built-in bloom |
| resolution | v1 1200x1200; v2 1200x1600 | v2 needed headroom for a much bigger sign |

**AgX trap:** a bright, saturated emissive gets pushed toward white. The v2 title face at
emission 1.6 rendered cream, not yellow-to-pink. At 0.75 it kept its colour, and the
separate cyan neon rim layer (emission 3.5) carries the glow instead. Rule: keep the
coloured face below about 1, and get the glow from a separate rim or halo layer.

## 4. The sky: what the camera sees is not what lights the scene

The world shader mixes two backgrounds by **Light Path → Is Camera Ray**:

- **Camera rays** see a screen-space gradient: `Texture Coordinate → Window`, take Y, then a
  B-spline Color Ramp with stops 0.00 `(1.00,0.42,0.16)` hot peach, 0.28 `(1.00,0.36,0.30)`
  coral, 0.55 `(0.62,0.12,0.42)` magenta, 0.82 `(0.16,0.06,0.32)` violet and 1.00
  `(0.04,0.03,0.14)` near-black indigo, at strength 1.0. Window coordinates mean the gradient
  always runs bottom to top of the frame, whatever the camera does. The other agent's
  world-direction gradient showed only one flat band of its ramp in an iso view; that's why
  theirs looked like flat tan.
- **Every other ray** (diffuse and glossy lighting) sees a soft dome: `Generated` Z mapped
  -1..1 onto a ramp from `(0.90,0.42,0.35)` warm at 0.40 to `(0.30,0.30,0.62)` cool at 0.75,
  strength 0.55. Warm bounce from low, cool from above.

So the backdrop can be a bold graphic gradient without dumping magenta light on everything.

**Sunrise or sunset:** an emissive disc (`(1.0,0.55,0.22)`, strength 3, radius 0.75 x scale
0.75), rotated to face the camera and pushed 14 m behind the diorama. It sits at screen-left,
half hidden behind the water block's corner, with no shadow. A low sun half behind the
horizon line reads as either dawn or dusk. That ambiguity is what the dusky follow-up asked
for.

## 5. Camera: true isometric, orthographic

- `type ORTHO`. Rotation `(54.736°, 0, 45°)`: 54.736° = 90° − atan(1/√2), which gives the
  classic 35.264° elevation of true isometric.
- Placement: take the view vectors `fwd = R·(0,0,−1)`, `up = R·(0,1,0)`,
  `right = R·(1,0,0)`, and set `location = target − fwd·20`. In ortho the distance only has
  to clear the geometry. Framing comes from `ortho_scale` and from sliding the target along
  `up`/`right`.
- v1: target (0,0,0.75), ortho 6.2, then tightened to 5.4 with target (0,0,0.95). v2:
  portrait, ortho 7.2 (ortho_scale spans the LONGER side, so 5.4 × 1600/1200), and the
  target lifted by `up·0.9` so the extra frame lands above the island for the sign.

## 6. Lights: one motivated sun and one fill

- **Sun** `(1.0,0.62,0.36)`, energy 4, angle 3°. It comes from azimuth 160° and elevation 18°,
  behind and to the left in the camera's view, so the figure gets a warm rim and the
  breakers are lit from behind. To aim a sun: compute the direction TO the light and set
  `rotation = (−dir).to_track_quat('-Z','Y')`, because a light shines along its local −Z.
- **Fill** `(0.55,0.62,1.0)`, energy 0.9 in v1 and 1.4 in v2, angle 20°, from the camera side
  `(1,−1,1.2)`, so the face on the shadow side isn't black.
- No studio three-point rig. The other agent's first scene had seven suns plus Blender's
  default 1000 W point light, and the result was flat.

## 7. The water block: one mesh, foam as data

**Geometry.** A 116×116 grid over ±2.3 m, height-mapped, with a skirt down to z = −1.4: each
boundary vertex gets a twin at the bottom, and quads join them. One mesh, two material
slots: top 0, sides 1.

```
water_h = 0.035 sin(3.1x+1.3y) + 0.025 sin(−1.7x+3.9y+1.1) + 0.015 sin(6.3x−5.1y)
        + 0.06 exp(−(r−1.75)²/0.08)        # a swell ring piling up toward the island
```

**Foam is a vertex attribute**, not a texture: `bm.verts.layers.float.new("foam")`. A float
layer in bmesh becomes a point attribute, which a shader reads with an **Attribute node**
named `foam`. Per vertex:

```
shore  = smoothstep(0.30, 0, |r − R_island(θ) − 0.05|) · (0.6 + 0.5·noise2(x,y))
streak = smoothstep(0.80, 0.98, noise2(0.5x+3, 0.9y−2)) · 0.45 · smoothstep(1.4, 2.1, r)
foam   = min(1, max(shore, streak))
noise2 = 0.5 + 0.25 sin(11x + 3 sin 7y) + 0.25 sin(13y + 2.7 sin 9x)   # cheap domain-warped sines
```

The first version's streak threshold was 0.62..0.95 at full scale, and the sea came out
covered in even white **cow spots**. Raising it to 0.80..0.98, halving the x frequency and
fading streaks in only beyond r = 1.4 made them sparse and directional.

**Top material:** Principled `(0.012,0.20,0.24)`, roughness 0.06, specular 0.6. A Mix Shader
blends it into a foam Principled `(0.92,0.96,0.97)`, roughness 0.7, SSS 0.2, with the factor
taken from the attribute.

**Side material** (the cut-away cross-section): `Texture Coordinate → Object` Z, mapped from
−1.4..0.05 into a ramp. 0.00 is sea-floor sand `(0.55,0.38,0.22)`, 0.13 darker sand
`(0.42,0.28,0.16)`, 0.16 is a hard cut to navy `(0.01,0.03,0.09)`, and 1.0 is teal
`(0.03,0.42,0.45)`. The same colour feeds a Principled (roughness 0.15) **plus an emission of
0.35**, so the cut face glows like lit water instead of reading as a painted box.

## 8. The island

A disc of 22 rings × 72 spokes plus a centre vertex. The shoreline radius wobbles:

```
R_island(θ) = 1.22 (1 + 0.07 sin(3θ+0.4) + 0.045 sin(5θ+1.7) + 0.025 sin 9θ)
z(t)        = 0.30(1 − t^2.6) − 0.35 smoothstep(0.85, 1, t) + 0.025 sin(2.3x+1) sin(1.9y+0.5)(1−t)
```

t^2.6 gives a flat top that rolls off at the shore, and the smoothstep term dives the rim
under the water. The first version used `0.012 sin(17θ + 5t)`, which pinched the radial
spokes into a **pie crust**. Any ripple that depends only on θ does that. Use x/y dunes.

Sand: Principled `(0.80,0.58,0.36)`, roughness 0.95, specular 0.1 (the other agent's glossier
sand mirrored the pink sky as streaks). Object Z from 0..0.09 mixes from wet `(0.38,0.24,0.14)`
to dry, so there's a darker band at the waterline. There are six flat-shaded icosphere rocks
at the shore, `(0.16,0.13,0.12)`.

## 9. The guy

### Frame convention: decide it once and write it down

Everything is modelled in a local frame: **front = −Y, his left = +X, feet at z = 0**. An
empty `CL_actor` at (0.05, −0.05, 0.285) with **Z rotation 45°** turns −Y toward the iso camera
at (+x, −y). v2 scales him 1.4×, to about 1.37 m.

The other agent lost two rounds on this:

- **Parenting.** Its helper set `matrix_parent_inverse = parent.matrix_world.inverted()`,
  which cancels the parent's transform. The head, beard, guitar and trunks stayed 0.92 m
  low, between his knees and under the sand. A plain `child.parent = actor` with an
  identity inverse makes child coordinates parent-local, and that's what you want when
  building in a local frame.
- **Which way he faces.** I misread a render myself: same-brown hair and beard made his face
  read as the back of his head, and I told the agent to flip him, wrongly. The fix is in the
  geometry: beard noticeably darker than hair, hair pulled back (+Y), and two dark eye dots.
  Check facing against the data (which side the beard is on relative to the camera), not
  against a single render.

### Body: sphere sweeps + voxel remesh (a poor man's SDF smooth union)

`sweep(pts, radii)` drops overlapping UV spheres every 12 mm along a polyline, with the radius
interpolated between joints. Everything goes into one bmesh, then a **Remesh modifier (VOXEL,
7 mm) + Smooth (factor 0.6, 3 iterations)** fuses the pile into one skin. This is a discrete
version of a smooth signed-distance union (see Quilez below). The other agent's Skin modifier
attempt failed because it couldn't reach `skin_vertices`; this needs nothing but bmesh.

Joint table, in metres, local frame:

| part | points (x, y, z) | radii |
|---|---|---|
| leg (each side s = ±1) | hip (0.065s, 0, 0.38) → knee (0.085s, −0.012, 0.20) → ankle (0.105s, 0, 0.045) | 0.058, 0.042, 0.031 |
| foot | (0.105s, 0, 0.03) → toe (0.115s, −0.075, 0.018) | 0.03, 0.024 |
| pelvis | sphere (0, 0, 0.40), scale (1.15, 0.85, 0.8) | 0.10 |
| belly | (0, −0.012, 0.48), scale (1.05, 0.95, 1.0) | 0.10 |
| chest | (0, 0, 0.595), scale (1.22, 0.85, 0.92) | 0.115 |
| shoulder bar | (−0.135, 0, 0.655) → (0.135, 0, 0.655) | 0.05 |
| neck | (0, 0, 0.66) → (0, −0.005, 0.77) | 0.047, 0.045 |
| head | (0, 0, 0.865), scale (0.95, 1, 1.06) | 0.12 |
| nose / ears | (0, −0.119, 0.853) / (±0.113, 0, 0.862), ear scale (0.6, 1, 1.2) | 0.022 / 0.026 |

Proportions: the head is about 1/4 of body height. That's chunky and slightly chibi on purpose
(see the vendored `cartoon-style`: exaggerated heads read at small scale).

Skin colour `(0.50, 0.30, 0.19)`, roughness 0.55, SSS 0.12: a medium tone that doesn't point
to any one ethnicity, per the prompt's "racially ambiguous".

**Trunks:** a separate, slightly fatter shell (pelvis sphere 0.112, thigh sweeps 0.068 → 0.062),
remeshed, `(1.0, 0.33, 0.04)` orange. Orange is the complement of the teal water, so it pops.
**Beard:** a jaw-line sweep (−0.10, −0.035, 0.835) … (0, −0.118, 0.765) … (0.10, −0.035,
0.835) with radii 0.036 → 0.048, plus a chin mass (0, −0.105, 0.735) r 0.055, a hanging tip
(0, −0.095, 0.695) r 0.038, and a mustache sweep at z 0.83. Colour `(0.075, 0.032, 0.016)`, much
darker than the **hair**, `(0.16, 0.085, 0.04)`: a cap at (0, 0.03, 0.925) r 0.122, squashed in
z to 0.75, a back mass at (0, 0.075, 0.86), and 14 random curl spheres (seed 3), none allowed
low on the face. **Eyes:** two spheres r 0.013 at (±0.042, −0.104, 0.878).

### The Mockingbird, drawn in its own coordinate frame

The guitar lives in a frame **G**: `u` runs along the neck, tilted 28° up toward his left,
`(cos 28°, 0, sin 28°)`; `v` points toward his head, `(−sin 28°, 0, cos 28°)`; and `n = u×v = −Y`,
the front. The origin J = (0, −0.118, 0.50) is the neck joint, just in front of his belly.
`G` is the 4×4 with those three columns plus J.

- **Body:** a 24-point outline in (u, v), extruded ±0.0225 along n, with a Bevel modifier
  (0.008, 3 segments, angle-limited). The points trace the Mockingbird's tells: the long upper
  horn reaching forward past the neck joint to u = 0.13, the deep upper waist at u ≈ −0.115,
  the hooked lower bout, and the short lower horn at (0.045, −0.075). Gloss black
  `(0.012, 0.012, 0.014)`, roughness 0.18, specular 0.8. Black reads best against skin.
- **No pickguard.** v2 had an 8-point cream plate. It was removed in polish because
  Mockingbirds don't have one (the owner's correction, relayed by the other agent on
  2026-10-08), and it read as a Strat part. The build script still makes it as `CL_gpick`;
  delete that block. **Pickups and bridge:** dark hardware boxes. In v2 they were chrome
  (metallic 1.0, base 0.8, roughness 0.2), and at metallic 1.0 they mirrored the pink sky and
  rendered as pale cream slabs, the same failure as the grey breakers in section 10. Polish
  set `CL_chrome` to base `(0.13, 0.14, 0.15)`, metallic 0.25, roughness 0.45, specular
  0.05. **Neck:** a 0.31 bar, `(0.20, 0.09, 0.035)`. **Headstock:** a pointed 5-point shape,
  in body black.
- **Strap:** an 8-sided tube through tail → behind the back → over the left shoulder → horn.

**The trick that makes him actually play it:** the hands are placed in G coordinates. The
strumming hand is at `G·(−0.10, 0.02, 0.045)`, over the body and in front of it. The fretting
hand is at `G·(0.235, −0.005, −0.03)`, on the neck and just behind it. The arm sweeps run from
the shoulders to those points. Move or tilt the guitar and the hands follow. The other agent
placed hands and guitar separately and got a boxing guard holding nothing.

### Aviators (added in polish)

Two dark lenses: ellipsoids scaled x 1.18 and z 0.68, for the teardrop. Each has a gold rim
made as a **slightly larger gold shell directly behind the lens**, not a torus. A torus rim
desynced from the lens as soon as the lens was scaled into a teardrop, and read as misaligned
rings; a shell can't desync. There's a bridge and angled arms to the ears. All are
`CL_avi_*`, parented to `CL_actor`, so they follow the head frame.

## 10. Crashing breakers


A breaker is a **closed curl profile swept around an arc** of the island. Profile points are
(outward dr, z), with the lip at index 8 overhanging inward:

```
(0.75,0) (0.45,0.10) (0.25,0.24) (0.10,0.40) (0,0.50) (−0.10,0.53) (−0.20,0.48) (−0.27,0.38)
(−0.25,0.29) (−0.18,0.34) (−0.11,0.37) (−0.05,0.32) (−0.03,0.20) (−0.07,0.06) (−0.15,0)
foam weight per point: 0 0 .05 .35 .75 1 1 1 1 .85 .55 .25 .05 0 0
```

The sweep has 60 steps from θ0 to θ1. The amplitude is `A(t) = amp·sin(πt)^0.6·(1 + 0.12
sin(9t + θ0))`, so each wave rises out of flat water at both ends, peaks in the middle and
wobbles a little. Points map to `r = r0 + dr·A/0.5·0.9`, `z = z·A/0.5 − 0.01`. The foam weight
becomes the vertex `foam` attribute, scaled down where A is small. There are three breakers:
65–160° (r0 1.62, amp 0.50), 185–285° (1.66, 0.46) and 305–395° (1.60, 0.52), with gaps
between them so the shoreline foam shows through.

**Material:** teal Principled `(0.03, 0.42, 0.44)`, roughness 0.12, **plus emission
`(0.05, 0.55, 0.55)` at 0.45**, mixed to a white foam shader (+0.3 emission) by
`map_range(foam, 0.35, 0.65)`. The first pass reused the dark glossy sea material, and the
breakers rendered as **grey inflatable rings**: at grazing angles a low-roughness dark
surface just mirrors the sky. The emission is what makes it read as backlit, translucent water.

## 11. Whitewater and spray

- **Plumes:** two per breaker, at 33% and 68% of its arc (six in all), each sitting where the
  lip hits the shore: `(r0 − 0.28)` at z 0.25. Each plume is 38 spheres. Height
  `q = rand^0.85 · H` with H ∈ [0.75, 1.05]. The spread grows with height, `0.06 + 0.32q`,
  scattered along the tangent and slightly inland, and the radius shrinks with height,
  `rand(0.045, 0.10)·(1 − 0.55q) + 0.02`. So each plume is a fan that is wide at the top: an
  explosion, not a column.
- **Crest froth:** 70 small spheres per breaker on random lip/crest profile points (indices
  4–8), ±2 cm jitter, radius scaled by the local amplitude. Without these the curl reads as
  glass.
- All of it goes into **one mesh → voxel remesh 0.026 + Smooth (0.8 × 6)**. Material: white
  `(0.93, 0.97, 1.0)`, roughness 0.55, SSS 0.35, emission 0.35. The other agent's plumes were
  separate un-merged icospheres, which read as **snowballs**. Its next try stacked
  non-overlapping spheres, which read as **eggs on a string**. The spheres must overlap by about
  half for remesh to fuse them.
- **Froth (added in polish):** a Displace modifier after Remesh + Smooth, with a CLOUDS texture
  and LOCAL coordinates. Noise scale 0.055 at strength 0.022 came out **spiky needles**. Scale
  0.11 at strength 0.009 reads as broken-up froth instead of marshmallow. The displacement has
  to be small relative to the remesh voxel (0.026), or it tears the surface into spikes.
- **Spray:** 22 icosphere droplets per plume (separate, not remeshed), radius 0.008–0.028,
  smaller the higher they fly, thrown outward and up to about 1.4 m.

## 12. The palm

- **Trunk:** `tube()` through 29 centres. Starting from base `left·0.60 + back·0.30` at
  z 0.18, it leans `0.55·t^1.7` toward screen-left/back and gets a slight S
  (`0.06 sin πt` back), with height 2.05. Radius tapers 0.078 → 0.048, and
  **`rmod = 1 + 0.13·(i % 2)`** alternates fat and thin rings, which reads as bark bands for
  free. Colour `(0.24, 0.15, 0.08)`.
- **Fronds:** 8, at evenly spaced azimuths ±0.15 rad. Each is an 18-step path whose pitch runs
  from e0 = 25–45° up to `e0 − (95–125°)·s^1.3`, so it arches and droops. Length 0.85–1.05.
  The cross-section is a 3-vertex **V fold** (midrib raised 1.2 cm). Width is
  `0.17 sin(π min(1, s^0.7))·(0.55 + 0.45|sin 38s|)`, and that `|sin|` term makes the
  **serrated leaflets**. Fronds alternate two greens, `(0.07, 0.26, 0.045)` and
  `(0.13, 0.34, 0.06)`, with SSS 0.1. There are three coconuts under the crown.

## 13. The sign

### v1, "glowing legible thin text"

Arial Narrow (`/System/Library/Fonts/Supplemental/Arial Narrow.ttf`), 4 lines, centred,
size 0.46, line spacing 0.92, extrude 0, emission hot pink `(1.0, 0.30, 0.62)` at 7, and
rotation **copied from the camera** so it is perfectly square to the view.

### v2, "super thick and bold and obnoxious", glowing, larger

**Impact.** Three text objects with the same body and frame, each pushed further back along
the sign's own normal:

| layer | offset | extrude | bevel | dz | material |
|---|---|---|---|---|---|
| face | 0.008 | 0.14 | 0.018 (res 2) | 0 | gradient emission (below) |
| ink outline | 0.034 | 0.09 | 0 | −0.06 | near-black `(0.02, 0, 0.035)` |
| neon rim | 0.050 | 0.03 | 0 | −0.11 | emission cyan `(0.1, 0.95, 1.0)` at 3.5 |

Size 0.86, line spacing 0.84, character spacing 1.04. **Text `offset` fattens the glyph
outline.** At my first values (0.05 and 0.078 on size 0.60) the outlines filled the counters
and merged neighbouring letters into **blobs**. Keep an outline offset below about 6% of the
text size.

**Face material:** `Texture Coordinate → Generated` Y drives a ramp running pink
`(1, 0.10, 0.45)` → orange `(1, 0.45, 0.05)` → yellow `(1, 0.92, 0.08)` into an Emission at 0.75.
`Texture Coordinate → Normal` Z, mapped from 0.7..0.95, mixes that against a side shader
(magenta Principled + emission 0.4). Local +Z normals are the front face, so the extrusion
walls come out magenta and the front comes out gradient.

**Pose:** `rot = R_cam · RotZ(−5°) · RotX(+10°)`. It's square to the camera, cocked 5°, and its
top leans 10° toward the viewer, which is the "overhang". At 20° the extrusion smeared the
letters. It sits at `anchor = (0, 0, 0.95) + up·2.62 + right·0.10 − fwd·4`, which is above the
island in screen space and in front of everything in depth.

**It hangs:** two 2.2 cm cable tubes running straight up 6 m from
`anchor ± tw·0.95 + th·1.08 − nz·0.06`, so they hook into the top of "STATUS:". All three text
layers and the cables have `visible_shadow = False`. Otherwise the cables and the ink layer
throw dark wedges across the face. Even so, a few dark notches remain on R and S where the
magenta extrusion walls show; see the known weaknesses.

**Dark notches inside R, A and S.** Most likely the ink layer, not the face walls. Impact's
counters are tiny, and an outline offset big enough to frame the letters also grows into the
counters, where it shows dark through the face. Fix order: shrink the ink and neon offsets
first (keeping the face's extrude, which is the depth). If notches remain, they're the face's
own side walls, so swap the magenta side shader for a darker version of the face gradient.

**The sign has been reworked since v2.** At the time of writing (2026-10-08, after polish):
size 1.4; offsets 0.014 face, 0.042 ink, 0.060 neon; extrude 0.24, 0.16 and 0.05. The ratio
is what carries over, not the absolute numbers: keep outline offsets at or below about 4–6% of
the text size, and scale offsets and extrudes with the size.

## 14. Iteration log (each render, and what it changed)


1. Water + island only. The sky gradient works; the island has pie-crust spokes and the sea
   has cow-spot foam. Fix: x/y dunes, sparse streaks.
2. Close-up of the figure from a temporary 60 mm camera. He reads; the pickups look like
   fingers but are acceptable at diorama scale.
3. Full scene. Breakers are grey inflatable rings and plumes look like popcorn. Fix:
   emissive teal breaker material, crest froth, a bigger remesh voxel with more smoothing,
   ortho 6.2 → 5.4.
4. The sun disc was off-frame. Moved it behind the block's left edge; fill 0.9 → 1.4.
5. v1 final at 128 samples.
6. v2 Impact sign: blobs, cut off, touching his head. Fix: smaller offsets, lean 20° → 10°,
   moved up.
7. Still too small and bleached. Fix: portrait frame, size 0.86, face emission 0.75, rim 3.5,
   glare threshold 1.2.
8. Cables floating and casting shadows. Fix: hook points recomputed in sign space, shadows off.
9. v2 final.

## 15. Known weaknesses

- He's still small, about 13% of frame height in v2. The prompt says "small bearded dude", so
  bring the camera in (lower ortho_scale and re-anchor the sign) rather than scaling him past
  1.4.
- ~~The whitewater is lumpy~~: fixed in polish with a Displace modifier (section 11).
- Dark notches in the sign's R, A and S: see section 13 for the diagnosis and fix order.
- The build script (`docs/scene-craft-island.py`) is the v2 build. It still makes the
  pickguard and chrome hardware, and it renders to `~/Desktop`, which the no-host-writes rule
  now forbids. Set `RENDER = False` and use `look` until the script is updated.
- It's a still. The breaker amplitude, plume scale and strumming arm are all parameters; key
  them and render frames for motion.

## 16. Reading list

Blender, version 4.2 docs:

- Light Path node (the Is Camera Ray trick):
  https://docs.blender.org/manual/en/4.2/render/shader_nodes/input/light_path.html
- Texture Coordinate node (Window, Object, Generated, Normal):
  https://docs.blender.org/manual/en/4.2/render/shader_nodes/input/texture_coordinate.html
- Attribute node (reading the `foam` vertex attribute):
  https://docs.blender.org/manual/en/4.2/render/shader_nodes/input/attribute.html
- Remesh modifier (voxel):
  https://docs.blender.org/manual/en/4.2/modeling/modifiers/generate/remesh.html
- Text properties (offset, extrude, bevel):
  https://docs.blender.org/manual/en/4.2/modeling/texts/properties.html
- Glare node (bloom in the compositor):
  https://docs.blender.org/manual/en/4.2/compositing/types/filter/glare.html
- Colour management and AgX: https://docs.blender.org/manual/en/4.2/render/color_management.html
- EEVEE Next changes in 4.2, including bloom moving to the compositor:
  https://developer.blender.org/docs/release_notes/4.2/eevee/
- `bmesh.ops` (create_uvsphere, create_icosphere, create_circle, recalc_face_normals):
  https://docs.blender.org/api/4.2/bmesh.ops.html
- `mathutils` (Matrix, Vector.to_track_quat): https://docs.blender.org/api/4.2/mathutils.html

Technique:

- Isometric projection and where 35.264° comes from:
  https://en.wikipedia.org/wiki/Isometric_projection
- Inigo Quilez, smooth minimum. Sphere-sweep + voxel remesh is a discrete version of this
  union: https://iquilezles.org/articles/smin/
- GPU Gems ch. 1, "Effective Water Simulation from Physical Models" (Gerstner waves), for when
  the sea needs to move:
  https://developer.nvidia.com/gpugems/gpugems/part-i-natural-effects/chapter-1-effective-water-simulation-physical-models
- Breaking waves (spilling, plunging, the lip and the barrel the profile imitates):
  https://en.wikipedia.org/wiki/Breaking_wave

In this repo:

- `rmcp-blender-skills/SKILL.md`: the tool surface (`look`, `render`, `execute_code`, ...).
- `docs/blender-notes.md`: Blender traps, including the ones this scene added.
- `docs/blender-sec.md`: what an agent can reach through this server and the addon, and the
  layered fix (bridge token, path jail, agent-code policy, OS sandbox). Read it before writing
  any `execute_code` that touches files.
- `vendor/blender-skills/.claude/skills/`: `isometric-style` (true-iso lock, "soft key + cool
  fill", edge contrast), `cartoon-style` + `character-artist/references/body-proportions.md`
  (big heads, shape language), `vegetation-artist` (the palm), `vfx-fx` (meshes + emissive
  instead of a simulation for a still frame), `lighting`, `compositing`, `neon-retrofuturism`
  (the sign), and `qa-review` + `references/visual-match-checklist.md` (rate each element of
  the prompt Match/Close/Miss).
- `vendor/mcp-for-blender/README.md`: the addon underneath. Its asset libraries (Poly Haven,
  Poly Pizza, Sketchfab) were deliberately off for this scene, which is all hand-built.
