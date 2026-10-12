# Scene craft: a flat 2D cartoon in 3D (the 小猫老板 office)

How the cow-cat office was taken from "almost right" to the brief on 2026-10-09:
a cat in a suit sipping coffee at an office desk, with a window onto a blue sky and
golden 小猫老板 lettering, rendered square and animated as a seamless loop. It
covers the decisions, the numbers and what broke first. Read it next to
`scene-craft.md` (the island, the same craft for a 3D diorama) and
`blender-notes.md` (the traps, one per section).

- **File:** `~/Desktop/gigan/xiaomaolaoban.blend`, scene `Scene`, saved by the owner.
- **Renders:** `renders/xiaomaolaoban.png` (1500x1500) and
  `renders/xiaomaolaoban_loop.mp4` (1080x1080, 48 frames at 24 fps, H.264).
  The earlier pass's `raj_cat_boss*` files are left beside them.
- **Helpers:** a text block `claude_helpers` in the .blend holds `peek()` (below).

## 0. Start from what is there, and diff it against the brief

The file already held a full pass by another agent. Rebuilding would have thrown
away a good room, chair, suit and sip animation. Instead:

1. Render the camera view once, small, and look at it.
2. Write the brief out as a checklist and mark every line pass or fail *from the
   picture*, not from object names.
3. Print the facts that decide each failed line: world bounding boxes, parents,
   animation keys, fonts, modifiers. Several failures were invisible in the
   picture and obvious in the data (a text layer at a different size, keys that
   duplicate a frame, a child at the wrong scale).
4. Fix one failure at a time and look after each fix.

## 1. "Reads as 2D" in a 3D file

| choice | value | why |
|---|---|---|
| camera | orthographic, `ortho_scale` 10, pitched about 15 degrees down from horizontal (`rotation_euler.x` 1.3 rad) | an elevation: no perspective convergence, but a sliver of desk top and floor so the furniture still reads as furniture |
| room | one wide back wall (11 m) and a deep floor (10 m), no side walls in frame | the frame never shows a room edge, so there is no box or diorama to read |
| resolution | 1500x1500 still, 1080x1080 video | the brief said square |
| engine | `BLENDER_EEVEE_NEXT`, 96-128 samples for stills, 64 for video | fast enough to look after every change |
| view transform | Standard | flat cartoon colours stay what you typed; AgX shifts them |
| outlines | each solid has a sibling `<name>_ink` object with the dark `ink` material | the drawn-line look; move and scale `_ink` with its partner |

## 2. A window that only ever shows sky through the opening

The back wall is four slabs around a hole: `wall_L`, `wall_R`, `wall_B` (below)
and `wall_T` (above), all spanning y 4.2 to 4.7. The sky is a plane at y about 4.5,
*inside* the slab thickness and larger than the hole on every side. The
slabs' front faces hide every part of the sky except the hole, from any camera
in front of the wall. The reveal pieces (`alcT/B/L/R`), frame (`wfL/R/T`),
mullions and sill sit in the hole. Clouds and the sun sit just in front of
the sky plane, so the frame clips them too.

To move the window, translate every window piece, then move the *vertices* of
the side slabs that border the hole (`wall_L` vertices with x > -4.6 and
`wall_R` vertices with x < 1.0, in world space). Scaling the slab objects instead
would also move their far edges. Animated clouds need their x keys shifted too
(see section 5).

## 3. Staging: the figure, the furniture and the lettering

The brief asked for chair and feet visible, and for the hanzi inside the room
next to the cat. Seating the cat *behind* the desk cuts him at the waist. The
fix was to seat him beside the desk, facing camera, and to put the lettering
on the wall right beside him:

- desk under the window on the left: desk top `x` -4.9..-0.6 (scaled to 4.3 m from 5.4 m), legs moved to
  the new ends, props respaced along it
- cat and chair: x -0.15..2.77
- hanzi column: x 3.1..4.6, z 1.4..7.4, on the wall at y 4.14
- a floor plant cut off by the frame edge was hidden (`hide_render`), not deleted

Moving a figure means moving everything that is not parented to it, all
together: torso, suit pieces, legs, feet, chair parts, casters, every `_ink`
sibling, *and the animated rigs* (`head_rig`, `mug_rig`) through their keys,
plus the fill light that lights the figure. Children of the rigs follow on their
own. Re-measure afterwards: `bpy.context.view_layer.update()`, then world
bounding boxes.

## 4. The cow-cat head: a pattern from a shader mask, not from faces

Male-pattern baldness has to read from the front: a bald white crown and face,
with black hair as a horseshoe around the sides and back at temple height.

Assigning `furb` (black) to faces by position worked, but the edges followed the
low-poly faces and read as jagged. What worked was one material, `headfur`,
with the colour mixed by a mask computed from **object-space** coordinates.
Object space keeps the pattern stuck to the head as it nods.

