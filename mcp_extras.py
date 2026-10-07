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

IMAGE_REPORT = r'''
import bpy, numpy as np

source = ARGS.get("source") or ""
cols = max(40, min(int(ARGS.get("width") or 116), 200))
if source == "":
    return {"report": "image_report needs an image already in the file, by name, or a path to load"}

src = bpy.data.images.get(source)
loaded = src is None
if loaded:
    try:
        src = bpy.data.images.load(source)
    except Exception as e:
        return {"report": "cannot load %s: %s" % (source, e)}
img = src
ow, oh = img.size
buf = np.empty(ow * oh * 4, dtype=np.float32)
img.pixels.foreach_get(buf)
a = buf.reshape(oh, ow, 4)[::-1, :, :3]

lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
mean = [int(round(a[..., i].mean() * 255)) for i in range(3)]
q = (np.clip(a, 0, 1) * 15).astype(np.uint8).reshape(-1, 3)
keys = q[:, 0].astype(np.int32) * 256 + q[:, 1].astype(np.int32) * 16 + q[:, 2]
uniq, counts = np.unique(keys, return_counts=True)
total = float(keys.size)
palette = ["#%02x%02x%02x %2.0f%%" % ((int(uniq[i]) // 256) * 17, ((int(uniq[i]) // 16) % 16) * 17,
                                      (int(uniq[i]) % 16) * 17, 100.0 * counts[i] / total)
           for i in np.argsort(-counts)[:6]]

mx = a.max(axis=2)
mn = a.min(axis=2)
den = np.maximum(mx - mn, 1e-6)
sat = np.where(mx > 0.01, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
hue = np.where(mx == a[..., 0], ((a[..., 1] - a[..., 2]) / den) % 6,
               np.where(mx == a[..., 1], (a[..., 2] - a[..., 0]) / den + 2,
                        (a[..., 0] - a[..., 1]) / den + 4)) * 60.0

rows = max(6, int(round(cols * (oh / float(ow)) / 2.0)))   # 2:1 cell, true proportions
ys = np.linspace(0, oh, rows + 1).astype(int)
xs = np.linspace(0, ow, cols + 1).astype(int)
grid = np.zeros((rows, cols), dtype=np.float32)
for r in range(rows):
    for c in range(cols):
        cell = lum[ys[r]:ys[r + 1], xs[c]:xs[c + 1]]
        grid[r, c] = float(cell.mean()) if cell.size else 0.0
lo, hi = np.percentile(grid, 5), np.percentile(grid, 95)
span = float(hi - lo) or 1.0
tone_ramp = " .:-=+*#%@"
hue_ramp = "RYGCBM"

tone = []
hues = []
for r in range(rows):
    tline = ""
    hline = ""
    for c in range(cols):
        v = (grid[r, c] - lo) / span
        tline += tone_ramp[max(0, min(len(tone_ramp) - 1, int(v * (len(tone_ramp) - 1))))]
        cs = sat[ys[r]:ys[r + 1], xs[c]:xs[c + 1]]
        ch = hue[ys[r]:ys[r + 1], xs[c]:xs[c + 1]]
        hline += "." if (cs.size == 0 or float(cs.mean()) < 0.18) else hue_ramp[int(float(ch.mean()) // 60) % 6]
    tone.append(tline)
    hues.append(hline)

lines = ["image %s  %dx%d  aspect %.3f  mean #%02x%02x%02x  grid %dx%d"
         % (source, ow, oh, (ow / float(oh) if oh else 0), mean[0], mean[1], mean[2], cols, rows),
         "palette " + ", ".join(palette),
         "tone, dense = bright:"]
lines.extend(tone)
lines.append("hue: R red  Y yellow  G green  C cyan  B blue  M magenta  . grey or desaturated")
lines.extend(hues)

if loaded:
    bpy.data.images.remove(img)
return {"report": "\n".join(lines)}
'''

