# Blender notes from building the tool surface

Blender-side facts that cost real round trips while this server was built. The
DSL's own gaps are in `rmcp-dsl-gaps.md`, editor issues in
`editor-issues.md`, and the text-vision design in `text-vision-tools.md`.
Each entry here is something a tool had to be told about, with the evidence
that found it.

## A camera facing the wrong way renders the world, and nothing says so

A render came back twice as a flat grey picture. `image_report` read it
correctly — `mean #3b3b3b`, `palette #333333 97%`, every hue cell a dot — which
is the signature of "world background, no geometry". The object was fine; the
camera was not.

The cause was mine and worth stating exactly, because the tool that reports it
already existed: `place` had been asked for `rx: 90` on the scene camera, which
set the pitch absolutely and left an inherited **36.87 degrees of yaw** in
place, pointing the camera about 3 m to the left of the subject. `place`'s own
report printed `now: rotation (90.00, -0.00, 36.87 deg)` and the number was not
read.

`aim` exists so this is not a judgement call: it frames a target from a named
side, computes the distance that fits the target's size to the lens, and points
the camera with a track quaternion rather than hand-set Euler angles. For a
1.05 m object at 50 mm it chose 2.63 m.

## Undo is the whole file's history, not one tool's

Measured, not assumed:

```
plain undo returned {'FINISHED'}
plain: objects 2 -> 3 after add -> 5 after undo      ← it walked back further than one step
with undo_push first: ok; objects 5 -> 6 after add -> 5 after undo   ← exactly one step
```

