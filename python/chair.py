# A chair from primitives: parts that meet, legs inside the seat, slatted back.
# Removes any existing Chair* objects first, then prints a self-check.
#   bash mcp.sh code python/chair.py
import bpy, bmesh

W, D, H, T = 0.46, 0.44, 0.45, 0.035     # width, depth, seat height, seat thickness
LEG, INSET = 0.045, 0.045                 # leg size, inset from the seat edge
LT = H - 0.02                             # legs run into the seat, not up to it
INS = W / 2 - INSET
POST = 0.44
SLATS = (H + 0.12, H + 0.24, H + 0.36)

for o in list(bpy.data.objects):
    if o.name.startswith("Chair"):
        bpy.data.objects.remove(o, do_unlink=True)

def box(name, size, loc):
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = (size[0], size[1], size[2])   # a size=1 cube is 1 m across
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return o

parts = [box("Chair_seat", (W, D, T), (0, 0, H - T / 2))]
for sx in (-1, 1):
    for sy in (-1, 1):
        parts.append(box(f"Chair_leg{sx}{sy}", (LEG, LEG, LT), (sx * INS, sy * INS, LT / 2)))
    parts.append(box(f"Chair_rail{sx}", (0.03, D - 2 * INSET - 0.02, 0.035), (sx * INS, 0, 0.13)))
parts.append(box("Chair_rail_back", (W - 2 * INSET - 0.02, 0.03, 0.035), (0, -INS, 0.13)))
for sx in (-1, 1):
    parts.append(box(f"Chair_post{sx}", (LEG, LEG, POST), (sx * INS, -INS, LT + POST / 2)))
for i, z in enumerate(SLATS, start=1):
    parts.append(box(f"Chair_slat{i}", (W - 2 * INSET - 0.02, 0.028, 0.06), (0, -INS, z)))

bpy.ops.object.select_all(action="DESELECT")
for o in parts:
    o.select_set(True)
bpy.context.view_layer.objects.active = parts[0]
bpy.ops.object.join()
chair = bpy.context.active_object
chair.name = "Chair"
chair.data.name = "Chair"

bev = chair.modifiers.new("Bevel", "BEVEL")
bev.width = 0.006
bev.segments = 2
bpy.ops.object.modifier_apply(modifier=bev.name)

mat = bpy.data.materials.get("ChairWood") or bpy.data.materials.new("ChairWood")
mat.use_nodes = True
principled = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
principled.inputs["Base Color"].default_value = (0.32, 0.18, 0.07, 1)
principled.inputs["Roughness"].default_value = 0.6
chair.data.materials.append(mat)

# --- self-check: nothing half size, and the tiers should overlap ---
me, mw = chair.data, chair.matrix_world
world = [mw @ v.co for v in me.vertices]
print("dims", [round(v, 3) for v in chair.dimensions], "faces", len(me.polygons),
      "world z", round(min(v.z for v in world), 3), round(max(v.z for v in world), 3))
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
          " x", round(min(v.x for v in g), 3), round(max(v.x for v in g), 3))