- normalise: `xn = x/0.78, yn = y/0.72, zn = z/0.75` (the mesh's half-extents)
- side band: `|xn| > 0.5`, between `zn > -0.05` and a scalloped top
  `zn < 0.40 + 0.06*sin(22*yn)` (the scallop is the "tufty hair" edge)
- back: `yn > 0`, under the same top edge
- each threshold is a ramp `clamp((v - edge) * 40, 0, 1)`, so the edge is crisp
  but antialiased; mask = max(side, back); Mix RGBA white to black
- roughness 0.8, specular low: a glossy black catches the glancing light at
  the silhouette and reads grey

Iterations that failed: thresholds 0.42 and a bottom of -0.5 put an eye and the
blush on black. A band at |xn| > 0.56 only showed at the very silhouette.

The comb-over: three bevelled bezier curves (`bevel_depth` 0.036, radius
tapering to 0.4) lying on the crown ellipsoid at 1.02x, waving slightly in y.
They were invisible at first because the head object has scale 1.22 and the
curves did not: a child of the rig does not inherit a sibling's scale. Give such
add-ons the same `scale` and `location` as the mesh they sit on, or parent them
to the mesh itself.

## 5. A loop that is actually seamless

- Render frames `1..N`, and key the loop's closing values at **N+1**, not N. A key
  at N equal to frame 1 shows the same pose twice at the seam: a visible hitch.
  Here every key at 48 moved to 49, with `frame_end` staying 48.
- Bezier keys whose first and last values are equal give zero slope at both
  ends, so a there-and-back (clouds drifting, steam bobbing) eases through the
  seam on its own.
- A continuous rotation (the clock's minute hand: +2*pi over the loop) must be
  `LINEAR`. Bezier eases to a stop at the seam.
- A one-shot action (the sip: keys 1-40) followed by a hold to the end loops
  cleanly as long as its last key equals its first.
- Check with a frame strip (section 7): 1, 8, 13, 20, 30, 40, 48. Frame 48 should
  lead into frame 1 without a jump.

## 6. Big, bold, golden hanzi as signage

- Font: on macOS Blender loads only face 0 of a `.ttc`. That gives "Hiragino
  Sans GB W3" (thin), "PingFang HK Regular", "Lantinghei SC Demibold" and
  "Heiti TC Medium". Lantinghei SC Demibold is the boldest clean face reachable.
  The Lantinghei, PingFang and Yuanti files live under
  `/System/Library/AssetsV2/com_apple_MobileAsset_Font7/*/AssetData/`, not
  `/System/Library/Fonts`.
- Vertical column: the body `小\n猫\n老\n板`, `align_x` CENTER, `size` 1.55,
  `space_line` 1.0.
- Weight and rim: **bevel, not offset**. `offset` 0.08 (and even 0.03 on
  Lantinghei) broke 板, whose glyph has overlapping contours: the fill tore. The
  face uses `bevel_depth` 0.03 to thicken strokes. The dark-gold rim is a copy
  (`hanzi_ink`) 0.06 behind with `bevel_depth` 0.085 and `offset` 0.
- The rim copy must match the face exactly: same font, size, `space_line`,
  alignment and `scale` (1,1,1). The inherited `hanzi_ink` was at size 1.08 x
  scale 1.05 against a face at 1.45, so every glyph was doubled. Bump one font
  setting and you bump both.
- To choose a font, render the same crop once per candidate and stitch the
  crops into one strip (section 7). Eight fonts then cost one image.

## 7. Seeing your work cheaply

`look` is the normal way. Two techniques were worth more than a full-frame look:

- **Crop renders.** Set `render.use_border` and `use_crop_to_border`, with the
  border in 0..1 frame fractions, and the resolution percentage so the crop comes out
  about 400 px. The head, the lettering or the mug then render at full detail for a
  fraction of the cost. Restore the border settings afterwards.
- **Strips.** Render several crops (frames of the loop, or one per font),
  load each with `bpy.data.images.load`, read `pixels` into numpy, concatenate
  along x, and save one JPEG. One image answers "does it loop" or "which font".

Write preview files under the repo's `renders/look/`, never `~/Desktop` or
`/tmp` (see `blender-sec.md`), and delete them when done. When `look` is
unavailable, `peek()` in `claude_helpers` renders a crop to
`renders/look/_peek.jpg` and prints it base64. Print a large pad after it, so
the MCP client spills the reply to a file instead of the conversation.
Unpadded base64 costs about 100k tokens per image.

## 8. Writing the MP4

```python
r = sc.render
r.image_settings.file_format = "FFMPEG"
r.ffmpeg.format = "MPEG4"; r.ffmpeg.codec = "H264"
r.ffmpeg.constant_rate_factor = "HIGH"; r.ffmpeg.gopsize = 12; r.ffmpeg.audio_codec = "NONE"
r.use_file_extension = False          # otherwise the name gets 0001-0048 appended
r.filepath = ".../renders/xiaomaolaoban_loop.mp4"
bpy.ops.render.render(animation=True, scene=sc.name)
```

Read the enum identifiers before assigning them (the server instructions say
why). The 48-frame render outlived the bridge timeout and returned "bridge
unreachable" while it carried on. `ping` first. Then check the file: its size and mtime
should be stable, and `bpy.data.movieclips.load(path).frame_duration` should equal
the frame count. Remove the clip afterwards. Put the still settings (PNG,
resolution, filepath) back when done, so the next render does not write video.
