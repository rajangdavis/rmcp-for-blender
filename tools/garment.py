"""Gigan: build the creature onto FinalBaseMesh, and expose the knobs.

Run inside Blender once:

    exec(open('<workspace>/tools/gigan_build.py').read())

That registers the controls and the "Gigan" panel in the 3D viewport's sidebar
(N), and builds once. After that, the panel's Rebuild button changes the shape —
and so does an agent setting scene.gigan.<knob> and calling build(). Every
measurement is asserted before anything is built, so a bad read fails loudly
rather than producing a shape that looks plausible and is wrong.
"""

import bpy, bmesh, math, json
import numpy as np

BANDS = 72


def measure(base_name="FinalBaseMesh"):
    base = bpy.data.objects.get("Gigan Body") or bpy.data.objects.get(base_name)
    assert base is not None, "no %s in this file" % base_name
    me = base.data
    n = len(me.vertices)
    co = np.empty(n * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)              # one call; the dtype must match
    co = co.reshape(n, 3)
    mw = np.array(base.matrix_world)
    world = co @ mw[:3, :3].T + mw[:3, 3]

    z = world[:, 2]
    zmin, zmax = float(z.min()), float(z.max())
    H = zmax - zmin
    assert H > 0.1, "the body has no height"

    bands = []
    for i in range(BANDS):
        lo = zmin + H * i / BANDS
        hi = zmin + H * (i + 1) / BANDS
        sel = (z >= lo) & (z < hi)
        if not sel.any():
            bands.append((lo, 0.0, 0.0))
            continue
        x = world[sel, 0]
        y = world[sel, 1]
        body = float(np.percentile(np.abs(x - np.median(x)), 75)
                     + np.percentile(np.abs(y - np.median(y)), 75))
        encl = max(float(x.max() - x.min()), float(y.max() - y.min())) / 2.0
        bands.append((lo, body, encl))

    def at(zz, k):
        return bands[max(0, min(BANDS - 1, int((zz - zmin) / H * BANDS)))][k]

    window = [b for b in bands if 0.80 * H <= b[0] - zmin <= 0.96 * H]
    neck_z = min(window, key=lambda b: b[1])[0]
    head_h = zmax - neck_z
    frac = head_h / H
    assert 0.10 <= frac <= 0.18, "head is %.3f of the height (want 0.10-0.18)" % frac

    head = z > neck_z
    hcx = float(np.median(world[head, 0]))
    hcy = float(np.median(world[head, 1]))
    head_r = float(max(np.percentile(np.abs(world[head, 0] - hcx), 85),
                       np.percentile(np.abs(world[head, 1] - hcy), 85)))
    assert 0.03 * H <= head_r <= 0.10 * H, "head radius %.3f is not a head" % head_r

    return {"zmin": zmin, "zmax": zmax, "height": H, "neck_z": neck_z, "head_h": head_h,
            "frac": frac, "head_r": head_r, "hcx": hcx, "hcy": hcy,
            "cx": float(np.median(world[:, 0])), "cy": float(np.median(world[:, 1])),
            "at": at, "bands": bands}


def build(settings=None):
    s = settings if settings is not None else bpy.context.scene.gigan
    m = measure()
    at = m["at"]

    for name in ("Gigan Robe", "Gigan Hood"):
        ob = bpy.data.objects.get(name)
        if ob is not None:
            bpy.data.objects.remove(ob, do_unlink=True)

    sh_r = at(m["neck_z"], 1) * 1.10 + 0.05
    hem_r = max(at(b[0], 2) for b in m["bands"]
                if 0.25 * m["height"] <= b[0] <= m["neck_z"]) * s.hem_scale

    mesh = bpy.data.meshes.new("Gigan Robe")
    bm = bmesh.new()
    rings = []
    for i in range(s.rings):
        zz = m["neck_z"] - (m["neck_z"] - m["zmin"]) * (i / (s.rings - 1.0))
        t = (m["neck_z"] - zz) / (m["neck_z"] - m["zmin"])
        smooth = sh_r + (hem_r - sh_r) * (t ** s.taper)
        r = max(smooth, at(zz, 2) * s.cloak_margin)
        assert r >= at(zz, 2), "the cloak cuts into the body at z=%.2f" % zz
        rings.append([bm.verts.new((m["cx"] + r * math.cos(2.0 * math.pi * k / s.segments),
                                    m["cy"] + r * math.sin(2.0 * math.pi * k / s.segments), zz))
                      for k in range(s.segments)])
    for i in range(len(rings) - 1):
        for k in range(s.segments):
            k2 = (k + 1) % s.segments
            bm.faces.new((rings[i][k], rings[i][k2], rings[i + 1][k2], rings[i + 1][k]))
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    robe = bpy.data.objects.new("Gigan Robe", mesh)
    bpy.context.scene.collection.objects.link(robe)

    hood_r = max(m["head_r"], m["head_h"] * 0.50) * s.hood_margin
    assert hood_r * 1.04 >= m["head_r"], "the hood is narrower than the head"
    hood_bottom = m["neck_z"] + m["head_h"] * s.hood_lift - hood_r * s.hood_squash
    assert hood_bottom <= m["neck_z"] + 0.25 * m["head_h"], \
        "the hood stops at z=%.2f, well above the neck at %.2f" % (hood_bottom, m["neck_z"])
    bpy.ops.mesh.primitive_uv_sphere_add(segments=36, ring_count=18, radius=hood_r,
        location=(m["hcx"], m["hcy"], m["neck_z"] + m["head_h"] * s.hood_lift))
    hood = bpy.context.active_object
    hood.name = "Gigan Hood"
    hood.scale = (1.04, 1.04, s.hood_squash)

    mat = bpy.data.materials.get("Gigan Hide")
    for o in (robe, hood):
        if len(o.data.materials) == 0:
            o.data.materials.append(mat)

    bpy.context.view_layer.update()
    s.measured = json.dumps({
        "height": round(m["height"], 2), "neck_z": round(m["neck_z"], 2),
        "head_fraction": round(m["frac"], 3), "head_r": round(m["head_r"], 2),
        "hood_r": round(hood_r, 2), "hem_r": round(hem_r, 2),
        "cloak": [round(v, 2) for v in robe.dimensions][:2],
    })
    return s.measured


