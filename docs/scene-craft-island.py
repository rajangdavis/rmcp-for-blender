# claude-island-build.py
# Rebuilds Claude's "STATUS: REAL FUCKIN SICK" desert-island diorama from an empty scene.
# Target: Blender 4.2 LTS, EEVEE Next. Run it in Blender's Python (Text Editor > Run Script,
# or an MCP execute_code call). It builds into its OWN scene (SCN) and prefixes every
# object/material with P, so it never touches anyone else's work in the same .blend.
# Rendering is done BY SCENE NAME (bpy.ops.render.render(scene=SCN)), so the window's
# active scene is never switched.
import bpy, bmesh, math, random, os
from mathutils import Vector, Matrix, Euler

SCN    = "CLAUDE_island"                                   # scene to build into
P      = "CL_"                                             # name prefix for every datablock
OUT    = os.path.expanduser("~/Desktop/claude-island-v2.png")  # host path: only with the owner's OK
RENDER = False   # build only. Agents may not write to the host (docs/blender-sec.md); use `look`

# =====================================================================================
# 0. HELPERS
# =====================================================================================
def N(name): return P + name
def scn(): return bpy.data.scenes[SCN]
def link(ob):
    for c in list(ob.users_collection): c.objects.unlink(ob)
    scn().collection.objects.link(ob); return ob
def kill(name):
    ob = bpy.data.objects.get(name)
    if not ob: return
    data = ob.data
    bpy.data.objects.remove(ob, do_unlink=True)
    if data is not None and data.users == 0:
        if   isinstance(data, bpy.types.Mesh):   bpy.data.meshes.remove(data)
        elif isinstance(data, bpy.types.Curve):  bpy.data.curves.remove(data)
        elif isinstance(data, bpy.types.Light):  bpy.data.lights.remove(data)
        elif isinstance(data, bpy.types.Camera): bpy.data.cameras.remove(data)
def mesh_obj(name, bm, mats=None, smooth=True, parent=None):
    # bmesh -> new mesh object linked into SCN (replacing any object of that name)
    kill(name)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    if smooth:
        for p in me.polygons: p.use_smooth = True
    ob = bpy.data.objects.new(name, me); link(ob)
    if mats is not None:
        for m in (mats if isinstance(mats, (list, tuple)) else [mats]): me.materials.append(m)
    if parent: ob.parent = parent        # plain parent, identity inverse: child coords are parent-local
    return ob
def add_sphere(bm, c, r, segs=24, rings=12, scale=(1,1,1)):
    M = Matrix.Translation(Vector(c)) @ Matrix.Diagonal((r*scale[0], r*scale[1], r*scale[2], 1))
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=1.0, matrix=M)
def sweep(bm, pts, radii, step=0.012):
    # "sphere sweep": overlapping spheres every `step` metres along a polyline, radius
    # interpolated per segment. Voxel-remesh afterwards and it becomes one smooth limb.
    for i in range(len(pts)-1):
        a, b = Vector(pts[i]), Vector(pts[i+1]); ra, rb = radii[i], radii[i+1]
        n = max(2, int((b-a).length/step))
        for k in range(n+1):
            t = k/n; add_sphere(bm, a.lerp(b, t), ra+(rb-ra)*t, 16, 8)
def remesh(ob, voxel=0.01, smooth=4, factor=0.6):
    m = ob.modifiers.new("remesh", "REMESH"); m.mode = 'VOXEL'; m.voxel_size = voxel; m.use_smooth_shade = True
    if smooth:
        s = ob.modifiers.new("smooth", "SMOOTH"); s.factor = factor; s.iterations = smooth
def frame_axes(d):
    d = Vector(d).normalized(); up = Vector((0,0,1)) if abs(d.z) < 0.95 else Vector((1,0,0))
    x = d.cross(up).normalized(); y = x.cross(d).normalized(); return x, y
def tube(bm, centers, radii, ring=16, rmod=None):
    # generalized cylinder through `centers`; rmod(i, j) multiplies the radius per ring/vertex
    rings = []
    for i, c in enumerate(centers):
        c = Vector(c)
        d = Vector(centers[min(i+1, len(centers)-1)]) - Vector(centers[max(i-1, 0)])
        x, y = frame_axes(d); rr = []
        for j in range(ring):
            a = 2*math.pi*j/ring; m = rmod(i, j) if rmod else 1.0
            rr.append(bm.verts.new(c + (x*math.cos(a) + y*math.sin(a))*radii[i]*m))
        rings.append(rr)
    for i in range(len(rings)-1):
        for j in range(ring):
            bm.faces.new((rings[i][j], rings[i][(j+1)%ring], rings[i+1][(j+1)%ring], rings[i+1][j]))
    bm.faces.new(list(reversed(rings[0]))); bm.faces.new(rings[-1])
def poly_prism(bm, pts2d, thick, M):
    # 2D outline (u, v) extruded +-thick/2 along local z, then transformed by matrix M
    lo = [bm.verts.new(M @ Vector((u, v, -thick/2))) for u, v in pts2d]
    hi = [bm.verts.new(M @ Vector((u, v,  thick/2))) for u, v in pts2d]
    n = len(pts2d)
    bm.faces.new(list(reversed(lo))); bm.faces.new(hi)
    for i in range(n): bm.faces.new((lo[i], lo[(i+1)%n], hi[(i+1)%n], hi[i]))
