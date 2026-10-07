# Dimensions, bounds and loose parts of one mesh object.
#   bash mcp.sh code python/mesh_report.py
import bpy, bmesh

OBJECT = "Chair"

o = bpy.data.objects.get(OBJECT)
if o is None or o.type != "MESH":
    print("no mesh object named", OBJECT)
else:
    me, mw = o.data, o.matrix_world
    world = [mw @ v.co for v in me.vertices]
    lo = [round(min(v[i] for v in world), 3) for i in range(3)]
    hi = [round(max(v[i] for v in world), 3) for i in range(3)]
    print("object", o.name, "dims", [round(v, 3) for v in o.dimensions],
          "loc", [round(v, 3) for v in o.location], "scale", [round(v, 3) for v in o.scale])
    print("world bbox", lo, hi, "faces", len(me.polygons), "verts", len(me.vertices),
          "materials", [m.name for m in me.materials],
          "modifiers", [m.type for m in o.modifiers])

    bm = bmesh.new(); bm.from_mesh(me)
    parent = list(range(len(bm.verts)))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for e in bm.edges:
        a, b = find(e.verts[0].index), find(e.verts[1].index)
        if a != b:
            parent[a] = b
    groups = {}
    for v in bm.verts:
        groups.setdefault(find(v.index), []).append(mw @ v.co)
    bm.free()
    print("islands", len(groups))
    for g in sorted(groups.values(), key=lambda g: min(v.z for v in g)):
        print("  z", round(min(v.z for v in g), 3), round(max(v.z for v in g), 3),
              " x", round(min(v.x for v in g), 3), round(max(v.x for v in g), 3),
              " y", round(min(v.y for v in g), 3), round(max(v.y for v in g), 3))