So undo *does* cover changes made by scripts through the socket, and
`bpy.ops.ed.undo_push(message=...)` creates an exact boundary. Two consequences
are built into this server: every tool that changes the scene opens a step first
(the module's `undoable` decorator), and `undo` is described as walking the
*file's* history rather than "undo the last call" — because it can cross the
user's own edits and earlier calls. It also does not unlink files that `render`
or `export` wrote.

Two lessons earned the hard way. **Never test undo on a live, unsaved file.**

The first probe, of two undos, walked past that session's changes, resurrected
three objects the user had deliberately deleted, and reset the camera to
Blender's startup default (`7.3589, -6.9258, 4.9583`). Scratch files exist for
this.

The second probe was a *single* step and it ended the session. `undo {"steps": 1}`
right after a `text` call reverted the creation exactly (`objects now (2):
Camera, Light`), which shows the decorator and `undo_push` do what they claim —
and then Blender turned off. The following call found the addon's socket refused
with the MCP server still healthy on its own port, and the user confirmed the
application had gone.

So the `undo` tool was **removed** rather than labelled experimental: a tool that
can end a session is worse than no tool. What remains is the boundary decorator
on every mutating entry point, which is useful on its own terms — the user's
Ctrl-Z lands on a tool call's boundary instead of in the middle of one. The
unresolved asymmetry is worth chasing in a scratch session: reverting a `text`
call worked and that path ends in an *operator* (`object.convert`), while the
case that failed, `remove`, is pure data API.

There is also an unresolved asymmetry worth chasing. Reverting a `text` call
works, and that path ends in an **operator** (`object.convert`). Failing to
revert a `remove` call is the observed case where the change is pure **data API**
(`bpy.data.objects.remove`). If that is the distinction, mutating tools should
prefer operators where one exists — `bpy.ops.object.delete()` for removal —
before undo can be described as a safety net.

## Local view and camera view hide a scene that is fine

Every trap that hides an object while the scene data says it is visible:

- **local view** (`space_data.local_view` set) — the viewport shows only the
  isolated objects; the outliner disagrees.
- **camera view** — `region_3d.view_perspective == "CAMERA"` overrides the
  framing, so `view_selected` appears to do nothing.
- **hidden collections** — `collection.hide_viewport`, or the layer collection's
  `exclude` (which removes it from the view layer entirely, so no viewport can
  draw it) or `hide_viewport`.
- **the object flags** — `hide_viewport`, `hide_set()` (the eye, per view
  layer), `hide_select`, `hide_render`.
- **a second Blender** — another window or process holding the addon socket.

`reveal` reports the file, scene, view layer, window count and viewport count
first, precisely because "the scene" is ambiguous when more than one is open,
then clears those traps and frames the object.

## A text object is a curve, and the mesh tools cannot read it

`bpy.data.curves.new(type="FONT")` produces something `wireframe`, `mesh_report`
and a glTF export cannot read as a mesh. `text` converts to a mesh by default
and says so (`converted to MESH: 1200 vertices, 880 faces`); `as_mesh: false`
keeps the curve when the text must stay editable.

Related: text lies flat in XY, so a **front** view draws its extruded edge — a
thin band — and the **top** view is the one that reads it. `wireframe` was
right both times; the request was wrong.

## A boolean whose cutter contains the object deletes it

```
MCP.001 difference Cube: faces 499 -> 0
the result is empty: check that the two objects overlap
```

A 0.5 m cube added at the subject's own centre encloses it, and the difference
of a containing solid is nothing. The tool reported the count and the likely
cause rather than claiming success. A cutter wants to be a slab: 0.06 m wide
through the glyphs gave `499 -> 456` and five loose parts.

## Modifiers are not the mesh

`array`, `boolean` (with `apply: false`) and any other modifier live *on top of*
the mesh. Reports that read `ob.data` — `mesh_report`, `wireframe` — describe the
base mesh, so a four-copy array still reads as `faces 499`. Renders and exports
apply modifiers, so what is rendered and exported is the array. The array tool
states both numbers: `faces 499 in the mesh, 1996 with the modifier applied`.

## The addon answers `status: "success"` for handler errors

The socket protocol wraps a handler exception as a **successful** reply whose
payload is `{"error": "..."}`. Every request path therefore inspects the payload
rather than trusting the status. A tool that skipped this would report a failed
command as a successful one.

## Orphaned data outlives the object

Deleting an object leaves its mesh and material in the file with no user. They
are not visible in the scene, they are saved into the `.blend`, and they make
"the file is clean" false until purged. `remove` runs
`bpy.data.orphans_purge(do_recursive=True)` and reports what it freed — `purged
data with no user left: 6 mesh(es), 1 material(s)` — and with `purge: false` it
says plainly that the data is still there.

## Lighting is a separate problem from geometry

An object can be perfectly placed and still render dark: the scene's default
light may point elsewhere, and the world contributes flat ambient. The energy
unit changes meaning with the type — a sun is irradiance in W/m² where about 3
reads as daylight, while point, area and spot are watts where 1000 is a lamp —
so `light` reports the type, the energy and what it aimed at, and lists every
light in the file rather than assuming the one it just made is the only one.

## numpy is in Blender's Python, and `foreach_get` is the way in

Blender bundles numpy — not an addon, not optional — so a script can move bulk
data instead of looping over it one element at a time. The bridge is the
`foreach_*` family, which reads or writes a flat buffer in one call:

- `img.pixels.foreach_get(buf)` — what `image_report` uses to read a whole image
  into an array; pixels are `float32`, RGBA, bottom-up.
- `mesh.vertices.foreach_get("co", arr)` — vertex positions in one call, with
  `foreach_set` for the way back; `mesh.polygons.foreach_get("material_index", …)`
  and `mesh.attributes[...].data.foreach_get(...)` work the same way.
- `mathutils` interops: `np.asarray(vector)` works, and for bulk work it is
  cheaper to take the object's matrix once and do `coords @ M.T` than to multiply
  per vertex inside a Python loop.

Gotchas worth knowing before trusting a fast path:

- **The dtype has to match.** Vertex coordinates are `float32`; a `float64` array
  raises instead of converting quietly. Same for pixels.
- **`ob.data` is the base mesh.** Modifiers are not in it — the evaluated object
  from the depsgraph is — which is why `array` and `modifier` report two face
  counts, and why `wireframe`/`mesh_report` see the unmodifiered shape.
- **The loops, not the reads, are what crawl.** `wireframe`'s rasterisation and
  `image_report`'s per-cell reduction are Python loops over a grid, while the
  array reads feeding them are already a single call each. Vectorising those two
  with `np.add.reduceat` / `np.histogram2d` is the cheap win when a generated
  import makes them slow.

Upstream's own guides — seven of them, in the vendored package — never mention
numpy or `foreach_get`, so this is one place their skill material is thinner than
the API deserves.

## "Bridge unreachable" can mean busy, not down

Found while building `docs/scene-craft.md`. An `execute_code` call that remeshed
about 900 spheres and then rendered at 1200x1600 with 128 samples returned
`Blender bridge unreachable; start the addon's server in Blender` three times in a
row. The work had finished: `ping` answered seconds later, every object the call
made was in the scene, and the output PNG's mtime was 2 s old. The bridge times out
on the reply, not on the work, and Blender's single main thread can't answer while
it renders.

So after a long call, `ping` and then check what the call was supposed to produce
(object names, a file's mtime) before doing anything else. Re-running a
non-idempotent script doubles its objects. That was the `.001` duplicate of every
accessory the other agent's scene picked up. Long jobs fare better split up: build
in one call, render in another.

## `matrix_parent_inverse = parent.matrix_world.inverted()` cancels the parent

A figure's head, beard, guitar and trunks rendered 0.92 m too low, clumped between
its knees and under the sand, while the body (parented differently) was right. The
helper had parented with an explicit inverse of the parent's world matrix, which is
what "keep transform" does. It was meant for objects already placed in world space,
and it silently undoes the parent for objects built in the parent's local frame.
When children are authored in local coordinates, set `child.parent = parent` and
leave the inverse at identity. Check one child numerically
(`child.matrix_world.translation`) before trusting the render.

## Two agents can share one Blender if neither switches scenes

Object names are global across scenes, so give every datablock a prefix. Create
objects with `bpy.data.objects.new` and link them into your own scene's
collection, never through context-dependent `bpy.ops`. Render with
`bpy.ops.render.render(write_still=True, scene=NAME)`, which renders a scene that
is not the window's active one. Then view the PNG with
`look {"mode":"image","image":PATH}`, since `look mode camera` uses the window's
scene. Helpers don't survive between `execute_code` calls; keep them in a text
block and `exec(bpy.data.texts[NAME].as_string())` at the top of each call.

## AgX bleaches bright saturated emission

A yellow-to-pink emissive title face at strength 1.6 rendered as flat cream under
AgX - Punchy with bloom. At 0.75 the gradient survived. AgX rolls very bright
saturated values toward white by design. For a coloured glow, keep the coloured
surface near or below 1 and put the halo on a separate layer (a neon rim, or
bloom from a thin emissive outline).

## A text object's `offset` fills the letter holes

`offset` grows the glyph outline, so a fat outline layer behind a text object is
one line. At offset 0.05 and 0.078 on Impact at size 0.60, the outlines closed
every counter and merged neighbouring letters into blobs. Below about 6% of the
text size (0.034 and 0.050 at size 0.86) it reads as an outline. Turn off
`visible_shadow` on stacked text layers, or the back layers cast dark wedges onto
the face.

`offset` can also tear a glyph whose outline has overlapping contours: 板 in
Lantinghei SC broke at offset 0.03, and every hanzi broke at 0.08. `bevel_depth`
strokes each contour instead, so it thickens and rims without tearing (face
`bevel_depth` 0.03, rim copy 0.085, both at offset 0). A rim copy must match the
face in font, size, `space_line`, alignment and `scale`, or every glyph doubles.

## A compositor Render Layers node renders the wrong scene

A freshly created `CompositorNodeRLayers` defaults its `scene` to the window's
active scene, not the scene that owns the node tree. Building a compositor for a
scene that is not active — a `PY_*` scene alongside others — and rendering it by
name therefore composites the wrong scene, and when that scene has no render
layers the output is pure greyscale (R=G=B everywhere). Bisected with a
controlled red-emission probe: compositor off, colour; compositor on, grey. The
fix is explicit on every Render Layers node: `node.scene = sc;
node.layer = sc.view_layers[0].name`. Any compositor work in a non-active scene
must set this.

## Animating and rendering a scene that is not the active one

Three traps, all hit while animating a `PY_*` scene that sits beside others
(2026-10-09):

- A **driver expression using `frame`** resolves against the *active* scene's
  frame, not the scene that owns the driver. Every frame of a non-active scene
  then renders identically. Use fcurves keyed at the first and last frame
  instead, or drive off the owning scene explicitly.
- **`bpy.ops.render.render(scene=...)` does not evaluate that scene's
  animation.** Rendering a non-active scene ignores its frame; set
  `bpy.context.window.scene = sc` first so the scene is the one being
  evaluated. This is the same class of surprise as the compositor Render Layers
  node defaulting to the active scene.
- The **Hue/Saturation node is neutral at `0.5`, not `0`.** A cycle written as
  `frame/N` therefore starts 180 degrees from the base palette; `0.5 + frame/N`
  gives a full +360 turn that closes the loop.



## Moving an animated object does nothing at the next frame change

A keyed `location` overwrites whatever you assign as soon as the frame is
evaluated, so `o.location.x += dx` on a rig with location keys snaps back. Shift
the keys instead: for the fcurve `location[0]`, add `dx` to each key's `co.y`,
`handle_left.y` and `handle_right.y`, then call `fc.update()`. Children of the
rig follow without help. Children whose own keys are in the parent's space (steam
on a mug rig) must not be shifted as well.

## `matrix_world` is stale until the view layer updates

After changing `location`, `scale` or a parent, `o.matrix_world` (and so any
world bounding box built from `o.bound_box`) still reports the old
placement in the same script. Call `bpy.context.view_layer.update()` before
measuring. Without it, a layout script verifies against the positions it just
replaced and prints numbers that look like nothing moved.

## A child does not inherit its sibling's scale

Curves added to a head rig at the head mesh's local coordinates sat *inside* the
head, invisible, because the head mesh has object scale 1.22 and the rig does
not. Copy the target's `scale` and `location` onto the add-on, or parent it to
the mesh itself rather than to the mesh's parent.

## A pattern from face materials has jagged edges

Assigning a second material to faces by position (black hair on a white head)
makes the boundary follow the mesh's polygons, which reads as a stair-step on
a low-poly sphere. Compute a mask from the **object-space** texture coordinate
instead: normalise by the mesh half-extents, express the regions as
inequalities, and turn each one into a ramp `clamp((v - edge) * 40, 0, 1)`. The
edge is then smooth, any shape you can write as a formula (a `sin` term makes a
scalloped edge), and it moves with the object. See `scene-craft-cartoon.md`
section 4.

## A key at the last frame duplicates the seam of a loop

A loop rendered over frames 1..N whose closing key sits at N, equal to frame
1, shows that pose twice in a row on playback. Key the closing value at N+1 and
keep `frame_end` at N. A continuous rotation over the loop must use `LINEAR`
interpolation, or Bezier eases it to a stop at the seam.

## Blender loads face 0 of a font collection

`bpy.data.fonts.load()` on a `.ttc` takes its first face only. On macOS that
makes "Hiragino Sans GB.ttc" the thin W3, PingFang the HK Regular, and
Lantinghei the SC Demibold, so a bold weight inside a collection is often out of
reach. Read `font.name` after loading to see which face you got. Many CJK
fonts live under `/System/Library/AssetsV2/com_apple_MobileAsset_Font7/`, not
`/System/Library/Fonts`.