def mat(name, color, rough=0.5, emit=None, estr=0.0, sss=0.0, spec=0.5, metal=0.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")   # by TYPE, never by name
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    for k in ("Specular IOR Level", "Specular"):
        if k in b.inputs: b.inputs[k].default_value = spec; break
    if "Subsurface Weight" in b.inputs: b.inputs["Subsurface Weight"].default_value = sss
    if emit is not None:
        b.inputs["Emission Color"].default_value = (*emit, 1); b.inputs["Emission Strength"].default_value = estr
    m.diffuse_color = (*color, 1)
    return m
def emis(name, col, strength):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    o = nt.nodes.new("ShaderNodeOutputMaterial"); e = nt.nodes.new("ShaderNodeEmission")
    e.inputs[0].default_value = (*col, 1); e.inputs[1].default_value = strength
    nt.links.new(e.outputs[0], o.inputs[0]); return m
def smoothstep(a, b, x):
    t = max(0.0, min(1.0, (x-a)/(b-a))); return t*t*(3-2*t)

# =====================================================================================
# 1. SCENE, RENDER, COLOUR MANAGEMENT
# =====================================================================================
s = bpy.data.scenes.get(SCN) or bpy.data.scenes.new(SCN)
try: s.render.engine = 'BLENDER_EEVEE_NEXT'
except TypeError as e: print("engine:", e)
s.render.resolution_x, s.render.resolution_y, s.render.resolution_percentage = 1200, 1600, 100
s.eevee.taa_render_samples = 128
for attr in ("use_shadows", "use_raytracing"):
    try: setattr(s.eevee, attr, True)
    except Exception: pass
s.view_settings.view_transform = 'AgX'
try: s.view_settings.look = 'AgX - Punchy'
except TypeError as e: print("look:", e)
s.view_settings.exposure = 0.0

# =====================================================================================
# 2. WORLD: what the CAMERA sees != what LIGHTS the scene
# =====================================================================================
w = bpy.data.worlds.get(N("world")) or bpy.data.worlds.new(N("world")); s.world = w
w.use_nodes = True; nt = w.node_tree; nt.nodes.clear(); L = nt.links.new
out = nt.nodes.new("ShaderNodeOutputWorld")
tc  = nt.nodes.new("ShaderNodeTexCoord")
sep = nt.nodes.new("ShaderNodeSeparateXYZ")
ramp = nt.nodes.new("ShaderNodeValToRGB"); cr = ramp.color_ramp; cr.interpolation = 'B_SPLINE'
stops = [(0.00, (1.00, 0.42, 0.16)),   # hot peach at the bottom of the frame
         (0.28, (1.00, 0.36, 0.30)),   # coral
         (0.55, (0.62, 0.12, 0.42)),   # magenta
         (0.82, (0.16, 0.06, 0.32)),   # violet
         (1.00, (0.04, 0.03, 0.14))]   # near-black indigo at the top
while len(cr.elements) < len(stops): cr.elements.new(0.5)
for el, (p, c) in zip(cr.elements, stops): el.position = p; el.color = (*c, 1)
bg_cam = nt.nodes.new("ShaderNodeBackground"); bg_cam.inputs[1].default_value = 1.0
sep2  = nt.nodes.new("ShaderNodeSeparateXYZ")
mapr  = nt.nodes.new("ShaderNodeMapRange"); mapr.inputs[1].default_value = -1; mapr.inputs[2].default_value = 1
ramp2 = nt.nodes.new("ShaderNodeValToRGB"); c2 = ramp2.color_ramp
c2.elements[0].position = 0.40; c2.elements[0].color = (0.90, 0.42, 0.35, 1)   # warm from the horizon
c2.elements[1].position = 0.75; c2.elements[1].color = (0.30, 0.30, 0.62, 1)   # cool from above
bg_env = nt.nodes.new("ShaderNodeBackground"); bg_env.inputs[1].default_value = 0.55
lp  = nt.nodes.new("ShaderNodeLightPath")
mix = nt.nodes.new("ShaderNodeMixShader")
L(tc.outputs["Window"], sep.inputs[0]);  L(sep.outputs["Y"], ramp.inputs[0]);  L(ramp.outputs[0], bg_cam.inputs[0])
L(tc.outputs["Generated"], sep2.inputs[0]); L(sep2.outputs["Z"], mapr.inputs[0]); L(mapr.outputs[0], ramp2.inputs[0]); L(ramp2.outputs[0], bg_env.inputs[0])
L(lp.outputs["Is Camera Ray"], mix.inputs[0]); L(bg_env.outputs[0], mix.inputs[1]); L(bg_cam.outputs[0], mix.inputs[2])
L(mix.outputs[0], out.inputs[0])

# =====================================================================================
# 3. CAMERA: true isometric, orthographic, portrait frame with headroom for the sign
# =====================================================================================
kill(N("cam"))
cd = bpy.data.cameras.new(N("cam")); cd.type = 'ORTHO'; cd.ortho_scale = 7.2; cd.clip_end = 100
cam = bpy.data.objects.new(N("cam"), cd); link(cam)
cam.rotation_euler = (math.radians(54.736), 0, math.radians(45))      # atan(sqrt(2)) tilt, 45 deg spin
R = cam.rotation_euler.to_matrix()
fwd, up, right = R @ Vector((0,0,-1)), R @ Vector((0,1,0)), R @ Vector((1,0,0))
BASE = Vector((0, 0, 0.95))                                            # what the diorama is centred on
cam.location = BASE + up*0.9 - fwd*20                                  # shift frame up 0.9 for the sign
s.camera = cam

# =====================================================================================
# 4. LIGHTS: one low warm sun from behind (rim), one cool soft fill from the camera side
# =====================================================================================
kill(N("sun"))
ld = bpy.data.lights.new(N("sun"), "SUN"); ld.energy = 4.0; ld.color = (1.0, 0.62, 0.36); ld.angle = math.radians(3)
sun = bpy.data.objects.new(N("sun"), ld); link(sun)
az, el = math.radians(160), math.radians(18)
src = Vector((math.cos(az)*math.cos(el), math.sin(az)*math.cos(el), math.sin(el)))  # direction TO the sun
sun.rotation_euler = (-src).to_track_quat('-Z', 'Y').to_euler()                     # light travels along -Z
kill(N("fill"))
fd = bpy.data.lights.new(N("fill"), "SUN"); fd.energy = 1.4; fd.color = (0.55, 0.62, 1.0); fd.angle = math.radians(20)
fill = bpy.data.objects.new(N("fill"), fd); link(fill)
fill.rotation_euler = (-Vector((1, -1, 1.2)).normalized()).to_track_quat('-Z', 'Y').to_euler()

# =====================================================================================
# 5. COMPOSITOR BLOOM (EEVEE Next has no built-in bloom any more)
# =====================================================================================
s.use_nodes = True; ct = s.node_tree; ct.nodes.clear()
rl = ct.nodes.new("CompositorNodeRLayers"); rl.scene = s
gl = ct.nodes.new("CompositorNodeGlare")
for t in ("BLOOM", "FOG_GLOW"):
    try: gl.glare_type = t; break
    except TypeError: pass
gl.threshold = 1.2; gl.quality = 'HIGH'
try: gl.size = 6
except Exception: pass
co = ct.nodes.new("CompositorNodeComposite")
ct.links.new(rl.outputs["Image"], gl.inputs["Image"]); ct.links.new(gl.outputs["Image"], co.inputs["Image"])

# =====================================================================================
# 6. WATER BLOCK: one mesh = displaced top grid + vertical skirt; foam as a vertex attribute
# =====================================================================================
random.seed(7)
HALF, NG, DEPTH = 2.3, 116, -1.4
def R_island(th): return 1.22*(1 + 0.07*math.sin(3*th+0.4) + 0.045*math.sin(5*th+1.7) + 0.025*math.sin(9*th))
def water_h(x, y):
    r = math.hypot(x, y)
    h  = 0.035*math.sin(3.1*x + 1.3*y) + 0.025*math.sin(-1.7*x + 3.9*y + 1.1) + 0.015*math.sin(6.3*x - 5.1*y)
    h += 0.06*math.exp(-((r-1.75)**2)/0.08)          # a swell ring piling up toward the island
    return h
def noise2(x, y): return 0.5 + 0.25*math.sin(11*x + 3*math.sin(7*y)) + 0.25*math.sin(13*y + 2.7*math.sin(9*x))
bm = bmesh.new(); foam_l = bm.verts.layers.float.new("foam")
grid = [[None]*(NG+1) for _ in range(NG+1)]
for i in range(NG+1):
    for j in range(NG+1):
        x = -HALF + 2*HALF*i/NG; y = -HALF + 2*HALF*j/NG
        v = bm.verts.new((x, y, water_h(x, y)))
        r = math.hypot(x, y); th = math.atan2(y, x); d = r - R_island(th)
        f = smoothstep(0.30, 0.0, abs(d-0.05)) * (0.6 + 0.5*noise2(x, y))                       # shore foam
        streak = smoothstep(0.80, 0.98, noise2(x*0.5+3, y*0.9-2)) * 0.45 * smoothstep(1.4, 2.1, r)  # sparse sea streaks
        v[foam_l] = min(1.0, max(f, streak)); grid[i][j] = v
for i in range(NG):
    for j in range(NG):
        bm.faces.new((grid[i][j], grid[i+1][j], grid[i+1][j+1], grid[i][j+1])).material_index = 0
edge = ([grid[i][0] for i in range(NG+1)] + [grid[NG][j] for j in range(1, NG+1)] +
        [grid[i][NG] for i in range(NG-1, -1, -1)] + [grid[0][j] for j in range(NG-1, 0, -1)])
bot = [bm.verts.new((v.co.x, v.co.y, DEPTH)) for v in edge]
for v in bot: v[foam_l] = 0.0
for k in range(len(edge)):
    a, b = edge[k], edge[(k+1) % len(edge)]; c, d = bot[(k+1) % len(edge)], bot[k]
    try: bm.faces.new((b, a, d, c)).material_index = 1
    except ValueError: pass
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
# top material: dark glossy teal, mixed to white by the "foam" attribute
mw = mat(N("water"), (0.012, 0.20, 0.24), rough=0.06, spec=0.6)
wt = mw.node_tree; wb = next(x for x in wt.nodes if x.type == "BSDF_PRINCIPLED")
at = wt.nodes.new("ShaderNodeAttribute"); at.attribute_name = "foam"
fb = wt.nodes.new("ShaderNodeBsdfPrincipled"); fb.inputs["Base Color"].default_value = (0.92, 0.96, 0.97, 1); fb.inputs["Roughness"].default_value = 0.7
if "Subsurface Weight" in fb.inputs: fb.inputs["Subsurface Weight"].default_value = 0.2
wo = next(x for x in wt.nodes if x.type == "OUTPUT_MATERIAL"); wm = wt.nodes.new("ShaderNodeMixShader")
wt.links.new(at.outputs["Fac"], wm.inputs[0]); wt.links.new(wb.outputs[0], wm.inputs[1]); wt.links.new(fb.outputs[0], wm.inputs[2]); wt.links.new(wm.outputs[0], wo.inputs[0])
# side material: the cut-away cross-section, coloured by object-space Z
ms = bpy.data.materials.get(N("water_side")) or bpy.data.materials.new(N("water_side")); ms.use_nodes = True
st = ms.node_tree; st.nodes.clear()
so = st.nodes.new("ShaderNodeOutputMaterial"); stc = st.nodes.new("ShaderNodeTexCoord"); ssp = st.nodes.new("ShaderNodeSeparateXYZ")
smr = st.nodes.new("ShaderNodeMapRange"); smr.inputs[1].default_value = DEPTH; smr.inputs[2].default_value = 0.05
srp = st.nodes.new("ShaderNodeValToRGB"); se = srp.color_ramp.elements
se[0].position = 0.0; se[0].color = (0.55, 0.38, 0.22, 1)                  # sea-floor sand
srp.color_ramp.elements.new(0.13).color = (0.42, 0.28, 0.16, 1)           # darker sand
srp.color_ramp.elements.new(0.16).color = (0.01, 0.03, 0.09, 1)           # hard cut to deep navy
se[-1].position = 1.0; se[-1].color = (0.03, 0.42, 0.45, 1)               # bright teal at the surface
sbs = st.nodes.new("ShaderNodeBsdfPrincipled"); sbs.inputs["Roughness"].default_value = 0.15
sem = st.nodes.new("ShaderNodeEmission"); sem.inputs[1].default_value = 0.35  # cross-section glows a little
sad = st.nodes.new("ShaderNodeAddShader")
st.links.new(stc.outputs["Object"], ssp.inputs[0]); st.links.new(ssp.outputs["Z"], smr.inputs[0]); st.links.new(smr.outputs[0], srp.inputs[0])
st.links.new(srp.outputs[0], sbs.inputs["Base Color"]); st.links.new(srp.outputs[0], sem.inputs[0])
st.links.new(sbs.outputs[0], sad.inputs[0]); st.links.new(sem.outputs[0], sad.inputs[1]); st.links.new(sad.outputs[0], so.inputs[0])
mesh_obj(N("water"), bm, [mw, ms])

# =====================================================================================
# 7. ISLAND: flattened dome on a wobbly shoreline; wet sand darkening near the waterline
# =====================================================================================
bm = bmesh.new(); RS, RR = 72, 22
top = bm.verts.new((0, 0, 0.30)); rows = []
for k in range(1, RR+1):
    t = k/RR; ring = []
    for j in range(RS):
        th = 2*math.pi*j/RS; r = R_island(th)*t
        x, y = r*math.cos(th), r*math.sin(th)
        z = 0.30*(1 - t**2.6) - 0.35*smoothstep(0.85, 1.0, t) + 0.025*math.sin(2.3*x+1.0)*math.sin(1.9*y+0.5)*(1-t)
        ring.append(bm.verts.new((x, y, z)))
    rows.append(ring)
for j in range(RS): bm.faces.new((top, rows[0][j], rows[0][(j+1) % RS]))
for k in range(RR-1):
    for j in range(RS): bm.faces.new((rows[k][j], rows[k+1][j], rows[k+1][(j+1) % RS], rows[k][(j+1) % RS]))
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
msand = mat(N("sand"), (0.80, 0.58, 0.36), rough=0.95, spec=0.1)
snt = msand.node_tree; sb = next(x for x in snt.nodes if x.type == "BSDF_PRINCIPLED")
t2 = snt.nodes.new("ShaderNodeTexCoord"); s2 = snt.nodes.new("ShaderNodeSeparateXYZ")
m2 = snt.nodes.new("ShaderNodeMapRange"); m2.inputs[1].default_value = 0.0; m2.inputs[2].default_value = 0.09
mc = snt.nodes.new("ShaderNodeMix"); mc.data_type = 'RGBA'
mc.inputs[6].default_value = (0.38, 0.24, 0.14, 1); mc.inputs[7].default_value = (0.80, 0.58, 0.36, 1)
snt.links.new(t2.outputs["Object"], s2.inputs[0]); snt.links.new(s2.outputs["Z"], m2.inputs[0]); snt.links.new(m2.outputs[0], mc.inputs[0]); snt.links.new(mc.outputs[2], sb.inputs["Base Color"])
mesh_obj(N("island"), bm, msand)
bm = bmesh.new()
for th, rr, sc in [(0.6,1.18,0.10),(0.75,1.25,0.06),(2.9,1.15,0.09),(4.3,1.2,0.07),(4.4,1.1,0.05),(5.6,1.22,0.08)]:
    Rr = R_island(th)*rr/1.2
    M = (Matrix.Translation((Rr*math.cos(th), Rr*math.sin(th), 0.0)) @
         Euler((random.random(), random.random(), random.random())).to_matrix().to_4x4() @ Matrix.Diagonal((sc*1.3, sc, sc*0.8, 1)))
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0, matrix=M)
mesh_obj(N("rocks"), bm, mat(N("rock"), (0.16, 0.13, 0.12), rough=0.8), smooth=False)