REVEAL = r'''
import bpy

# Why an object is not on screen is a property of the view and the view layer,
# not of the object. This reports both, clears the traps it finds, and frames
# the object so the next screenshot has something in it.

name = (ARGS.get("name") or "").strip()
want_frame = ARGS.get("frame")
if want_frame is None:
    want_frame = True

def window_region(area):
    for r in area.regions:
        if r.type == "WINDOW":
            return r
    return None

def override(window, area, space=None):
    over = {"window": window, "area": area}
    r = window_region(area)
    if r is not None:
        over["region"] = r
    if space is not None:
        over["space_data"] = space
    return over

def layer_collection(node, collection):
    if node.collection == collection:
        return node
    for child in node.children:
        found = layer_collection(child, collection)
        if found is not None:
            return found
    return None

scene = bpy.context.scene
view_layer = bpy.context.view_layer
windows = list(bpy.context.window_manager.windows)
views = []
for w in windows:
    for a in w.screen.areas:
        if a.type == "VIEW_3D":
            for s in a.spaces:
                if s.type == "VIEW_3D":
                    views.append((w, a, s))

lines = ["file %s" % (bpy.data.filepath or "(unsaved)"),
         "scene %s  view layer %s  windows %d  3D viewports %d  frame %d"
         % (scene.name, view_layer.name, len(windows), len(views), scene.frame_current),
         "camera %s" % (scene.camera.name if scene.camera else "(none)")]

cleared = []
for w, a, s in views:
    if s.local_view is not None:
        try:
            with bpy.context.temp_override(**override(w, a, s)):
                bpy.ops.view3d.localview()
            cleared.append("left local view")
        except Exception as e:
            cleared.append("local view would not clear (%s)" % e)
    r3d = s.region_3d
    if r3d is not None and r3d.view_perspective == "CAMERA":
        r3d.view_perspective = "PERSP"
        cleared.append("left camera view")
lines.append("view: " + (", ".join(sorted(set(cleared))) if len(cleared) > 0 else "nothing was hiding the view"))

if name == "":
    lines.append("visible objects here: %s" % (", ".join(sorted(o.name for o in view_layer.objects)[:24]) or "(none)"))
    return {"report": "\n".join(lines)}

ob = bpy.data.objects.get(name)
if ob is None:
    near = [o.name for o in bpy.data.objects if name.lower() in o.name.lower()][:8]
    lines.append("no object named %r%s" % (name, ("; nearest: " + ", ".join(near)) if len(near) > 0 else ""))
    return {"report": "\n".join(lines)}

in_layer = ob.name in view_layer.objects
changes = []
if ob.hide_viewport:
    ob.hide_viewport = False
    changes.append("hide_viewport")
hidden_state = "unknown"
try:
    if ob.hide_get():
        ob.hide_set(False)
        changes.append("hidden in this view layer")
        hidden_state = "visible (it was hidden)"
    else:
        hidden_state = "visible"
except Exception as e:
    hidden_state = "unknown (%s)" % e
if ob.hide_select:
    ob.hide_select = False
    changes.append("hide_select")
if ob.hide_render:
    ob.hide_render = False
    changes.append("hide_render")
for c in ob.users_collection:
    if c.hide_viewport:
        c.hide_viewport = False
        changes.append("collection %s hidden" % c.name)
    if c.hide_render:
        c.hide_render = False
        changes.append("collection %s hidden from renders" % c.name)
    lc = layer_collection(view_layer.layer_collection, c)
    if lc is not None:
        if lc.exclude:
            lc.exclude = False
            changes.append("collection %s excluded from this view layer" % c.name)
        if lc.hide_viewport:
            lc.hide_viewport = False
            changes.append("collection %s hidden in this view layer" % c.name)

bpy.context.view_layer.objects.active = ob
for o in list(bpy.context.selected_objects):
    o.select_set(False)
ob.select_set(True)
framed = 0
if want_frame:
    for w, a, s in views:
        try:
            with bpy.context.temp_override(**override(w, a, s)):
                bpy.ops.view3d.view_selected(use_all_regions=False)
            framed = framed + 1
        except Exception as e:
            lines.append("could not frame in one viewport (%s)" % e)

mats = []
if getattr(ob.data, "materials", None) is not None:
    mats = [m.name for m in ob.data.materials if m]
lines.append("object %s  type %s  %s  in this view layer: %s"
             % (ob.name, ob.type, hidden_state, "yes" if in_layer else "no"))
lines.append("  location (%.4f, %.4f, %.4f)  dimensions (%.4f, %.4f, %.4f)"
             % (ob.location.x, ob.location.y, ob.location.z, ob.dimensions.x, ob.dimensions.y, ob.dimensions.z))
lines.append("  collections %s  parent %s"
             % (", ".join(c.name for c in ob.users_collection) or "(none)", ob.parent.name if ob.parent else "(none)"))
lines.append("  materials %s  selected objects: %d" % (", ".join(mats) or "(none)", len(bpy.context.selected_objects)))
lines.append("changed: " + (", ".join(changes) if len(changes) > 0 else "nothing was hiding it"))
lines.append("framed in %d of %d viewports" % (framed, len(views)))
if not in_layer:
    lines.append("note: %s is not in view layer %s, so no viewport can draw it; the collections above say where it lives" % (ob.name, view_layer.name))
return {"report": "\n".join(lines)}
'''

