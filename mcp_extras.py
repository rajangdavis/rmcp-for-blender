# Extra text-vision scripts for the Blender MCP server.
#
# Each constant is top-level Python that the server's run_script helper wraps
# in `def _main():` and runs inside Blender with the module-global ARGS set to
# the tool's arguments. A body reads ARGS and returns a dict; the text is under
# the key "report". A three-single-quote sequence may not appear inside a body
# (the constant regex stops at the first one), and there is no printing: the text is the return value.

WIREFRAME = r'''
import bpy

# Inputs from the MCP tool. ARGS is set on the module before _main() runs.
name = ARGS.get("name")
if not name:
    return {"report": "wireframe needs the name of a mesh object"}

views = ARGS.get("views") or ["front", "side"]
if not isinstance(views, (list, tuple)):
    views = [views]

width = ARGS.get("width") or 78
height = ARGS.get("height") or 34
if width < 40:
    width = 40
if width > 160:
    width = 160
if height < 20:
    height = 20
if height > 60:
    height = 60
cols = int(width)
rows = int(height)

o = bpy.data.objects.get(name)
if o is None or o.type != "MESH":
    return {"report": "no mesh object named " + str(name)}

me = o.data
mw = o.matrix_world
verts = [mw @ v.co for v in me.vertices]
edges = [(e.vertices[0], e.vertices[1]) for e in me.edges]
zs = [v.z for v in verts]
header = ("[wireframe v2] object " + o.name
          + " dims " + str([round(v, 3) for v in o.dimensions])
          + " faces " + str(len(me.polygons))
          + " verts " + str(len(me.vertices))
          + " edges " + str(len(me.edges))
          + " world z " + str(round(min(zs), 3)) + " " + str(round(max(zs), 3)))


def axis_pair(view):
    # One shared scale for both axes, so proportions are true.
    if view == "front":
        return (lambda v: v.x), (lambda v: v.z), "FRONT  x->right, z->up"
    if view == "side":
        return (lambda v: v.y), (lambda v: v.z), "SIDE   y->right, z->up"
    if view == "top":
        return (lambda v: v.x), (lambda v: v.y), "TOP    x->right, y->up"
    raise ValueError("unknown view '" + str(view) + "'; use front, side or top")


def draw(ax, bz, label):
    a0 = min(ax(v) for v in verts)
    a1 = max(ax(v) for v in verts)
    b0 = min(bz(v) for v in verts)
    b1 = max(bz(v) for v in verts)
    s = min((cols - 1) / ((a1 - a0) or 1.0), (rows - 1) / ((b1 - b0) or 1.0))
    ca = (cols - 1 - (a1 - a0) * s) / 2
    cb = (rows - 1 - (b1 - b0) * s) / 2
    g = [[" "] * cols for _ in range(rows)]
    for i, j in edges:
        p = verts[i]
        q = verts[j]
        n = max(2, int(max(abs(ax(p) - ax(q)), abs(bz(p) - bz(q))) * s * 2))
        for k in range(n + 1):
            t = k / n
            c = int(ca + (ax(p) * (1 - t) + ax(q) * t - a0) * s)
            r = int(cb + (bz(p) * (1 - t) + bz(q) * t - b0) * s)
            if 0 <= c < cols and 0 <= r < rows:
                g[rows - 1 - r][c] = "#"
    lines = [label]
    for row in g:
        lines.append("".join(row).rstrip())
    return "\n".join(lines)


parts = [header]
for view in views:
    ax, bz, label = axis_pair(view)
    parts.append(draw(ax, bz, label))
return {"report": "\n".join(parts)}
'''

MESH_REPORT = r'''
import bpy
import bmesh
from collections import Counter

name = ARGS.get("name")
if not name:
    return {"report": "mesh_report needs the name of a mesh object"}

o = bpy.data.objects.get(name)
if o is None or o.type != "MESH":
    return {"report": "no mesh object named " + str(name)}

me = o.data
mw = o.matrix_world
world = [mw @ v.co for v in me.vertices]
lo = [round(min(v[i] for v in world), 3) for i in range(3)]
hi = [round(max(v[i] for v in world), 3) for i in range(3)]

lines = []
lines.append("object " + o.name)
lines.append("  dims " + str([round(v, 3) for v in o.dimensions])
             + " loc " + str([round(v, 3) for v in o.location])
             + " scale " + str([round(v, 3) for v in o.scale]))
lines.append("  world bbox " + str(lo) + " " + str(hi))
lines.append("  faces " + str(len(me.polygons))
             + " verts " + str(len(me.vertices))
             + " edges " + str(len(me.edges)))
lines.append("  materials " + str([m.name for m in me.materials]))
lines.append("  modifiers " + str([m.type for m in o.modifiers]))

# Loose parts: union-find over the mesh's edges, then each part's world bounds.
bm = bmesh.new()
bm.from_mesh(me)
parent = list(range(len(bm.verts)))


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


for e in bm.edges:
    a = find(e.verts[0].index)
    b = find(e.verts[1].index)
    if a != b:
        parent[a] = b

groups = {}
for v in bm.verts:
    groups.setdefault(find(v.index), []).append(mw @ v.co)
bm.free()

lines.append("  loose parts " + str(len(groups)))
for g in sorted(groups.values(), key=lambda g: min(v.z for v in g)):
    lines.append("    z " + str(round(min(v.z for v in g), 3))
                 + " " + str(round(max(v.z for v in g), 3))
                 + "  x " + str(round(min(v.x for v in g), 3))
                 + " " + str(round(max(v.x for v in g), 3))
                 + "  y " + str(round(min(v.y for v in g), 3))
                 + " " + str(round(max(v.y for v in g), 3)))

# Face-orientation histogram: slab back vs slatted, lid vs wall.
hist = Counter()
for p in me.polygons:
    n = p.normal
    if abs(n.z) > 0.9:
        hist["horizontal"] += 1
    elif abs(n.x) > 0.9:
        hist["side"] += 1
    elif abs(n.y) > 0.9:
        hist["front_back"] += 1
    else:
        hist["angled"] += 1
lines.append("  face orientation " + str(dict(hist)))

return {"report": "\n".join(lines)}
'''