# =====================================================================================
# 8. THE GUY. Local frame: front = -Y, his LEFT = +X, feet at z=0. Actor empty turns him 45 deg
#    so -Y points at the iso camera, and scales him to 1.4 (about 1.37 m tall).
# =====================================================================================
V = Vector
kill(N("actor"))
act = bpy.data.objects.new(N("actor"), None); link(act)
act.location = (0.05, -0.05, 0.285); act.rotation_euler = (0, 0, math.radians(45)); act.scale = (1.4, 1.4, 1.4)
# guitar frame G: u along the neck (28 deg up toward his left), v toward his head, n = u x v = -Y (front)
a = math.radians(28)
u = V((math.cos(a), 0, math.sin(a))); vv = V((-math.sin(a), 0, math.cos(a))); n = u.cross(vv)
J = V((0.0, -0.118, 0.50))                                     # neck joint, just in front of the belly
G = Matrix(((u.x, vv.x, n.x, J.x), (u.y, vv.y, n.y, J.y), (u.z, vv.z, n.z, J.z), (0, 0, 0, 1)))
def gp(uu, v_, ww=0.0): return G @ V((uu, v_, ww))
# skin
bm = bmesh.new()
for sd in (1, -1):
    sweep(bm, [(sd*0.065, 0, 0.38), (sd*0.085, -0.012, 0.20), (sd*0.105, 0, 0.045)], [0.058, 0.042, 0.031])  # hip-knee-ankle
    sweep(bm, [(sd*0.105, 0, 0.03), (sd*0.115, -0.075, 0.018)], [0.03, 0.024])                               # foot