TEXT = r'''
import bpy

# A text object is a curve, not a mesh, so wireframe and mesh_report cannot read
# it and glTF writes it as an outline. Converting to a mesh is therefore the
# useful default, and the report says which one you got.

text = ARGS.get("text") or ""
if text.strip() == "":
    return {"report": "text needs a non-empty string; the body is what gets drawn"}

name = (ARGS.get("name") or "").strip()
if name == "":
    name = (text.strip().splitlines()[0][:32] or "Text")

size = float(ARGS.get("size") or 1.0)
extrude = float(ARGS.get("extrude") or 0.0)
spacing = ARGS.get("spacing")
align = ARGS.get("align") or "CENTER"
loc = [float(ARGS.get("x") or 0.0), float(ARGS.get("y") or 0.0), float(ARGS.get("z") or 0.0)]
as_mesh = ARGS.get("as_mesh")
if as_mesh is None:
    as_mesh = True

curve = bpy.data.curves.new(name, type="FONT")
curve.body = text
curve.size = size
curve.extrude = extrude
curve.align_x = align
if spacing is not None:
    curve.space_character = float(spacing)
ob = bpy.data.objects.new(name, curve)
ob.location = loc

collection = bpy.context.scene.collection
try:
    if bpy.context.collection is not None:
        collection = bpy.context.collection
except Exception:
    pass
collection.objects.link(ob)
bpy.context.view_layer.update()

lines = ["created %s: a FONT curve, %d characters on %d line(s)" % (ob.name, len(text), text.count("\n") + 1),
         "size %.3f  extrude %.3f  align_x %s  spacing %.3f" % (size, extrude, curve.align_x, curve.space_character),
         "location (%.4f, %.4f, %.4f)  dimensions (%.4f, %.4f, %.4f)  collection %s"
         % (ob.location.x, ob.location.y, ob.location.z, ob.dimensions.x, ob.dimensions.y, ob.dimensions.z, collection.name)]

if as_mesh:
    for o in list(bpy.context.selected_objects):
        o.select_set(False)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    try:
        bpy.ops.object.convert(target="MESH")
    except Exception as e:
        lines.append("could not convert it to a mesh (%s); it is still a text object" % e)
    ob = bpy.data.objects.get(ob.name) or ob
    bpy.context.view_layer.update()
    if ob.type == "MESH":
        lines.append("converted to MESH: %d vertices, %d faces, dimensions (%.4f, %.4f, %.4f)"
                     % (len(ob.data.vertices), len(ob.data.polygons), ob.dimensions.x, ob.dimensions.y, ob.dimensions.z))
        lines.append("wireframe, mesh_report and export can read it now")
    else:
        lines.append("it is still a text object: wireframe and mesh_report need a mesh")
else:
    lines.append("left as a text object (as_mesh was false): wireframe and mesh_report need a mesh to read")
lines.append("%d objects in the scene now" % len(bpy.data.objects))
return {"report": "\n".join(lines)}
'''

