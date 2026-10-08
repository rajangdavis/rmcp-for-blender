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