add_sphere(bm, (0, 0, 0.40), 0.10, scale=(1.15, 0.85, 0.8))           # pelvis
add_sphere(bm, (0, -0.012, 0.48), 0.10, scale=(1.05, 0.95, 1.0))      # belly
add_sphere(bm, (0, 0, 0.595), 0.115, scale=(1.22, 0.85, 0.92))        # chest
sweep(bm, [(-0.135, 0, 0.655), (0.135, 0, 0.655)], [0.05, 0.05])      # shoulder bar
sweep(bm, [(0, 0, 0.66), (0, -0.005, 0.77)], [0.047, 0.045])          # neck
add_sphere(bm, (0, 0, 0.865), 0.12, 32, 16, scale=(0.95, 1.0, 1.06))  # head
add_sphere(bm, (0, -0.119, 0.853), 0.022)                             # nose
for sd in (1, -1): add_sphere(bm, (sd*0.113, 0, 0.862), 0.026, scale=(0.6, 1, 1.2))   # ears
RH = gp(-0.10, 0.02, 0.045)                                           # strumming hand: over the body, in front
sweep(bm, [(-0.145, 0, 0.655), (-0.215, -0.05, 0.51), RH + V((0, 0, 0.015))], [0.042, 0.034, 0.028])
add_sphere(bm, RH, 0.036, scale=(1.1, 0.8, 0.9))
LH = gp(0.235, -0.005, -0.03)                                         # fretting hand: on the neck, just behind it
sweep(bm, [(0.145, 0, 0.655), (0.255, -0.035, 0.55), LH], [0.042, 0.034, 0.028])
add_sphere(bm, LH, 0.035, scale=(1.0, 0.9, 1.1))
ob = mesh_obj(N("skin"), bm, mat(N("skin_m"), (0.50, 0.30, 0.19), rough=0.55, sss=0.12), parent=act); remesh(ob, 0.007, 3)
# swim trunks: slightly fatter shell over pelvis and upper thighs
bm = bmesh.new()
add_sphere(bm, (0, 0, 0.395), 0.112, scale=(1.15, 0.9, 0.72))
for sd in (1, -1): sweep(bm, [(sd*0.066, 0, 0.38), (sd*0.074, -0.006, 0.29)], [0.068, 0.062])
ob = mesh_obj(N("trunks"), bm, mat(N("trunks_m"), (1.0, 0.33, 0.04), rough=0.6), parent=act); remesh(ob, 0.007, 2)
# beard: jaw-line sweep + chin mass + hanging tip + mustache
bm = bmesh.new()
sweep(bm, [(-0.10,-0.035,0.835), (-0.075,-0.09,0.79), (0,-0.118,0.765), (0.075,-0.09,0.79), (0.10,-0.035,0.835)], [0.036,0.042,0.048,0.042,0.036])
add_sphere(bm, (0, -0.105, 0.735), 0.055, scale=(1.1, 0.9, 1.0))
add_sphere(bm, (0, -0.095, 0.695), 0.038)
sweep(bm, [(-0.045,-0.124,0.826), (0,-0.132,0.832), (0.045,-0.124,0.826)], [0.014, 0.016, 0.014])
ob = mesh_obj(N("beard"), bm, mat(N("beard_m"), (0.075, 0.032, 0.016), rough=0.85), parent=act); remesh(ob, 0.008, 2)
# hair: a cap pushed back (+Y) so the face stays clear, plus 14 random curls (none low on the face)
random.seed(3)
bm = bmesh.new()
add_sphere(bm, (0, 0.03, 0.925), 0.122, scale=(1.04, 1.0, 0.75))
add_sphere(bm, (0, 0.075, 0.86), 0.10, scale=(1.05, 0.8, 1.0))
for k in range(14):
    th = random.uniform(0, 2*math.pi); ph = random.uniform(0.2, 1.1)
    c = V((0, 0.03, 0.90)) + V((math.cos(th)*math.sin(ph)*0.12, abs(math.sin(th))*math.sin(ph)*0.10, math.cos(ph)*0.10))
    if c.y < -0.06 and c.z < 0.95: continue
    add_sphere(bm, c, random.uniform(0.03, 0.05))