PLACE = r'''
import bpy, math

# Absolute by default, so a call is idempotent; relative when asked, so a
# nudge is expressible. Only the axes given are touched, which is why an
# unset axis cannot be confused with a zero.

name = (ARGS.get("name") or "").strip()
ob = bpy.data.objects.get(name)
if ob is None:
    near = [o.name for o in bpy.data.objects if name.lower() in o.name.lower()][:8] if name != "" else []
    return {"report": "place needs the exact name of an object in the scene%s" % ("; nearest: " + ", ".join(near) if len(near) > 0 else "")}

rel = bool(ARGS.get("relative"))

def want(key):
    v = ARGS.get(key)
    if v is None:
        return None
    return float(v)

before = ["location (%.4f, %.4f, %.4f)" % (ob.location.x, ob.location.y, ob.location.z),
          "rotation (%.2f, %.2f, %.2f deg)" % tuple(math.degrees(a) for a in ob.rotation_euler),
          "scale (%.4f, %.4f, %.4f)" % (ob.scale.x, ob.scale.y, ob.scale.z)]

changed = []
mode_note = ""
if ob.rotation_mode != "XYZ":
    mode_note = "  rotation_mode was %s, set to XYZ" % ob.rotation_mode
    ob.rotation_mode = "XYZ"

loc = [want("x"), want("y"), want("z")]
if loc[0] is not None or loc[1] is not None or loc[2] is not None:
    cur = [ob.location.x, ob.location.y, ob.location.z]
    new = []
    for i in range(3):
        if loc[i] is None:
            new.append(cur[i])
        elif rel:
            new.append(cur[i] + loc[i])
        else:
            new.append(loc[i])
    ob.location = new
    changed.append("location")

rot = [want("rx"), want("ry"), want("rz")]
if rot[0] is not None or rot[1] is not None or rot[2] is not None:
    cur = [math.degrees(a) for a in ob.rotation_euler]
    new = []
    for i in range(3):
        if rot[i] is None:
            new.append(cur[i])
        elif rel:
            new.append(cur[i] + rot[i])
        else:
            new.append(rot[i])
    ob.rotation_euler = [math.radians(v) for v in new]
    changed.append("rotation")

uniform = want("scale")
if uniform is not None:
    if rel:
        ob.scale = (ob.scale.x * uniform, ob.scale.y * uniform, ob.scale.z * uniform)
    else:
        ob.scale = (uniform, uniform, uniform)
    changed.append("scale")

bpy.context.view_layer.update()

lines = ["%s  type %s%s" % (ob.name, ob.type, mode_note)]
lines.append("before: " + "; ".join(before))
lines.append("now: location (%.4f, %.4f, %.4f)  rotation (%.2f, %.2f, %.2f deg)  scale (%.4f, %.4f, %.4f)"
             % (ob.location.x, ob.location.y, ob.location.z,
                math.degrees(ob.rotation_euler.x), math.degrees(ob.rotation_euler.y), math.degrees(ob.rotation_euler.z),
                ob.scale.x, ob.scale.y, ob.scale.z))
lines.append("dimensions (%.4f, %.4f, %.4f)" % (ob.dimensions.x, ob.dimensions.y, ob.dimensions.z))
if ob.parent is not None:
    lines.append("parented to %s, so these numbers are relative to the parent, not to the world" % ob.parent.name)
if len(ob.constraints) > 0:
    lines.append("constraints %s: they can override what was set here" % ", ".join("%s (%s)" % (c.name, c.type) for c in ob.constraints))
if len(changed) > 0:
    lines.append("changed: " + ", ".join(changed) + (" relative to the old values" if rel else " to the values above (absolute)"))
else:
    lines.append("changed: nothing - pass at least one of x, y, z, rx, ry, rz, scale")
return {"report": "\n".join(lines)}
'''

