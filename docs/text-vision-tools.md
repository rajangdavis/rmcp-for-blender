# Giving a text-only agent "sight" of a Blender scene

An MCP client delivers an `image` content block as base64. An agent reading tool
output as text cannot interpret that: a 600x381 viewport PNG is ~80 KB of
base64 for one look, and it is opaque to inspection. Worse, a *shaded* render
hides exactly what is usually wrong — you see lighting and colour, not that the
seat floats above the legs.

These are the techniques that worked while debugging a chair built from six
cubes, ordered by value. Each is cheap, deterministic, and yields text the agent
can reason about. All were run through `execute_code`; the last section proposes
them as first-class tools.

## 1. Numbers first

Before any picture, ask the object what it is. One call answers most questions:

```
faces 36  verts 48  edges 72  dims [0.4, 0.41, 0.683]  loc [0, 0, 0]  scale [1, 1, 1]
```

That line alone established: six boxes (36 faces = 6 cubes), a smaller object
than the script intended, and a transform already baked (`scale` and `loc` are
identity, so the squash is in the mesh). Nothing about a render would have said
that. Worth printing every time: dimensions, world bbox, verts/faces/edges,
materials, modifiers, location/rotation/scale.

## 2. Loose parts

Connectivity catches what proportion checks cannot: an object whose parts do not
touch, or a "chair" that is really six separate islands. Union-find over
`bmesh` edges, then per-part bounds:

```python
import bpy, bmesh
o = bpy.data.objects.get("Chair")
bm = bmesh.new(); bm.from_mesh(o.data)
parent = list(range(len(bm.verts)))
def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]; x = parent[x]
    return x
for e in bm.edges:
    a, b = find(e.verts[0].index), find(e.verts[1].index)
    if a != b:
        parent[a] = b
groups = {}
for v in bm.verts:
    groups.setdefault(find(v.index), []).append(v.co.copy())
print("loose parts", len(groups))
for vs in groups.values():
    print("  verts", len(vs), "x", round(min(v.x for v in vs),3), round(max(v.x for v in vs),3),
          "z", round(min(v.z for v in vs),3), round(max(v.z for v in vs),3))
bm.free()
```

Six parts with disjoint `z` ranges means the legs, seat and back are not joined
to each other — the bug that made the chair look wrong.

**The signature, and the trap of reading too much into it:** every part *exactly
half* its expected size, each shrunk about its own centre, leaving ~10 cm of air
between the tiers (seat 0.44 -> 0.22, legs 0.45 -> 0.225, back 0.46 -> 0.23)
while the object keeps `loc [0,0,0] scale [1,1,1]`, because the change is in the
mesh.

Two very different causes produce that signature: scaling a multi-object
selection with the pivot on **Individual Origins** (`S` then `0.5`), or a bug in
the build script. In this session it was the script —
`primitive_cube_add(size=1)` makes a 1 m cube, so `o.scale = size[0] / 2` halves
every part — and the loose-part report alone cannot tell the two apart. It tells
you *what* happened (centres unchanged, every part at half size); check the code
that built the mesh before blaming the viewport.

## 3. ASCII wireframe projection — the workhorse

Project the mesh's **edges** onto a 2D grid and print them. No lighting, no
background, no contrast problem, and true proportions if both axes share one
scale. Front (`x`,`z`) and side (`y`,`z`) are usually enough.

- normalise with a **single** scale `s = min(sa, sb)` and centre the rest, or the
  drawing lies about proportions;
- sample along each edge (`n = length * s * 2` points) so long edges are solid;
- draw `#` into `rows` x `cols`, flipping the row so +z is up.

What it produced for the broken chair:

```
FRONT  x->right, z->up                 SIDE   y->right, z->up
                                 ###########                          ##
                                 #         #                          ##
                                 ... (back panel, 13 rows)             ...
                                 ###########                          ##
                                                                  ############
                                 ###########                      ############
                                 ###########                          ##
                            ##                 ##                     ##
                            ##                 ##                     ##
```

Readable at 78x34: a back panel, a gap, the seat (2 rows thick), a gap, then two
leg bars — and the legs 21 columns wide against an 11-column seat. Two defects,
visible as text, in ~1 KB.

## 4. Face-orientation histogram

Cheap composition check: classify each polygon's normal as horizontal / side /
front-back / angled. Tells a slab back from a slatted one, or a lid from a wall,
without any geometry maths:

```python
from collections import Counter
c = Counter()
for p in o.data.polygons:
    n = p.normal
    c["horizontal" if abs(n.z) > 0.9 else "side" if abs(n.x) > 0.9 else "front_back" if abs(n.y) > 0.9 else "angled"] += 1
print(dict(c))
```

## 5. Screenshot to ASCII luminance — use sparingly

When the *shaded* look matters, the viewport PNG can be loaded back into Blender
and downsampled to characters (`numpy`, `img.pixels.foreach_get` for speed).
It worked, but it is the weakest of the techniques:

- `lum 0.247 .. 0.577` — a low-contrast render compresses to mush;
- the viewport floor's gradient dominates the frame;
- an object that fills a third of the frame occupies few characters.

Improve the odds: frame the subject first, set a flat world colour, consider
`shading.type = "WIREFRAME"`, and normalise luminance per image (min..max) with
the ramp inverted so dark geometry draws dense.

## 6. Proportion sanity checks

Numbers beat pictures for "is this a chair". A seat is 0.42-0.48 m; a back tops
out around 0.85-0.95 m; legs are inset from the seat edge, not outside it. A
`dims` line of `[0.4, 0.41, 0.683]` fails all three at once — no render needed.

## Gotchas

- **The file lifecycle bites.** `look`/`screenshot` read the PNG and then delete
  it (see `take_file_base64`), so there is nothing left to load. Use the addon's
  own `get_viewport_screenshot` with an explicit `filepath` when something else
  needs to read it.
- **Repeated `bpy.data.images.load` accumulates datablocks**; remove the image
  after reading, or reuse the name.
- **Do not hardcode enum identifiers.** `bpy.ops.object.shade_smooth_by_angle`
  moved between 4.x versions; read the operator list or skip smoothing (the
  bevel does the visual work).
- **`execute_code` error output is a JSON blob with a full traceback** — great
  for debugging, verbose for the model; expect to trim it.
- **A joined mesh keeps the active object's transform**, so "scale baked or not"
  is a real question; print `scale` and `loc` with `dims`.

## Proposed MCP tools

Two tools cover most of this, both read-only, both returning text:

- **`wireframe(name, views, width, height)`** — front/side/top/iso edge
  projections at true proportions. `views` a `:string_list` defaulting to
  `["front", "side"]`; `width`/`height` bounded (say 40-160 by 20-60).
- **`mesh_report(name)`** — dimensions, world bbox, verts/faces/edges, materials,
  modifiers, location/rotation/scale, loose-part count with per-part bounds, and
  the face-orientation histogram.

Possible third: **`silhouette(name, view, threshold)`** for the rendered look,
once the framing and contrast caveats are handled.

### Implementation, using what already exists

- Put the Python in `python/mcp_scripts.py`, a real module beside the DSL file
  with `def wireframe(args)` / `def mesh_report(args)` entry points — the shape
  every later tool in this server adopted.
- Reach them through **`run_module`**, which reads the file from disk, installs
  its text into `sys.modules` under a content hash, and calls one entry point by
  name — so a call sends a short invocation rather than the whole script, and a
  changed file installs once under a new name.
- Bodies stay thin: build the args JSON with `Json.quote` / `Json.str_list_json`,
  call `run_script(host, port, setting(:blender_extras), "WIREFRAME", args)`, and
  return the text. `read_only: true`.

### Why it matters beyond debugging

The generation tools (`generate_3d`) are the strongest case: a generated model
arrives at arbitrary scale and facing, and the agent has to decide how to orient
and size it. `mesh_report` gives the numbers (bbox, parts, orientation), and
`wireframe` shows the shape — both as text. Without them, the agent is judging a
mesh by a base64 image it cannot read.

## A drawing must keep the image's aspect

A character cell is about twice as tall as it is wide, so a grid of `COLS` x
`ROWS` does not show the image's shape unless the row count follows the aspect:

```python
ROWS = max(6, int(round(COLS * (h / float(w)) / 2.0)))
```

This is not a detail. The first version of the image report mapped a 4400x6000
image onto a fixed 116x34 grid, so every drawing came out about 1.5x too tall —
letterforms looked "funky", and a header that said `600x381` next to a grid of
116x34 was quietly describing two different pictures. Same rule as the
wireframe: one scale, or the picture lies.