ob = mesh_obj(N("hair"), bm, mat(N("hair_m"), (0.16, 0.085, 0.04), rough=0.8), parent=act); remesh(ob, 0.009, 2)
bm = bmesh.new()
for sd in (1, -1): add_sphere(bm, (sd*0.042, -0.104, 0.878), 0.013)
mesh_obj(N("eyes"), bm, mat(N("eye_m"), (0.01, 0.008, 0.006), rough=0.2), parent=act)

# =====================================================================================
# 9. THE BC RICH MOCKINGBIRD, drawn in G-space (u = along neck, v = toward his head)
# =====================================================================================
body = [(0.0,0.032),(0.035,0.05),(0.095,0.072),(0.13,0.078),(0.115,0.098),(0.06,0.118),(-0.02,0.125),(-0.08,0.112),
        (-0.115,0.085),(-0.15,0.098),(-0.20,0.12),(-0.26,0.11),(-0.30,0.075),(-0.315,0.02),(-0.30,-0.04),(-0.25,-0.09),
        (-0.18,-0.115),(-0.115,-0.105),(-0.075,-0.08),(-0.04,-0.098),(0.0,-0.10),(0.045,-0.075),(0.02,-0.05),(0.0,-0.032)]
mg = mat(N("guitar_m"), (0.012, 0.012, 0.014), rough=0.18, spec=0.8)
bm = bmesh.new(); poly_prism(bm, body, 0.045, G)
ob = mesh_obj(N("gbody"), bm, mg, smooth=False, parent=act)
bv = ob.modifiers.new("bevel", "BEVEL"); bv.width = 0.008; bv.segments = 3; bv.limit_method = 'ANGLE'
pg = [(-0.02,0.04),(0.05,0.065),(0.04,0.09),(-0.03,0.10),(-0.09,0.085),(-0.12,0.05),(-0.10,0.02),(-0.05,0.025)]
bm = bmesh.new(); poly_prism(bm, pg, 0.004, G @ Matrix.Translation((0, 0, 0.0245)))
mesh_obj(N("gpick"), bm, mat(N("pick_m"), (0.85, 0.80, 0.68), rough=0.4), smooth=False, parent=act)
bm = bmesh.new()
for uc in (-0.06, -0.15):   # two pickups
    poly_prism(bm, [(uc-0.012,-0.04),(uc+0.012,-0.04),(uc+0.012,0.04),(uc-0.012,0.04)], 0.01, G @ Matrix.Translation((0, 0, 0.026)))