MATERIAL = r'''
import bpy

# Blender keeps two colours for a material: the Principled base colour a render
# uses, and diffuse_color, the flat colour a solid viewport draws. Setting both
# is what makes look(shading="solid") show the change without a render.

NAMED_COLOURS = {"black": "#000000", "white": "#ffffff", "grey": "#808080", "gray": "#808080",
                 "red": "#d02020", "green": "#2f9e44", "blue": "#1c5fd0", "yellow": "#e8c020",
                 "orange": "#e07020", "purple": "#8038c0", "pink": "#e060a0", "brown": "#7a4f24",
                 "cyan": "#20b8c0", "magenta": "#c020a0", "wood": "#a9713f", "steel": "#8a9099",
                 "gold": "#c8a02a", "concrete": "#9a9a94", "glass": "#bcd8e0"}

def to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def parse_colour(text):
    key = text.strip().lower()
    if key in NAMED_COLOURS:
        key = NAMED_COLOURS[key]
    if key.startswith("#"):
        key = key[1:]
    if len(key) == 3:
        key = key[0] * 2 + key[1] * 2 + key[2] * 2
    if len(key) != 6:
        return None
    try:
        return [int(key[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    except ValueError:
        return None

name = (ARGS.get("name") or "").strip()
ob = bpy.data.objects.get(name)
if ob is None:
    return {"report": "material needs the exact name of an object in the scene (scene lists them)"}
data = getattr(ob, "data", None)
if data is None or not hasattr(data, "materials"):
    return {"report": "%s is a %s object and carries no materials: they hang off mesh, curve, surface or grease pencil data" % (ob.name, ob.type)}

want_material = (ARGS.get("material") or "").strip()
want_colour = (ARGS.get("colour") or "").strip()
roughness = ARGS.get("roughness")
metallic = ARGS.get("metallic")
if want_material == "" and want_colour == "" and roughness is None and metallic is None:
    held = ["%d: %s" % (i, m.name) for i, m in enumerate(data.materials) if m]
    return {"report": "%s has %d material slot(s): %s. Pass colour to set or create one, material to name an existing one, or roughness/metallic to adjust what is already there." % (ob.name, len(data.materials), ", ".join(held) if len(held) > 0 else "all empty")}

rgb = None
if want_colour != "":
    rgb = parse_colour(want_colour)
    if rgb is None:
        return {"report": "colour %r is neither #rgb nor #rrggbb nor one of: %s" % (want_colour, ", ".join(sorted(NAMED_COLOURS)))}

mat = None
created = False
if want_material != "":
    mat = bpy.data.materials.get(want_material)
    if mat is None:
        near = [m.name for m in bpy.data.materials if want_material.lower() in m.name.lower()][:8]
        return {"report": "no material named %r%s" % (want_material, ("; nearest: " + ", ".join(near)) if len(near) > 0 else "")}
else:
    held = [m for m in data.materials if m]
    if len(held) > 0:
        mat = held[0]
if mat is None:
    mat = bpy.data.materials.new("%s %s" % (ob.name, (want_colour or "material").replace("#", "")))
    created = True

held = [m for m in data.materials if m]
if mat not in held:
    empty = [i for i, m in enumerate(data.materials) if m is None]
    if len(data.materials) == 0:
        data.materials.append(mat)
    elif len(empty) > 0:
        data.materials[empty[0]] = mat
    else:
        data.materials.append(mat)

slot = 0
for i, m in enumerate(data.materials):
    if m == mat:
        slot = i
        break

principled = None
tree = mat.node_tree if (mat.use_nodes and mat.node_tree is not None) else None
if tree is not None:
    for node in tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            principled = node
            break
if principled is None and (rgb is not None or roughness is not None or metallic is not None):
    try:
        mat.use_nodes = True
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                principled = node
                break
    except Exception:
        pass

set_inputs = []
if principled is not None:
    if rgb is not None:
        lin = [to_linear(c) for c in rgb]
        try:
            principled.inputs["Base Color"].default_value = (lin[0], lin[1], lin[2], 1.0)
            set_inputs.append("base colour")
        except Exception as e:
            set_inputs.append("base colour refused (%s)" % e)
    if roughness is not None:
        try:
            principled.inputs["Roughness"].default_value = float(roughness)
            set_inputs.append("roughness %.3f" % float(roughness))
        except Exception as e:
            set_inputs.append("roughness refused (%s)" % e)
    if metallic is not None:
        try:
            principled.inputs["Metallic"].default_value = float(metallic)
            set_inputs.append("metallic %.3f" % float(metallic))
        except Exception as e:
            set_inputs.append("metallic refused (%s)" % e)

if rgb is not None:
    lin = [to_linear(c) for c in rgb]
    mat.diffuse_color = (lin[0], lin[1], lin[2], 1.0)

lines = ["%s slot %d -> %s%s" % (ob.name, slot, mat.name, " (new material)" if created else "")]
if rgb is not None:
    lines.append("colour %r = srgb (%d, %d, %d)" % (want_colour, int(round(rgb[0] * 255)), int(round(rgb[1] * 255)), int(round(rgb[2] * 255))))
lines.append("principled node %s; touched: %s" % ("found" if principled is not None else "not found", ", ".join(set_inputs) if len(set_inputs) > 0 else "nothing on the shader"))
lines.append("the viewport diffuse colour was set too, so look(shading=\"solid\") shows it without a render")
if ob.type == "MESH":
    used = {}
    for p in ob.data.polygons:
        used[p.material_index] = used.get(p.material_index, 0) + 1
    lines.append("faces by slot: %s" % (", ".join("%d: %d" % (i, used[i]) for i in sorted(used)) if len(used) > 0 else "none"))
    if len(used) > 0 and slot not in used:
        lines.append("note: no face uses slot %d, so this colour will not show on %s" % (slot, ob.name))
lines.append("materials on %s now: %s" % (ob.name, ", ".join("%d: %s" % (i, m.name if m else "(empty)") for i, m in enumerate(data.materials))))
return {"report": "\n".join(lines)}
'''