def mark_stale(self, context):
    self.stale = True          # never rebuild from a property update: it would be
                               # a structural change inside a UI evaluation


class GiganSettings(bpy.types.PropertyGroup):
    hood_margin: bpy.props.FloatProperty(name="Hood size", default=1.22, min=1.0, max=2.0, update=mark_stale)
    hood_squash: bpy.props.FloatProperty(name="Hood height", default=1.18, min=0.8, max=2.0, update=mark_stale)
    hood_lift: bpy.props.FloatProperty(name="Hood lift", default=0.46, min=0.0, max=1.0, update=mark_stale)
    cloak_margin: bpy.props.FloatProperty(name="Cloak clearance", default=1.06, min=1.0, max=1.5, update=mark_stale)
    hem_scale: bpy.props.FloatProperty(name="Hem width", default=1.08, min=0.6, max=1.8, update=mark_stale)
    taper: bpy.props.FloatProperty(name="Flare", default=1.5, min=0.4, max=4.0, update=mark_stale)
    segments: bpy.props.IntProperty(name="Segments", default=44, min=12, max=96, update=mark_stale)
    rings: bpy.props.IntProperty(name="Rings", default=30, min=6, max=80, update=mark_stale)
    stale: bpy.props.BoolProperty(default=False, options={"HIDDEN"})
    measured: bpy.props.StringProperty(default="")


class GIGAN_OT_rebuild(bpy.types.Operator):
    bl_idname = "gigan.rebuild"
    bl_label = "Rebuild"
    bl_description = "Rebuild the cloak and hood from the body's own measurements"

    def execute(self, context):
        try:
            build(context.scene.gigan)
        except AssertionError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        context.scene.gigan.stale = False
        return {"FINISHED"}


class GIGAN_PT_panel(bpy.types.Panel):
    bl_label = "Gigan"
    bl_idname = "GIGAN_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Gigan"

    def draw(self, context):
        s = context.scene.gigan
        col = self.layout.column()
        for name in ("hood_margin", "hood_squash", "hood_lift", "cloak_margin",
                     "hem_scale", "taper", "segments", "rings"):
            col.prop(s, name)
        row = self.layout.row()
        row.alert = s.stale
        row.operator("gigan.rebuild", icon="FILE_REFRESH")
        if s.measured:
            box = self.layout.box()
            box.label(text="measured", icon="INFO")
            for key, value in json.loads(s.measured).items():
                box.label(text="%s: %s" % (key, value))


# The operator and panel are re-registered so an edited file takes effect at once;
# the settings group is left alone because its values live on the scene.
for cls in (GIGAN_OT_rebuild, GIGAN_PT_panel):
    try:
        bpy.utils.unregister_class(cls)
    except Exception:
        pass
for cls in (GiganSettings, GIGAN_OT_rebuild, GIGAN_PT_panel):
    try:
        bpy.utils.register_class(cls)
    except ValueError:
        pass
if not hasattr(bpy.types.Scene, "gigan"):
    bpy.types.Scene.gigan = bpy.props.PointerProperty(type=GiganSettings)

build()
print("gigan: panel registered (3D viewport sidebar, N, category Gigan); built once")