poly_prism(bm, [(-0.215,-0.03),(-0.2,-0.03),(-0.2,0.03),(-0.215,0.03)], 0.01, G @ Matrix.Translation((0, 0, 0.026)))   # bridge
mesh_obj(N("ghw"), bm, mat(N("chrome"), (0.8, 0.8, 0.82), rough=0.2, metal=1.0), smooth=False, parent=act)
bm = bmesh.new(); poly_prism(bm, [(0.0,-0.02),(0.31,-0.017),(0.31,0.017),(0.0,0.02)], 0.026, G @ Matrix.Translation((0, 0, 0.004)))
mesh_obj(N("gneck"), bm, mat(N("neck_m"), (0.20, 0.09, 0.035), rough=0.5), smooth=False, parent=act)
bm = bmesh.new(); poly_prism(bm, [(0.305,-0.02),(0.36,-0.035),(0.405,0.005),(0.39,0.03),(0.305,0.022)], 0.022, G @ Matrix.Translation((0, 0, 0.004)))
mesh_obj(N("ghead"), bm, mg, smooth=False, parent=act)
bm = bmesh.new()
strap = [gp(-0.31, 0.0, -0.01), V((-0.15,0.06,0.42)), V((-0.02,0.11,0.57)), V((0.09,0.07,0.70)), V((0.13,-0.04,0.69)), gp(0.11, 0.09, -0.01)]
tube(bm, strap, [0.009]*len(strap), ring=8)
mesh_obj(N("strap"), bm, mat(N("strap_m"), (0.03, 0.03, 0.035), rough=0.7), parent=act)

# =====================================================================================
# 10. CRASHING BREAKERS: a closed curl profile swept around arcs of the island
# =====================================================================================
PROF  = [(0.75,0.0),(0.45,0.10),(0.25,0.24),(0.10,0.40),(0.0,0.50),(-0.10,0.53),(-0.20,0.48),(-0.27,0.38),(-0.25,0.29),
         (-0.18,0.34),(-0.11,0.37),(-0.05,0.32),(-0.03,0.20),(-0.07,0.06),(-0.15,0.0)]   # (outward dr, z); lip at index 8