RENDER = r'''
import bpy, os, time

# Writes a real file at a real resolution, rather than the viewport grab look
# takes, so the result is something the user keeps. For an image back in the
# conversation use look(mode="camera"); for text, image_report reads this file.

scene = bpy.context.scene
want_file = (ARGS.get("file") or "").strip()
want_camera = (ARGS.get("camera") or "").strip()
width = ARGS.get("width")
height = ARGS.get("height")
samples = ARGS.get("samples")
frame = ARGS.get("frame")

base = bpy.data.filepath
folder = os.path.dirname(base) if base else ""
if folder == "" or not os.path.isdir(folder):
    home = os.path.expanduser("~")
    desktop = os.path.join(home, "Desktop")
    folder = desktop if os.path.isdir(desktop) else home
stem = os.path.splitext(os.path.basename(base))[0] if base else "scene"

if want_file == "":
    path = os.path.join(folder, "%s-render.png" % stem)
else:
    path = os.path.expanduser(want_file)
    if os.path.splitext(path)[1] == "":
        path = path + ".png"
    if not os.path.isabs(path):
        path = os.path.join(folder, path)
out_dir = os.path.dirname(path)
if out_dir != "" and not os.path.isdir(out_dir):
    try:
        os.makedirs(out_dir)
    except Exception as e:
        return {"report": "cannot create %s: %s" % (out_dir, e)}

if want_camera != "":
    cam = bpy.data.objects.get(want_camera)
    if cam is None or cam.type != "CAMERA":
        cams = [o.name for o in bpy.data.objects if o.type == "CAMERA"]
        return {"report": "no camera named %r; this file has: %s" % (want_camera, ", ".join(cams) if len(cams) > 0 else "none")}
    scene.camera = cam
if scene.camera is None:
    return {"report": "the scene has no camera to render from; add one with execute_code, bpy.ops.object.camera_add()"}

if width is not None:
    scene.render.resolution_x = int(width)
if height is not None:
    scene.render.resolution_y = int(height)
if samples is not None:
    n = int(samples)
    if scene.render.engine == "CYCLES" and hasattr(scene, "cycles"):
        scene.cycles.samples = n
    else:
        try:
            scene.eevee.taa_render_samples = n
        except Exception:
            pass
if frame is not None:
    scene.frame_set(int(frame))

was_percentage = scene.render.resolution_percentage
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = path
started = time.time()
bpy.ops.render.render(write_still=True)
seconds = time.time() - started
size = os.path.getsize(path) if os.path.isfile(path) else 0
if size == 0:
    return {"report": "the render finished but wrote nothing at %s" % path}

if scene.render.engine == "CYCLES":
    sample_note = "samples %d" % scene.cycles.samples
else:
    try:
        sample_note = "samples %d" % scene.eevee.taa_render_samples
    except Exception:
        sample_note = "samples (this engine reports none)"

lines = ["wrote %s" % path,
         "%.1f KB in %.1f s  %s  %dx%d at %d%%  frame %d  %s"
         % (size / 1024.0, seconds, scene.render.engine, scene.render.resolution_x, scene.render.resolution_y,
            scene.render.resolution_percentage, scene.frame_current, sample_note),
         "camera %s  (resolution_percentage was %d and is now 100)" % (scene.camera.name if scene.camera else "(none)", was_percentage),
         "read it back as text with image_report(source=\"%s\")" % path]
return {"report": "\n".join(lines)}
'''