FOAMW = [0,0,0.05,0.35,0.75,1,1,1,1,0.85,0.55,0.25,0.05,0,0]                              # whiteness per profile point
mb = bpy.data.materials.get(N("breaker_m")) or bpy.data.materials.new(N("breaker_m")); mb.use_nodes = True
bt = mb.node_tree; bt.nodes.clear(); L = bt.links.new
bo = bt.nodes.new("ShaderNodeOutputMaterial")
ba = bt.nodes.new("ShaderNodeAttribute"); ba.attribute_name = "foam"
bw = bt.nodes.new("ShaderNodeBsdfPrincipled"); bw.inputs["Base Color"].default_value = (0.03, 0.42, 0.44, 1); bw.inputs["Roughness"].default_value = 0.12
bwe = bt.nodes.new("ShaderNodeEmission"); bwe.inputs[0].default_value = (0.05, 0.55, 0.55, 1); bwe.inputs[1].default_value = 0.45
bwa = bt.nodes.new("ShaderNodeAddShader")
bf = bt.nodes.new("ShaderNodeBsdfPrincipled"); bf.inputs["Base Color"].default_value = (0.95, 0.98, 1, 1); bf.inputs["Roughness"].default_value = 0.6
bfe = bt.nodes.new("ShaderNodeEmission"); bfe.inputs[0].default_value = (0.9, 0.97, 1, 1); bfe.inputs[1].default_value = 0.3
bfa = bt.nodes.new("ShaderNodeAddShader")
bmx = bt.nodes.new("ShaderNodeMixShader")
bmr = bt.nodes.new("ShaderNodeMapRange"); bmr.inputs[1].default_value = 0.35; bmr.inputs[2].default_value = 0.65
L(bw.outputs[0], bwa.inputs[0]); L(bwe.outputs[0], bwa.inputs[1]); L(bf.outputs[0], bfa.inputs[0]); L(bfe.outputs[0], bfa.inputs[1])
L(ba.outputs["Fac"], bmr.inputs[0]); L(bmr.outputs[0], bmx.inputs[0]); L(bwa.outputs[0], bmx.inputs[1]); L(bfa.outputs[0], bmx.inputs[2]); L(bmx.outputs[0], bo.inputs[0])
def amp_at(t, amp, th0): return amp*(math.sin(math.pi*t)**0.6)*(1 + 0.12*math.sin(9*t + th0))
def breaker(name, th0, th1, r0, amp, segs=60):
    bm = bmesh.new(); fl = bm.verts.layers.float.new("foam"); rings = []
    for i in range(segs+1):
        t = i/segs; th = th0 + (th1-th0)*t; A = amp_at(t, amp, th0); ring = []
        for (dr, z), fw in zip(PROF, FOAMW):
            r = r0 + dr*A/0.5*0.9
            v = bm.verts.new((r*math.cos(th), r*math.sin(th), z*A/0.5 - 0.01)); v[fl] = fw*min(1, A/amp*1.3); ring.append(v)
        rings.append(ring)
    m = len(PROF)
    for i in range(segs):
        for j in range(m): bm.faces.new((rings[i][j], rings[i][(j+1)%m], rings[i+1][(j+1)%m], rings[i+1][j]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return mesh_obj(name, bm, mb)
BR = [(math.radians(65),  math.radians(160), 1.62, 0.50),
      (math.radians(185), math.radians(285), 1.66, 0.46),
      (math.radians(305), math.radians(395), 1.60, 0.52)]
for k, (a0, a1, r0, amp) in enumerate(BR): breaker(N("breaker%d" % k), a0, a1, r0, amp)

# =====================================================================================
# 11. WHITEWATER: plumes where the lips slam the shore + froth along every lip + spray
# =====================================================================================
random.seed(11)
mww = mat(N("whitewater"), (0.93, 0.97, 1.0), rough=0.55, sss=0.35, emit=(0.85, 0.95, 1.0), estr=0.35)
plumes = [(a0 + (a1-a0)*f, r0, amp) for (a0, a1, r0, amp) in BR for f in (0.33, 0.68)]
wbm = bmesh.new()
for th, r0, amp in plumes:
    base = V(((r0-0.28)*math.cos(th), (r0-0.28)*math.sin(th), 0.25))
    radial = V((math.cos(th), math.sin(th), 0)); tang = V((-math.sin(th), math.cos(th), 0))
    H = random.uniform(0.75, 1.05)
    for k in range(38):
        q = random.random()**0.85; z = q*H; spread = 0.06 + 0.32*q          # widens as it rises
        c = base + tang*random.gauss(0, spread*0.8) + radial*(random.gauss(0, spread*0.5) - 0.12*q) + V((0, 0, z))
        add_sphere(wbm, c, random.uniform(0.045, 0.10)*(1 - 0.55*q) + 0.02, 16, 8)
sbm = bmesh.new()
for th, r0, amp in plumes:
    for k in range(22):
        q = random.random(); rr = r0 - 0.25 + random.uniform(-0.05, 0.5)*q; aa = th + random.gauss(0, 0.13)
        c = V((rr*math.cos(aa), rr*math.sin(aa), 0.35 + q*random.uniform(0.6, 1.05)))
        bmesh.ops.create_icosphere(sbm, subdivisions=2, radius=random.uniform(0.008, 0.028)*(1.2 - 0.6*q), matrix=Matrix.Translation(c))
mesh_obj(N("spray"), sbm, mww)
random.seed(21)
for (a0, a1, r0, amp) in BR:
    for i in range(70):
        t = random.uniform(0.08, 0.92); th = a0 + (a1-a0)*t; A = amp_at(t, amp, a0)
        dr, z = PROF[random.randint(4, 8)]                                   # somewhere on the crest/lip
        r = r0 + dr*A/0.5*0.9
        c = V((r*math.cos(th), r*math.sin(th), z*A/0.5)) + V((random.gauss(0, 0.02), random.gauss(0, 0.02), random.gauss(0, 0.02)))
        add_sphere(wbm, c, random.uniform(0.025, 0.05)*A/amp + 0.01, 12, 6)
ob = mesh_obj(N("whitewater"), wbm, mww); remesh(ob, 0.026, 6, 0.8)

# =====================================================================================
# 12. PALM: ringed tube trunk leaning away from him + 8 serrated V-folded fronds + coconuts
# =====================================================================================
random.seed(5)
left_g = V((-right.x, -right.y, 0)).normalized(); back_g = V((-0.70710678, 0.70710678, 0))
base = left_g*0.60 + back_g*0.30; base.z = 0.18
lean = (left_g*0.8 + back_g*0.2).normalized(); H, NT = 2.05, 28
cent = [base + lean*(0.55*(i/NT)**1.7) + V((0, 0, H*i/NT)) + back_g*(0.06*math.sin(math.pi*i/NT)) for i in range(NT+1)]
rad = [0.078 - 0.03*i/NT for i in range(NT+1)]
bm = bmesh.new(); tube(bm, cent, rad, ring=14, rmod=lambda i, j: 1.0 + 0.13*(i % 2))   # alternate rings = bark bands
mesh_obj(N("palm_trunk"), bm, mat(N("bark"), (0.24, 0.15, 0.08), rough=0.85))
top = cent[-1]; bmA, bmB = bmesh.new(), bmesh.new()
for k in range(8):
    az = 2*math.pi*k/8 + random.uniform(-0.15, 0.15)
    hd = V((math.cos(az), math.sin(az), 0)); side = V((-math.sin(az), math.cos(az), 0))
    Lf = random.uniform(0.85, 1.05); e0 = math.radians(random.uniform(25, 45)); drop = math.radians(random.uniform(95, 125))
    p = top.copy(); pts = [p.copy()]; S = 18
    for i in range(1, S+1):
        e = e0 - drop*(i/S)**1.3                                             # pitch arcs from up to down
        p = p + (hd*math.cos(e) + V((0, 0, math.sin(e))))*(Lf/S); pts.append(p.copy())
    tb = bmA if k % 2 == 0 else bmB; rows = []
    for i, p in enumerate(pts):
        s_ = i/S
        wdt = 0.17*math.sin(math.pi*min(1, s_**0.7))*(0.55 + 0.45*abs(math.sin(s_*38))) + 0.004   # serrated leaflets
        d = (pts[min(i+1, S)] - pts[max(i-1, 0)]).normalized(); nrm = d.cross(side).normalized()
        if nrm.z < 0: nrm = -nrm
        rows.append([tb.verts.new(p + side*wdt - nrm*0.03*wdt/0.17), tb.verts.new(p + nrm*0.012), tb.verts.new(p - side*wdt - nrm*0.03*wdt/0.17)])
    for i in range(S):
        for j in range(2): tb.faces.new((rows[i][j], rows[i][j+1], rows[i+1][j+1], rows[i+1][j]))
mesh_obj(N("fronds_a"), bmA, mat(N("frond_a"), (0.07, 0.26, 0.045), rough=0.6, sss=0.1))
mesh_obj(N("fronds_b"), bmB, mat(N("frond_b"), (0.13, 0.34, 0.06), rough=0.6, sss=0.1))
bm = bmesh.new()
for k in range(3):
    aa = 2*math.pi*k/3 + 0.4; add_sphere(bm, top + V((math.cos(aa)*0.06, math.sin(aa)*0.06, -0.07)), 0.05)
mesh_obj(N("coconuts"), bm, mat(N("coco"), (0.12, 0.07, 0.03), rough=0.7))

# =====================================================================================
# 13. SUN DISC: low in the backdrop, half hidden by the block's edge -> rising or setting?
# =====================================================================================
bm = bmesh.new(); bmesh.ops.create_circle(bm, cap_ends=True, segments=64, radius=0.75)
sd_ob = mesh_obj(N("sundisc"), bm, emis(N("sun_m"), (1.0, 0.55, 0.22), 3.0), smooth=False)
sd_ob.rotation_euler = cam.rotation_euler.copy(); sd_ob.scale = (0.75, 0.75, 0.75)
sd_ob.location = BASE + fwd*14 - right*2.05 + up*0.05; sd_ob.visible_shadow = False

# =====================================================================================
# 14. THE SIGN: Impact, 3 stacked layers (glowing face / black ink outline / cyan neon rim),
#     leaned toward the camera, cocked sideways, hung from two cables
# =====================================================================================
impact = bpy.data.fonts.load("/System/Library/Fonts/Supplemental/Impact.ttf", check_existing=True)
mf = bpy.data.materials.get(N("title_face")) or bpy.data.materials.new(N("title_face")); mf.use_nodes = True
ft = mf.node_tree; ft.nodes.clear(); L = ft.links.new
fo = ft.nodes.new("ShaderNodeOutputMaterial"); ftc = ft.nodes.new("ShaderNodeTexCoord")
fsg = ft.nodes.new("ShaderNodeSeparateXYZ"); fsn = ft.nodes.new("ShaderNodeSeparateXYZ")
frp = ft.nodes.new("ShaderNodeValToRGB"); fe = frp.color_ramp.elements
fe[0].position = 0.0; fe[0].color = (1.0, 0.10, 0.45, 1)          # hot pink at the bottom of the block
fe[1].position = 1.0; fe[1].color = (1.0, 0.92, 0.08, 1)          # yellow at the top
frp.color_ramp.elements.new(0.5).color = (1.0, 0.45, 0.05, 1)     # orange in between
fem = ft.nodes.new("ShaderNodeEmission"); fem.inputs[1].default_value = 0.75   # >1 and AgX bleaches it to cream
fsd = ft.nodes.new("ShaderNodeBsdfPrincipled"); fsd.inputs["Base Color"].default_value = (0.45, 0.0, 0.28, 1); fsd.inputs["Roughness"].default_value = 0.25
fse = ft.nodes.new("ShaderNodeEmission"); fse.inputs[0].default_value = (0.6, 0.0, 0.35, 1); fse.inputs[1].default_value = 0.4
fsa = ft.nodes.new("ShaderNodeAddShader")
fmr = ft.nodes.new("ShaderNodeMapRange"); fmr.inputs[1].default_value = 0.7; fmr.inputs[2].default_value = 0.95
fmx = ft.nodes.new("ShaderNodeMixShader")
L(ftc.outputs["Generated"], fsg.inputs[0]); L(fsg.outputs["Y"], frp.inputs[0]); L(frp.outputs[0], fem.inputs[0])
L(ftc.outputs["Normal"], fsn.inputs[0]); L(fsn.outputs["Z"], fmr.inputs[0])    # local +Z normal = front face
L(fsd.outputs[0], fsa.inputs[0]); L(fse.outputs[0], fsa.inputs[1])
L(fmr.outputs[0], fmx.inputs[0]); L(fsa.outputs[0], fmx.inputs[1]); L(fem.outputs[0], fmx.inputs[2]); L(fmx.outputs[0], fo.inputs[0])
BODY = "STATUS:\nREAL\nFUCKIN\nSICK"
rot = R.to_4x4() @ Matrix.Rotation(math.radians(-5), 4, 'Z') @ Matrix.Rotation(math.radians(10), 4, 'X')
anchor = BASE + up*2.62 + right*0.10 - fwd*4.0
layers = [("title",      0.008, 0.14, 0.018, mf,                                                    0.00),
          ("title_ink",  0.034, 0.09, 0.0,   mat(N("title_ink"), (0.02, 0.0, 0.035), rough=0.35),  -0.06),
          ("title_neon", 0.050, 0.03, 0.0,   emis(N("title_neon"), (0.1, 0.95, 1.0), 3.5),         -0.11)]
for name, off, ext, bev, m, dz in layers:
    kill(N(name))
    cu = bpy.data.curves.new(N(name), "FONT"); cu.font = impact; cu.body = BODY
    cu.align_x = 'CENTER'; cu.align_y = 'CENTER'; cu.size = 0.86; cu.space_line = 0.84; cu.space_character = 1.04
    cu.offset = off; cu.extrude = ext; cu.bevel_depth = bev; cu.bevel_resolution = 2
    cu.materials.append(m)
    ob = bpy.data.objects.new(N(name), cu); link(ob)
    ob.matrix_world = Matrix.Translation(anchor) @ rot @ Matrix.Translation((0, 0, dz))
    ob.visible_shadow = False
tw, th_, nz = rot.to_3x3() @ V((1,0,0)), rot.to_3x3() @ V((0,1,0)), rot.to_3x3() @ V((0,0,1))
bm = bmesh.new()
for sg in (-1, 1):
    p0 = anchor + tw*sg*0.95 + th_*1.08 - nz*0.06              # hooks into the top of "STATUS:"
    tube(bm, [p0 + V((0, 0, z)) for z in (0, 2, 4, 6)], [0.022]*4, ring=10); add_sphere(bm, p0, 0.045)
ob = mesh_obj(N("cables"), bm, mat(N("cable_m"), (0.02, 0.02, 0.025))); ob.visible_shadow = False

# =====================================================================================
# 15. RENDER (by scene name; the window's active scene is untouched)
# =====================================================================================
if RENDER:
    s.render.filepath = OUT; s.render.image_settings.file_format = 'PNG'
    bpy.ops.render.render(write_still=True, scene=SCN)
    print("rendered", OUT)