EXPORT = r'''
import bpy, os

# The file lands next to the .blend, or on the Desktop for an unsaved one, so
# the report can name a path the user recognises instead of a temp file.

fmt = (ARGS.get("format") or "glb").strip().lower()
if fmt not in ("glb", "fbx"):
    return {"report": "export writes glb or fbx, not %r" % fmt}
names = ARGS.get("objects") or []
if not isinstance(names, (list, tuple)):
    names = [names]
selection_only = bool(ARGS.get("selection_only"))
mods = ARGS.get("apply_modifiers")
if mods is None:
    mods = True

wanted = []
missing = []
for n in names:
    ob = bpy.data.objects.get(str(n))
    if ob is None:
        missing.append(str(n))
    else:
        wanted.append(ob)
        try:
            wanted.extend(ob.children_recursive)
        except Exception:
            pass
if len(missing) > 0:
    return {"report": "no object named %s; export takes exact names (scene lists them)" % ", ".join(missing)}
if len(wanted) > 0:
    targets = wanted
elif selection_only:
    targets = list(bpy.context.selected_objects)
    if len(targets) == 0:
        return {"report": "selection_only was set but nothing is selected in the viewport"}
else:
    targets = [o for o in bpy.context.view_layer.objects if o.type in ("MESH", "CURVE", "SURFACE", "FONT", "META") and not o.hide_render]
if len(targets) == 0:
    return {"report": "nothing to export: this view layer has no mesh, curve, surface, font or metaball object"}

base = bpy.data.filepath
folder = os.path.dirname(base) if base else ""
if folder == "" or not os.path.isdir(folder):
    home = os.path.expanduser("~")
    desktop = os.path.join(home, "Desktop")
    folder = desktop if os.path.isdir(desktop) else home
stem = os.path.splitext(os.path.basename(base))[0] if base else "scene"
want_file = (ARGS.get("file") or "").strip()
if want_file == "":
    path = os.path.join(folder, "%s.%s" % (stem, fmt))
else:
    path = os.path.expanduser(want_file)
    if os.path.splitext(path)[1] == "":
        path = path + "." + fmt
    if not os.path.isabs(path):
        path = os.path.join(folder, path)
out_dir = os.path.dirname(path)
if out_dir != "" and not os.path.isdir(out_dir):
    try:
        os.makedirs(out_dir)
    except Exception as e:
        return {"report": "cannot create %s: %s" % (out_dir, e)}

for o in list(bpy.context.selected_objects):
    o.select_set(False)
linked = []
skipped = []
for o in targets:
    if o.name in bpy.context.view_layer.objects:
        o.select_set(True)
        linked.append(o.name)
    else:
        skipped.append(o.name)
if len(linked) == 0:
    return {"report": "none of the %d object(s) are in view layer %s, and export can only reach what is linked here" % (len(targets), bpy.context.view_layer.name)}
bpy.context.view_layer.objects.active = bpy.data.objects[linked[0]]

try:
    if fmt == "glb":
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_apply=bool(mods))
    else:
        options = {"filepath": path, "use_selection": True}
        if not mods:
            options["use_mesh_modifiers"] = False
        bpy.ops.export_scene.fbx(**options)
except Exception as e:
    return {"report": "the %s export failed: %s" % (fmt.upper(), e)}

size = os.path.getsize(path) if os.path.isfile(path) else 0
if size == 0:
    return {"report": "the export reported success but wrote nothing at %s" % path}
lines = ["wrote %s  %.2f MB  %s" % (path, size / 1048576.0, fmt.upper()),
         "%d object(s): %s" % (len(linked), ", ".join(linked)[:400]),
         "modifiers applied: %s; the viewport selection now holds the exported objects" % bool(mods)]
if len(skipped) > 0:
    lines.append("skipped, not in this view layer: %s" % ", ".join(skipped))
lines.append("glb carries materials and animation; fbx is the fallback for importers that need it")
return {"report": "\n".join(lines)}
'''
