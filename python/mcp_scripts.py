"""The Blender-side scripts the MCP tools run.

Each function takes the tool's arguments as a dict and returns a dict whose
"report" holds the text. scene_summary, look and bounds, ported from the
addon's observation scripts, keep their own result shape instead, as do
scene_items, object_info and viewport_screenshot, ported from the addon's
commands. The server ships this whole file to Blender once per content hash,
then calls one function by name (run_module in blender.rmcp.rb). This is a real
module rather than a string constant: it can be linted, imported and reviewed,
and a traceback out of Blender names a line in this file.

Every entry point's arguments and result are typed below (the *Args and result
TypedDicts), matching what blender.rmcp.rb sends: an unset string arrives as "",
an unset number as null. bpy and mathutils types resolve in a language server
once fake-bpy-module for the matching Blender version is installed where it
runs; Blender itself never evaluates the annotations.

One entry point by hand, with no server and no bridge:

    blender --background --python python/mcp_scripts.py -- reveal '{"name": "Chair"}'
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict, TypeVar, cast

if TYPE_CHECKING:
    import numpy as np
    from bpy.types import Area, Collection, LayerCollection, Object, Region, Space, Window
    from mathutils import Matrix, Vector


# --- Results ---


class Report(TypedDict):
    """What most entry points return: the text the tool shows."""
    report: str


class FileReport(TypedDict):
    """render, render_animation and export: the text, and the path written
    (absent when nothing was)."""
    report: str
    path: NotRequired[str]


class Failure(TypedDict):
    """scene_summary, look, object_info and viewport_screenshot report a miss
    this way; the tool raises it as the error."""
    error: str


class SceneSummary(TypedDict):
    header: dict[str, Any]
    lines: list[str]
    total: int
    shown: int


# look's result: mode, targets, centre and size, the views or frames drawn,
# width and height; the keys depend on the mode.
LookInfo = dict[str, Any]


class ObjectBounds(TypedDict):
    name: str
    world_bounding_box: list[list[float]]
    size: list[float]


class SceneItem(TypedDict):
    kind: Literal["object", "material", "collection"]
    name: str
    detail: str


class SceneItems(TypedDict):
    items: list[SceneItem]
    total: int


class ObjectInfo(TypedDict):
    name: str
    type: str
    location: list[float]
    rotation: list[float]
    scale: list[float]
    visible: bool
    materials: list[str]
    world_bounding_box: NotRequired[list[list[float]]]
    mesh: NotRequired[dict[str, int]]


class ViewportShot(TypedDict):
    width: int
    height: int
    filepath: str
    file: str
    scene: str


# --- Arguments, one per entry point ---


class RevealArgs(TypedDict, total=False):
    name: str
    frame: bool


class TextArgs(TypedDict, total=False):
    text: str
    name: str
    size: float
    extrude: float
    spacing: float | None
    align: str
    x: float
    y: float
    z: float
    as_mesh: bool


PlaceNumber = Literal["x", "y", "z", "rx", "ry", "rz", "scale"]


class PlaceArgs(TypedDict, total=False):
    name: str
    x: float | None
    y: float | None
    z: float | None
    rx: float | None
    ry: float | None
    rz: float | None
    scale: float | None
    relative: bool


class MaterialArgs(TypedDict, total=False):
    name: str
    colour: str
    material: str
    roughness: float | None
    metallic: float | None


class RenderArgs(TypedDict, total=False):
    file: str  # resolved under the write roots by the server; "" for the default
    folder: str  # the default output folder, resolved the same way
    camera: str
    width: int | None
    height: int | None
    samples: int | None
    frame: int | None


class RenderAnimationArgs(TypedDict, total=False):
    file: str
    folder: str
    scene: str
    camera: str
    frame_start: int | None
    frame_end: int | None
    fps: int | None
    width: int | None
    height: int | None
    samples: int | None
    format: Literal["mp4", "webm", "mkv", "png"]


class ExportArgs(TypedDict, total=False):
    file: str
    folder: str
    format: Literal["glb", "fbx"]
    objects: list[str]
    selection_only: bool
    apply_modifiers: bool


class RemoveArgs(TypedDict, total=False):
    names: list[str]
    purge: bool


class DuplicateArgs(TypedDict, total=False):
    names: list[str]
    count: int
    dx: float
    dy: float
    dz: float
    linked: bool


class ArrayArgs(TypedDict, total=False):
    name: str
    count: int
    mode: str
    offset_x: float | None
    offset_y: float | None
    offset_z: float | None


class BooleanArgs(TypedDict, total=False):
    name: str
    operand: str
    operation: str
    apply: bool
    hide_operand: bool


class AimArgs(TypedDict, total=False):
    target: str
    camera: str
    view: str
    distance: float | None
    lens: float | None


class LightArgs(TypedDict, total=False):
    name: str
    kind: str
    energy: float | None
    size: float | None
    target: str
    x: float | None
    y: float | None
    z: float | None


class WireframeArgs(TypedDict, total=False):
    name: str
    views: list[str]
    width: int
    height: int


class MeshReportArgs(TypedDict, total=False):
    name: str


class ImageReportArgs(TypedDict, total=False):
    source: str  # an image's name in the file, or an absolute path the server resolved
    width: int


class ModifierArgs(TypedDict, total=False):
    name: str
    action: str
    kind: str
    count: int | None
    amount: float | None
    axis: str
    apply: bool


class SceneSummaryArgs(TypedDict, total=False):
    fields: list[str]
    limit: int
    query: str
    root: str


class LookArgs(TypedDict, total=False):
    mode: Literal["viewport", "camera", "angles", "frames", "image"]
    shading: str
    target: list[str]
    views: list[str]
    distance: float
    view: str
    frames: list[int]
    frame_count: int
    max_size: int
    image: str
    filepath: str  # where to write the PNG, a server temp path


class BoundsArgs(TypedDict, total=False):
    names: list[str]


class SceneItemsArgs(TypedDict, total=False):
    query: str
    limit: int


class ObjectInfoArgs(TypedDict, total=False):
    name: str


class ViewportArgs(TypedDict, total=False):
    max_size: int
    filepath: str  # where to write the PNG, a server temp path


class AssetMap(TypedDict):
    key: str  # Poly Haven's map name: Diffuse, Rough, nor_gl and so on
    role: Literal["base_color", "roughness", "metallic", "displacement", "normal"]
    path: str


class AssetManifest(TypedDict, total=False):
    """What rust/blender_assets.rs's asset_fetch downloaded: one folder under the
    write roots holding the asset's files, and who made it."""
    source: Literal["polyhaven", "sketchfab", "polypizza"]
    kind: Literal["hdri", "texture", "model", "archive", "glb"]
    id: str
    asset_type: str
    resolution: str
    format: str
    dir: str  # the download folder, deleted once the files are packed
    path: str  # the file to import (hdri, model, archive, glb)
    maps: list[AssetMap]  # texture
    dimensions_mm: list[float]  # texture: its real-world size
    name: str | None
    url: str | None
    authors: list[str]
    licence: str | None
    attribution: str | None


class ImportAssetArgs(TypedDict, total=False):
    manifest: AssetManifest
    target_size: float  # metres across the largest dimension; 0 keeps the asset's own size
    apply_to: list[str]  # texture: objects to give a material built from it
    note: str  # appended to the message (the glTF fallback says why)


class AssetImported(TypedDict, total=False):
    source: str
    id: str
    message: str
    imported_objects: list[str]
    world_bounding_box: list[list[float]] | None
    dimensions: list[float] | None
    scale_applied: float
    world: str
    image: str
    material: str
    maps: list[str]
    applied_to: dict[str, str]  # object -> its new material
    not_applied: dict[str, str]  # object -> why not
    scale_mm: list[float] | None
    mapping_node: str | None
    authors: list[str]
    url: str | None
    licence: str | None
    attribution: str | None


class AssetFallback(TypedDict):
    """A Poly Haven .blend this Blender cannot open: the server fetches the glTF."""
    fallback: str


A = TypeVar("A", bound=Mapping[str, object])
R = TypeVar("R")


def push_step(message: str) -> None:
    """Mark an undo boundary, so the user's own undo lands on this call rather
    than in the middle of it. There is deliberately no undo tool: a single-step
    test of one ended the session, so the boundary is left for the user.

    Blender's undo is the whole file's history, not one tool's; without a
    boundary a later undo walks back through whatever happened before it.
    """
    import bpy

    try:
        bpy.ops.ed.undo_push(message=message)
    except Exception:
        pass


def undoable(fn: Callable[[A], R]) -> Callable[[A], R]:
    """Wrap an entry point so it opens an undo step before it changes anything."""
    import functools

    @functools.wraps(fn)
    def wrapped(args: A) -> R:
        subject = args.get("name") or args.get("names") or args.get("target") or args.get("file") or ""
        if isinstance(subject, (list, tuple)):
            subject = ", ".join(str(s) for s in subject[:3])
        push_step("%s: %s" % (fn.__name__, subject) if str(subject) != "" else fn.__name__)
        return fn(args)

    return wrapped


@undoable
def reveal(args: RevealArgs) -> Report:
    import bpy

    # Why an object is not on screen is a property of the view and the view layer,
    # not of the object. This reports both, clears the traps it finds, and frames
    # the object so the next screenshot has something in it.

    name = (args.get("name") or "").strip()
    want_frame = args.get("frame")
    if want_frame is None:
        want_frame = True

    def window_region(area: Area) -> Region | None:
        for r in area.regions:
            if r.type == "WINDOW":
                return r
        return None

    def override(window: Window, area: Area, space: Space | None = None) -> dict[str, Any]:
        over = {"window": window, "area": area}
        r = window_region(area)
        if r is not None:
            over["region"] = r
        if space is not None:
            over["space_data"] = space
        return over

    def layer_collection(node: LayerCollection, collection: Collection) -> LayerCollection | None:
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

@undoable
def text(args: TextArgs) -> Report:
    import bpy

    # A text object is a curve, not a mesh, so wireframe and mesh_report cannot read
    # it and glTF writes it as an outline. Converting to a mesh is therefore the
    # useful default, and the report says which one you got.

    text = args.get("text") or ""
    if text.strip() == "":
        return {"report": "text needs a non-empty string; the body is what gets drawn"}

    name = (args.get("name") or "").strip()
    if name == "":
        name = (text.strip().splitlines()[0][:32] or "Text")

    size = float(args.get("size") or 1.0)
    extrude = float(args.get("extrude") or 0.0)
    spacing = args.get("spacing")
    align = args.get("align") or "CENTER"
    loc = [float(args.get("x") or 0.0), float(args.get("y") or 0.0), float(args.get("z") or 0.0)]
    as_mesh = args.get("as_mesh")
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

@undoable
def place(args: PlaceArgs) -> Report:
    import bpy, math

    # Absolute by default, so a call is idempotent; relative when asked, so a
    # nudge is expressible. Only the axes given are touched, which is why an
    # unset axis cannot be confused with a zero.

    name = (args.get("name") or "").strip()
    ob = bpy.data.objects.get(name)
    if ob is None:
        near = [o.name for o in bpy.data.objects if name.lower() in o.name.lower()][:8] if name != "" else []
        return {"report": "place needs the exact name of an object in the scene%s" % ("; nearest: " + ", ".join(near) if len(near) > 0 else "")}

    rel = bool(args.get("relative"))

    def want(key: PlaceNumber) -> float | None:
        v = args.get(key)
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

@undoable
def material(args: MaterialArgs) -> Report:
    import bpy

    # Blender keeps two colours for a material: the Principled base colour a render
    # uses, and diffuse_color, the flat colour a solid viewport draws. Setting both
    # is what makes look(shading="solid") show the change without a render.

    NAMED_COLOURS = {"black": "#000000", "white": "#ffffff", "grey": "#808080", "gray": "#808080",
                     "red": "#d02020", "green": "#2f9e44", "blue": "#1c5fd0", "yellow": "#e8c020",
                     "orange": "#e07020", "purple": "#8038c0", "pink": "#e060a0", "brown": "#7a4f24",
                     "cyan": "#20b8c0", "magenta": "#c020a0", "wood": "#a9713f", "steel": "#8a9099",
                     "gold": "#c8a02a", "concrete": "#9a9a94", "glass": "#bcd8e0"}

    def to_linear(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def parse_colour(text: str) -> list[float] | None:
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

    name = (args.get("name") or "").strip()
    ob = bpy.data.objects.get(name)
    if ob is None:
        return {"report": "material needs the exact name of an object in the scene (scene lists them)"}
    data = getattr(ob, "data", None)
    if data is None or not hasattr(data, "materials"):
        return {"report": "%s is a %s object and carries no materials: they hang off mesh, curve, surface or grease pencil data" % (ob.name, ob.type)}

    want_material = (args.get("material") or "").strip()
    want_colour = (args.get("colour") or "").strip()
    roughness = args.get("roughness")
    metallic = args.get("metallic")
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

@undoable
def render(args: RenderArgs) -> FileReport:
    import bpy, os, time

    # Writes a real file at a real resolution, rather than the viewport grab look
    # takes, so the result is something the user keeps. For an image back in the
    # conversation use look(mode="camera"); for text, image_report reads this file.

    scene = bpy.context.scene
    want_file = (args.get("file") or "").strip()
    want_camera = (args.get("camera") or "").strip()
    width = args.get("width")
    height = args.get("height")
    samples = args.get("samples")
    frame = args.get("frame")

    base = bpy.data.filepath
    # The server passes folder, already resolved under its file roots, and it is
    # created here if it is new; the .blend's folder and the Desktop are only the
    # fallback for a direct call.
    folder = (args.get("folder") or "").strip()
    if folder != "":
        os.makedirs(folder, exist_ok=True)
    else:
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
        return {"report": "the scene has no camera to render from; add one with aim"}

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
    return {"path": path, "report": "\n".join(lines)}

@undoable
def render_animation(args: RenderAnimationArgs) -> FileReport:
    import bpy, os, time

    # Renders a whole frame range, where render writes one still. A scene has to
    # be the window's active one or its animation is not evaluated, and a
    # compositor render-layer node can pin the output to another scene, so both
    # are set below before the render.

    name = (args.get("scene") or "").strip()
    if name != "":
        sc = bpy.data.scenes.get(name)
        if sc is None:
            names = [s.name for s in bpy.data.scenes]
            return {"report": "no scene named %r; this file has: %s" % (name, ", ".join(names) if len(names) > 0 else "none")}
        try:
            bpy.context.window.scene = sc
        except Exception as e:
            return {"report": "cannot make scene %r the active one: %s" % (name, e)}
    else:
        sc = bpy.context.scene

    # A Render Layers node inside the compositor holds its own scene pointer; if
    # it points elsewhere the whole range renders that scene's first frame, so
    # pin it to the scene being rendered.
    if sc.use_nodes and sc.node_tree:
        for node in sc.node_tree.nodes:
            if node.type == "RL_LAYERS":
                node.scene = sc
                node.layer = sc.view_layers[0].name

    f0 = int(args.get("frame_start") if args.get("frame_start") is not None else sc.frame_start)
    f1 = int(args.get("frame_end") if args.get("frame_end") is not None else sc.frame_end)
    sc.frame_start = f0
    sc.frame_end = f1

    want_file = (args.get("file") or "").strip()
    want_camera = (args.get("camera") or "").strip()
    width = args.get("width")
    height = args.get("height")
    samples = args.get("samples")
    fps = args.get("fps")
    fmt = (args.get("format") or "mp4").strip().lower()
    if fmt not in ("mp4", "webm", "mkv", "png"):
        return {"report": "render_animation writes mp4, webm, mkv or png, not %r" % fmt}

    if fps is not None:
        sc.render.fps = int(fps)
    if width is not None:
        sc.render.resolution_x = int(width)
    if height is not None:
        sc.render.resolution_y = int(height)
    if samples is not None:
        n = int(samples)
        if sc.render.engine == "CYCLES" and hasattr(sc, "cycles"):
            sc.cycles.samples = n
        else:
            try:
                sc.eevee.taa_render_samples = n
            except Exception:
                pass

    if want_camera != "":
        cam = bpy.data.objects.get(want_camera)
        if cam is None or cam.type != "CAMERA":
            cams = [o.name for o in bpy.data.objects if o.type == "CAMERA"]
            return {"report": "no camera named %r; this file has: %s" % (want_camera, ", ".join(cams) if len(cams) > 0 else "none")}
        sc.camera = cam
    if sc.camera is None:
        return {"report": "the scene has no camera to render from; add one with aim"}

    base = bpy.data.filepath
    # The server passes folder, already resolved under its file roots, and it is
    # created here if it is new; the .blend's folder and the Desktop are only the
    # fallback for a direct call.
    folder = (args.get("folder") or "").strip()
    if folder != "":
        os.makedirs(folder, exist_ok=True)
    else:
        folder = os.path.dirname(base) if base else ""
        if folder == "" or not os.path.isdir(folder):
            home = os.path.expanduser("~")
            desktop = os.path.join(home, "Desktop")
            folder = desktop if os.path.isdir(desktop) else home
    stem = os.path.splitext(os.path.basename(base))[0] if base else "scene"
    if want_file == "":
        dest = os.path.join(folder, "%s-anim" % stem)
    else:
        dest = os.path.expanduser(want_file)
        if not os.path.isabs(dest):
            dest = os.path.join(folder, dest)

    sc.render.resolution_percentage = 100
    if fmt == "png":
        # png writes one numbered file per frame into a directory: Blender appends
        # 0001.png to the filepath, so the template is dir/<stem>_
        out_dir = os.path.dirname(dest) if os.path.splitext(dest)[1] != "" else dest
        if out_dir != "" and not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir)
            except Exception as e:
                return {"report": "cannot create %s: %s" % (out_dir, e)}
        sc.render.image_settings.file_format = "PNG"
        sc.render.filepath = os.path.join(out_dir, stem + "_")
        path = sc.render.filepath + ("%04d.png" % f0)
    else:
        if os.path.splitext(dest)[1] == "":
            dest = dest + "." + fmt
        out_dir = os.path.dirname(dest)
        if out_dir != "" and not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir)
            except Exception as e:
                return {"report": "cannot create %s: %s" % (out_dir, e)}
        sc.render.image_settings.file_format = "FFMPEG"
        if fmt == "mp4":
            sc.render.ffmpeg.format = "MPEG4"
            sc.render.ffmpeg.codec = "H264"
        elif fmt == "mkv":
            sc.render.ffmpeg.format = "MATROSKA"
            sc.render.ffmpeg.codec = "H264"
        else:
            sc.render.ffmpeg.format = "WEBM"
            sc.render.ffmpeg.codec = "WEBM"
            sc.render.ffmpeg.audio_codec = "OPUS"
        sc.render.filepath = dest
        path = dest

    started = time.time()
    try:
        bpy.ops.render.render(animation=True, scene=sc.name)
    except Exception as e:
        return {"report": "the animation render stopped: %s" % e}
    seconds = time.time() - started

    lines = ["wrote %s" % path,
             "%d frames (frame %d to %d) as %s in %.1f s  %s  %dx%d at %d%%  %d fps"
             % (f1 - f0 + 1, f0, f1, fmt, seconds, sc.render.engine, sc.render.resolution_x, sc.render.resolution_y,
                sc.render.resolution_percentage, sc.render.fps),
             "scene %s  camera %s  (resolution_percentage is 100)" % (sc.name, sc.camera.name if sc.camera else "(none)"),
             "a long range can outlive the bridge timeout: if the reply times out the frames already written are still on disk, so check what is there before re-running rather than starting the whole range again"]
    return {"path": path, "report": "\n".join(lines)}

@undoable
def export(args: ExportArgs) -> FileReport:
    import bpy, os

    # The file lands next to the .blend, or on the Desktop for an unsaved one, so
    # the report can name a path the user recognises instead of a temp file.

    fmt = (args.get("format") or "glb").strip().lower()
    if fmt not in ("glb", "fbx"):
        return {"report": "export writes glb or fbx, not %r" % fmt}
    names = args.get("objects") or []
    if not isinstance(names, (list, tuple)):
        names = [names]
    selection_only = bool(args.get("selection_only"))
    mods = args.get("apply_modifiers")
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
    # The server passes folder, already resolved under its file roots, and it is
    # created here if it is new; the .blend's folder and the Desktop are only the
    # fallback for a direct call.
    folder = (args.get("folder") or "").strip()
    if folder != "":
        os.makedirs(folder, exist_ok=True)
    else:
        folder = os.path.dirname(base) if base else ""
        if folder == "" or not os.path.isdir(folder):
            home = os.path.expanduser("~")
            desktop = os.path.join(home, "Desktop")
            folder = desktop if os.path.isdir(desktop) else home
    stem = os.path.splitext(os.path.basename(base))[0] if base else "scene"
    want_file = (args.get("file") or "").strip()
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
    return {"path": path, "report": "\n".join(lines)}


@undoable
def remove(args: RemoveArgs) -> Report:
    """Delete objects, and say what that cost: what went, what the children did,
    what the orphan purge freed, and what is left."""
    import bpy

    names = args.get("names") or []
    if not isinstance(names, (list, tuple)):
        names = [names]
    wanted = []
    for n in names:
        text = str(n).strip()
        if text != "":
            wanted.append(text)
    if len(wanted) == 0:
        return {"report": "remove needs at least one object name; scene lists what is here"}
    purge = args.get("purge")
    if purge is None:
        purge = True

    gone = []
    missing = []
    orphans = []
    for name in wanted:
        ob = bpy.data.objects.get(name)
        if ob is None:
            missing.append(name)
            continue
        for child in list(ob.children):
            orphans.append("%s (was a child of %s)" % (child.name, ob.name))
        gone.append("%s [%s]" % (ob.name, ob.type))
        bpy.data.objects.remove(ob, do_unlink=True)

    if len(gone) == 0:
        lines = ["no object named %s" % ", ".join(missing)]
        for name in missing:
            near = [o.name for o in bpy.data.objects if name.lower() in o.name.lower()][:5]
            if len(near) > 0:
                lines.append("  nearest to %r: %s" % (name, ", ".join(near)))
        lines.append("nothing was removed; %d object(s) here" % len(bpy.data.objects))
        return {"report": "\n".join(lines)}

    lines = ["removed %d object(s): %s" % (len(gone), ", ".join(gone))]
    if len(missing) > 0:
        lines.append("no object named %s" % ", ".join(missing))
    if len(orphans) > 0:
        lines.append("left in the scene, now unparented: %s" % ", ".join(orphans))
    if purge:
        meshes_before = len(bpy.data.meshes)
        materials_before = len(bpy.data.materials)
        images_before = len(bpy.data.images)
        bpy.data.orphans_purge(do_recursive=True)
        freed = []
        if meshes_before > len(bpy.data.meshes):
            freed.append("%d mesh(es)" % (meshes_before - len(bpy.data.meshes)))
        if materials_before > len(bpy.data.materials):
            freed.append("%d material(s)" % (materials_before - len(bpy.data.materials)))
        if images_before > len(bpy.data.images):
            freed.append("%d image(s)" % (images_before - len(bpy.data.images)))
        lines.append("purged data with no user left: " + (", ".join(freed) if len(freed) > 0 else "nothing was orphaned"))
    else:
        lines.append("purge was false: the meshes and materials these objects used are still in the file")
    lines.append("%d object(s) left: %s" % (len(bpy.data.objects), ", ".join(sorted(o.name for o in bpy.data.objects)[:24])))
    return {"report": "\n".join(lines)}


def look_at_rotation(location: Sequence[float], point: Sequence[float]) -> tuple[float, ...]:
    """A camera-style rotation (looking along -Z, +Y up) from a position to a point."""
    from mathutils import Vector

    direction = Vector(point) - Vector(location)
    if direction.length < 1e-6:
        return (0.0, 0.0, 0.0)
    return tuple(direction.to_track_quat("-Z", "Y").to_euler())


def bounds_of(objects: Iterable[Object]) -> tuple[Vector, float]:
    """The world-space centre and the largest dimension across these objects."""
    from mathutils import Vector

    lo = None
    hi = None
    for ob in objects:
        for corner in ob.bound_box:
            point = ob.matrix_world @ Vector(corner)
            if lo is None:
                lo = Vector((point.x, point.y, point.z))
                hi = Vector((point.x, point.y, point.z))
            else:
                lo = Vector((min(lo.x, point.x), min(lo.y, point.y), min(lo.z, point.z)))
                hi = Vector((max(hi.x, point.x), max(hi.y, point.y), max(hi.z, point.z)))
    if lo is None:
        return (Vector((0.0, 0.0, 0.0)), 1.0)
    centre = (lo + hi) / 2.0
    size = max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z)
    return (centre, size if size > 1e-6 else 1.0)


def view_direction(view: str, distance: float) -> Vector:
    """Where to stand, relative to a centre, for a named view."""
    from mathutils import Vector

    if view == "front":
        return Vector((0.0, -distance, 0.0))
    if view == "back":
        return Vector((0.0, distance, 0.0))
    if view == "left":
        return Vector((-distance, 0.0, 0.0))
    if view == "right":
        return Vector((distance, 0.0, 0.0))
    if view == "top":
        return Vector((0.0, 0.0, distance))
    return Vector((distance * 0.55, -distance * 0.7, distance * 0.45))


@undoable
def duplicate(args: DuplicateArgs) -> Report:
    """Copy objects, offsetting each copy, so one generated chair can become a row."""
    import bpy

    names = args.get("names") or []
    if not isinstance(names, (list, tuple)):
        names = [names]
    wanted = [str(n).strip() for n in names if str(n).strip() != ""]
    if len(wanted) == 0:
        return {"report": "duplicate needs at least one object name; scene lists what is here"}
    count = int(args.get("count") or 1)
    count = max(1, min(count, 200))
    linked = args.get("linked")
    if linked is None:
        linked = False
    step = [float(args.get("dx") or 0.0), float(args.get("dy") or 0.0), float(args.get("dz") or 0.0)]

    made = []
    missing = []
    for name in wanted:
        ob = bpy.data.objects.get(name)
        if ob is None:
            missing.append(name)
            continue
        for i in range(1, count + 1):
            copy = ob.copy()
            if not linked and ob.data is not None:
                copy.data = ob.data.copy()
            copy.location = (ob.location.x + step[0] * i,
                             ob.location.y + step[1] * i,
                             ob.location.z + step[2] * i)
            if ob.parent is not None:
                copy.parent = ob.parent
            pasted = False
            for collection in ob.users_collection:
                collection.objects.link(copy)
                pasted = True
            if not pasted:
                bpy.context.scene.collection.objects.link(copy)
            made.append(copy.name)

    if len(made) == 0:
        lines = ["no object named %s" % ", ".join(missing)]
        for name in missing:
            near = [o.name for o in bpy.data.objects if name.lower() in o.name.lower()][:5]
            if len(near) > 0:
                lines.append("  nearest to %r: %s" % (name, ", ".join(near)))
        lines.append("nothing was copied; %d object(s) here" % len(bpy.data.objects))
        return {"report": "\n".join(lines)}

    lines = ["copied %d object(s): %s" % (len(made), ", ".join(made))]
    if len(missing) > 0:
        lines.append("no object named %s" % ", ".join(missing))
    lines.append("step (%g, %g, %g) per copy, from the original's own position" % tuple(step))
    if linked:
        lines.append("linked: every copy shares the original's mesh data, so editing one changes them all")
    else:
        lines.append("full copies: each has its own mesh, so one can be edited without the others")
    lines.append("%d object(s) in the scene now" % len(bpy.data.objects))
    return {"report": "\n".join(lines)}


@undoable
def array(args: ArrayArgs) -> Report:
    """Stack copies of one object with the array modifier, which follows the original."""
    import bpy

    name = (args.get("name") or "").strip()
    ob = bpy.data.objects.get(name)
    if ob is None:
        return {"report": "array needs the exact name of a mesh object; scene lists them"}
    if ob.type != "MESH":
        return {"report": "%s is a %s object; the array modifier needs a mesh" % (ob.name, ob.type)}
    count = max(1, min(int(args.get("count") or 3), 1000))
    mode = (args.get("mode") or "constant").lower()
    if mode not in ("constant", "relative"):
        return {"report": "mode must be constant (offset in metres) or relative (as a factor of the object), not %r" % mode}
    offsets = [args.get("offset_x"), args.get("offset_y"), args.get("offset_z")]
    given = [float(v) for v in offsets if v is not None]
    if len(given) == 0:
        if mode == "relative":
            offsets = [1.0, 0.0, 0.0]
        else:
            offsets = [ob.dimensions.x, 0.0, 0.0]
    else:
        offsets = [0.0 if v is None else float(v) for v in offsets]

    modifier = None
    for existing in ob.modifiers:
        if existing.type == "ARRAY":
            modifier = existing
            break
    fresh = modifier is None
    if fresh:
        modifier = ob.modifiers.new("Array", "ARRAY")
    modifier.count = count
    modifier.use_relative_offset = (mode == "relative")
    modifier.use_constant_offset = (mode == "constant")
    modifier.relative_offset_displace = (offsets[0], offsets[1], offsets[2])
    modifier.constant_offset_displace = (offsets[0], offsets[1], offsets[2])
    bpy.context.view_layer.update()

    base_faces = len(ob.data.polygons)
    shown = base_faces
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        shown = len(ob.evaluated_get(depsgraph).data.polygons)
    except Exception:
        pass

    lines = ["%s: array modifier %s, count %d, offsets (%g, %g, %g) %s"
             % (ob.name, "created" if fresh else "updated", count, offsets[0], offsets[1], offsets[2],
                "as factors of the object" if mode == "relative" else "in metres")]
    lines.append("faces %d in the mesh, %d with the modifier applied" % (base_faces, shown))
    lines.append("the modifier follows the object: move the original and the whole row moves; renders and exports apply it")
    lines.append("mesh_report and wireframe read the base mesh, so they still show %d faces" % base_faces)
    if count == 1:
        lines.append("count 1 is one copy: nothing is added")
    return {"report": "\n".join(lines)}


@undoable
def boolean(args: BooleanArgs) -> Report:
    """Cut, join or intersect two meshes, and report what the result actually is."""
    import bpy

    name = (args.get("name") or "").strip()
    operand_name = (args.get("operand") or "").strip()
    ob = bpy.data.objects.get(name)
    operand = bpy.data.objects.get(operand_name)
    if ob is None:
        return {"report": "boolean needs the exact name of the object to modify; scene lists them"}
    if operand is None:
        return {"report": "boolean needs the exact name of the object to cut with, as operand"}
    if ob == operand:
        return {"report": "the operand is the same object as %s; it takes a second object" % ob.name}
    if ob.type != "MESH" or operand.type != "MESH":
        return {"report": "both objects must be meshes; %s is a %s and %s is a %s" % (ob.name, ob.type, operand.name, operand.type)}
    operation = (args.get("operation") or "difference").lower()
    if operation not in ("difference", "union", "intersect"):
        return {"report": "operation must be difference, union or intersect, not %r" % operation}
    apply_now = args.get("apply")
    if apply_now is None:
        apply_now = True
    hide = args.get("hide_operand")
    if hide is None:
        hide = True

    before = len(ob.data.polygons)
    modifier = ob.modifiers.new("Boolean", "BOOLEAN")
    modifier.operation = operation.upper()
    modifier.object = operand
    bpy.context.view_layer.update()

    applied = False
    note = ""
    if apply_now:
        for o in list(bpy.context.selected_objects):
            o.select_set(False)
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        try:
            bpy.ops.object.modifier_apply(modifier=modifier.name)
            applied = True
        except Exception as e:
            note = "could not apply the modifier (%s), so it stays live" % e
    after = len(ob.data.polygons)
    if not applied:
        try:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            after = len(ob.evaluated_get(depsgraph).data.polygons)
        except Exception:
            after = before
    if hide:
        operand.hide_viewport = True
        operand.hide_render = True

    lines = ["%s %s %s: faces %d -> %d" % (ob.name, operation, operand.name, before, after)]
    lines.append("modifier %s" % ("applied, so the mesh itself changed" if applied else "left live, so the result is evaluated on top"))
    if note != "":
        lines.append(note)
    if hide:
        lines.append("%s is now hidden in the viewport and from renders, as a cutter usually is" % operand.name)
    if after == 0:
        lines.append("the result is empty: check that the two objects overlap")
    elif after == before:
        lines.append("the face count did not change: the objects may not overlap, or the cut missed")
    return {"report": "\n".join(lines)}


@undoable
def aim(args: AimArgs) -> Report:
    """Put the camera where it frames a target, so a render or a look shows the subject."""
    import bpy, math

    name = (args.get("target") or "").strip()
    ob = bpy.data.objects.get(name)
    if ob is None:
        return {"report": "aim needs the exact name of an object to look at; scene lists them"}
    camera_name = (args.get("camera") or "").strip()
    camera = bpy.data.objects.get(camera_name) if camera_name != "" else bpy.context.scene.camera
    created = False
    if camera is None:
        data = bpy.data.cameras.new(camera_name or "MCP Camera")
        camera = bpy.data.objects.new(camera_name or "MCP Camera", data)
        bpy.context.scene.collection.objects.link(camera)
        created = True
    if camera.type != "CAMERA":
        return {"report": "%s is a %s object, not a camera" % (camera.name, camera.type)}
    view = (args.get("view") or "three_quarter").lower()
    lens = args.get("lens")
    if lens is not None:
        camera.data.lens = float(lens)
    lens = camera.data.lens
    centre, size = bounds_of([ob])
    want = args.get("distance")
    if want is None:
        sensor = camera.data.sensor_width or 36.0
        half_angle = math.atan((sensor / 2.0) / max(lens, 1e-3))
        want = (size / 2.0) / math.tan(half_angle) * 1.8
    want = float(want)
    location = centre + view_direction(view, want)
    camera.location = location
    camera.rotation_mode = "XYZ"
    camera.rotation_euler = look_at_rotation(location, centre)
    bpy.context.scene.camera = camera
    bpy.context.view_layer.update()

    lines = ["camera %s%s set to %s of %s" % (camera.name, " (created)" if created else "", view, ob.name)]
    lines.append("target centre (%g, %g, %g), largest dimension %g m; camera %g m away at (%g, %g, %g), lens %g mm"
                 % (centre.x, centre.y, centre.z, size, want, location.x, location.y, location.z, lens))
    lines.append("it is now the scene camera, so render and look(mode=\"camera\") frame %s" % ob.name)
    if size < 0.02:
        lines.append("%s is less than 2 cm across; move closer or set distance explicitly" % ob.name)
    return {"report": "\n".join(lines)}


@undoable
def light(args: LightArgs) -> Report:
    """Make or adjust a light, aimed at something useful rather than at nothing."""
    import bpy

    name = (args.get("name") or "").strip()
    ob = bpy.data.objects.get(name) if name != "" else None
    if name != "" and ob is None:
        near = [o.name for o in bpy.data.objects if name.lower() in o.name.lower()][:5]
        return {"report": "no object named %r%s; leave name unset to create a light" % (name, ("; nearest: " + ", ".join(near)) if len(near) > 0 else "")}
    kind = (args.get("kind") or "sun").lower()
    if kind not in ("point", "sun", "area", "spot"):
        return {"report": "type must be point, sun, area or spot, not %r" % kind}
    created = False
    if ob is None:
        data = bpy.data.lights.new(name or "MCP Light", type=kind.upper())
        ob = bpy.data.objects.new(name or "MCP Light", data)
        collection = bpy.context.scene.collection
        try:
            if bpy.context.collection is not None:
                collection = bpy.context.collection
        except Exception:
            pass
        collection.objects.link(ob)
        created = True
    if ob.type != "LIGHT":
        return {"report": "%s is a %s object, not a light" % (ob.name, ob.type)}
    ob.data.type = kind.upper()

    energy = args.get("energy")
    if energy is None:
        energy = 3.0 if kind == "sun" else 1000.0
    ob.data.energy = float(energy)
    size = args.get("size")
    if size is not None:
        if kind == "area":
            ob.data.size = float(size)
        elif kind == "spot":
            ob.data.spot_size = float(size)

    target_name = (args.get("target") or "").strip()
    target = bpy.data.objects.get(target_name) if target_name != "" else None
    if target is None:
        visible = [o for o in bpy.context.view_layer.objects if o.type != "LIGHT" and o != ob]
        centre, span = bounds_of(visible if len(visible) > 0 else [ob])
        target = None
        point = centre
    else:
        point, span = bounds_of([target])

    given = [args.get("x"), args.get("y"), args.get("z")]
    if len([v for v in given if v is not None]) > 0:
        location = (ob.location.x if given[0] is None else float(given[0]),
                    ob.location.y if given[1] is None else float(given[1]),
                    ob.location.z if given[2] is None else float(given[2]))
    else:
        location = (point.x + span, point.y - span, point.z + span * 1.2)
    ob.location = location
    ob.rotation_mode = "XYZ"
    ob.rotation_euler = look_at_rotation(location, point)
    bpy.context.view_layer.update()

    lights = [o.name for o in bpy.data.objects if o.type == "LIGHT"]
    lines = ["light %s%s: %s at energy %g" % (ob.name, " (created)" if created else " (updated)", ob.data.type.lower(), ob.data.energy)]
    lines.append("at (%g, %g, %g), aimed at %s" % (location[0], location[1], location[2],
                 target.name if target is not None else "the scene's objects"))
    lines.append("%d light(s) in the file: %s" % (len(lights), ", ".join(lights)))
    if kind == "sun":
        lines.append("a sun has no falloff and no distance: energy is irradiance, and about 3 reads as daylight")
    else:
        lines.append("a %s light falls off with distance: energy is in watts, and 1000 is a lamp-sized default" % kind)
    return {"report": "\n".join(lines)}



def wireframe(args: WireframeArgs) -> Report:
    """Draw a mesh as text: front, side or top edge projections at true proportions."""
    import bpy

    # Inputs from the MCP tool.
    name = args.get("name")
    if not name:
        return {"report": "wireframe needs the name of a mesh object"}

    views = args.get("views") or ["front", "side"]
    if not isinstance(views, (list, tuple)):
        views = [views]

    width = args.get("width") or 78
    height = args.get("height") or 34
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


    def axis_pair(view: str) -> tuple[Callable[[Vector], float], Callable[[Vector], float], str]:
        # One shared scale for both axes, so proportions are true.
        if view == "front":
            return (lambda v: v.x), (lambda v: v.z), "FRONT  x->right, z->up"
        if view == "side":
            return (lambda v: v.y), (lambda v: v.z), "SIDE   y->right, z->up"
        if view == "top":
            return (lambda v: v.x), (lambda v: v.y), "TOP    x->right, y->up"
        raise ValueError("unknown view '" + str(view) + "'; use front, side or top")


    def draw(ax: Callable[[Vector], float], bz: Callable[[Vector], float], label: str) -> str:
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

def mesh_report(args: MeshReportArgs) -> Report:
    """Measure a mesh: dimensions, bounds, loose parts and a face-orientation histogram."""
    import bpy
    import bmesh
    from collections import Counter

    name = args.get("name")
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


    def find(x: int) -> int:
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

def image_report(args: ImageReportArgs) -> Report:
    """Describe an image as text: dimensions, aspect, mean and top colours, and two character grids."""
    import bpy, os, numpy as np

    source = args.get("source") or ""
    cols = max(40, min(int(args.get("width") or 116), 200))
    if source == "":
        return {"report": "image_report needs an image already in the file, by name, or a path to load"}

    src = bpy.data.images.get(source)
    loaded = src is None
    if loaded:
        # A path comes from the server already resolved under its file roots,
        # so it is absolute; anything else was a name that is not in the file.
        if not os.path.isabs(source):
            return {"report": "no image named %r in the file; a path on disk must sit under the file roots" % source}
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

@undoable
def modifier(args: ModifierArgs) -> Report:
    """Add, remove or list one modifier, with the setting that matters typed."""
    import bpy

    KINDS = {"subdivision": "SUBSURF", "bevel": "BEVEL", "mirror": "MIRROR",
             "solidify": "SOLIDIFY", "decimate": "DECIMATE", "wireframe": "WIREFRAME"}
    name = (args.get("name") or "").strip()
    ob = bpy.data.objects.get(name)
    if ob is None:
        return {"report": "modifier needs the exact name of an object; scene lists them"}
    if ob.type != "MESH":
        return {"report": "%s is a %s object; these modifiers need a mesh" % (ob.name, ob.type)}
    action = (args.get("action") or "add").lower()

    def counted() -> tuple[int, int]:
        base = len(ob.data.polygons)
        shown = base
        try:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            shown = len(ob.evaluated_get(depsgraph).data.polygons)
        except Exception:
            pass
        return (base, shown)

    if action == "list":
        lines = ["%s carries %d modifier(s):" % (ob.name, len(ob.modifiers))]
        for i, m in enumerate(ob.modifiers):
            lines.append("  %d: %s [%s]%s" % (i, m.name, m.type, "" if m.show_render else " (hidden from renders)"))
        if len(ob.modifiers) == 0:
            lines.append("  none")
        base, shown = counted()
        lines.append("faces %d in the mesh, %d with them applied" % (base, shown))
        return {"report": "\n".join(lines)}

    kind = (args.get("kind") or "").strip().lower()
    if kind not in KINDS:
        return {"report": "kind must be one of %s" % ", ".join(sorted(KINDS))}
    if action == "remove":
        target = None
        for m in ob.modifiers:
            if m.type == KINDS[kind]:
                target = m
                break
        if target is None:
            return {"report": "%s has no %s modifier to remove; action list shows what it has" % (ob.name, kind)}
        removed = target.name
        ob.modifiers.remove(target)
        bpy.context.view_layer.update()
        return {"report": "removed modifier %s (%s) from %s; %d left: %s"
                % (removed, kind, ob.name, len(ob.modifiers), ", ".join(m.name for m in ob.modifiers) or "none")}
    if action != "add":
        return {"report": "action must be add, remove or list, not %r" % action}

    existing = None
    for m in ob.modifiers:
        if m.type == KINDS[kind]:
            existing = m
            break
    fresh = existing is None
    mod = existing if existing is not None else ob.modifiers.new(kind.title(), KINDS[kind])
    count = args.get("count")
    amount = args.get("amount")
    axis = (args.get("axis") or "").lower()
    used = []
    if kind == "subdivision":
        if count is not None:
            mod.levels = int(count)
            mod.render_levels = int(count)
        used.append("levels %d" % mod.levels)
    elif kind == "bevel":
        if amount is not None:
            mod.width = float(amount)
        used.append("width %g" % mod.width)
        used.append("segments %d" % mod.segments)
    elif kind == "mirror":
        if axis in ("x", "y", "z"):
            mod.use_axis = (axis == "x", axis == "y", axis == "z")
        used.append("axis %s" % "".join(a for a, on in zip("XYZ", mod.use_axis) if on))
    elif kind == "solidify":
        if amount is not None:
            mod.thickness = float(amount)
        used.append("thickness %g" % mod.thickness)
    elif kind == "decimate":
        if amount is not None:
            mod.ratio = max(0.0, min(float(amount), 1.0))
        used.append("ratio %g" % mod.ratio)
    elif kind == "wireframe":
        if amount is not None:
            mod.thickness = float(amount)
        used.append("thickness %g" % mod.thickness)
    bpy.context.view_layer.update()

    applied = False
    note = ""
    if args.get("apply"):
        for o in list(bpy.context.selected_objects):
            o.select_set(False)
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        try:
            bpy.ops.object.modifier_apply(modifier=mod.name)
            applied = True
        except Exception as e:
            note = "could not apply it (%s), so it stays live" % e
    base, shown = counted()
    lines = ["%s: %s modifier %s" % (ob.name, kind, "created" if fresh else "updated")]
    lines.append("settings: %s" % (", ".join(used) if len(used) > 0 else "none given; the defaults stand"))
    lines.append("faces %d in the mesh, %d with the modifiers applied" % (base, shown))
    lines.append("modifiers on %s: %s" % (ob.name, ", ".join("%s [%s]" % (m.name, m.type) for m in ob.modifiers)))
    if note != "":
        lines.append(note)
    lines.append("mesh_report and wireframe read the base mesh, so they still see %d faces" % base)
    return {"report": "\n".join(lines)}


def scene_summary(args: SceneSummaryArgs) -> SceneSummary | Failure:
    """One line per object with the fields the caller asked for, plus scene counts.

    The body is ported from the addon's SCENE_SUMMARY script, so the result keeps
    the same shape the scene_info tool parses: a header, the object lines, the
    total object count and how many lines were shown.
    """
    import bpy
    import math
    from mathutils import Vector

    scene = bpy.context.scene
    F = set(args.get("fields") or ())
    depsgraph = bpy.context.evaluated_depsgraph_get() if F & {"size", "ground"} else None
    limit = max(1, min(int(args.get("limit") or 20), 500))
    query = (args.get("query") or "").strip().lower()
    root_name = args.get("root")

    def r(v: float) -> float:
        return round(float(v), 2)

    def bounds(obj: Object) -> tuple[list[float], list[float]] | None:
        if obj.type in {"EMPTY", "LIGHT", "CAMERA"}:
            return None
        try:
            ev = obj.evaluated_get(depsgraph)
            pts = [ev.matrix_world @ Vector(c) for c in ev.bound_box]
        except Exception:
            return None
        lo = [min(p[i] for p in pts) for i in range(3)]
        hi = [max(p[i] for p in pts) for i in range(3)]
        return lo, hi

    def line(obj: Object, depth: int = 0) -> str:
        parts = [("  " * depth) + obj.name, obj.type.lower()]
        if "location" in F:
            loc = obj.matrix_world.translation
            parts.append(f"at ({r(loc.x)}, {r(loc.y)}, {r(loc.z)})")
        if "rotation" in F:
            e = obj.matrix_world.to_euler()
            parts.append(f"rot ({round(math.degrees(e.x))}, {round(math.degrees(e.y))}, {round(math.degrees(e.z))})")
        if "scale" in F:
            s = obj.matrix_world.to_scale()
            parts.append(f"scale ({r(s.x)}, {r(s.y)}, {r(s.z)})")
        b = bounds(obj) if F & {"size", "ground"} else None
        if b and "size" in F:
            parts.append(f"size {r(b[1][0] - b[0][0])}x{r(b[1][1] - b[0][1])}x{r(b[1][2] - b[0][2])}")
        if b and "ground" in F:
            if abs(b[0][2]) < 0.005:
                parts.append("on ground")
            elif b[0][2] < -0.005:
                parts.append(f"below ground by {r(-b[0][2])}")
            else:
                parts.append(f"floating {r(b[0][2])}")
        if "parent" in F and obj.parent:
            parts.append(f"parent {obj.parent.name}")
        if "details" in F:
            if obj.type == "MESH":
                parts.append(f"{len(obj.data.polygons)} faces")
            elif obj.type == "ARMATURE":
                parts.append(f"{len(obj.data.bones)} bones")
            elif obj.type == "LIGHT":
                parts.append(f"{obj.data.type.lower()} {r(obj.data.energy)}W")
        if "materials" in F:
            mats = [s.material.name for s in getattr(obj, "material_slots", []) if s.material]
            if mats:
                parts.append("mat " + ", ".join(mats[:3]) + ("..." if len(mats) > 3 else ""))
        if "modifiers" in F and obj.modifiers:
            parts.append("mods " + ", ".join(m.type.lower() for m in obj.modifiers))
        if "animation" in F and obj.animation_data and obj.animation_data.action:
            parts.append(f"anim {obj.animation_data.action.name}")
        if "hidden" in F and (obj.hide_get() or obj.hide_render):
            parts.append("hidden")
        if "children" in F and obj.children:
            parts.append(f"{len(obj.children)} children")
        if "topology" in F and obj.type == "MESH":
            parts.append(topology(obj))
        if "weights" in F and obj.type == "MESH":
            w = weights(obj)
            if w:
                parts.append(w)
        return " | ".join(parts)

    def topology(obj: Object) -> str:
        import bmesh
        if obj.mode == "EDIT":
            obj.update_from_editmode()
        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            sides = [len(f.verts) for f in bm.faces]
            non_manifold = sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary)
            boundary = sum(1 for e in bm.edges if e.is_boundary)
            loose = sum(1 for v in bm.verts if not v.link_edges)
            poles = sum(1 for v in bm.verts if len(v.link_edges) not in (0, 2, 4) and not v.is_boundary)
        finally:
            bm.free()
        return (f"{sides.count(4)} quads, {sides.count(3)} tris, {sum(1 for n in sides if n > 4)} ngons; "
                f"{non_manifold} non-manifold, {boundary} boundary edges, {loose} loose verts, {poles} poles")

    def weights(obj: Object) -> str | None:
        arm = next((m.object for m in obj.modifiers if m.type == "ARMATURE" and m.object), None)
        if arm is None:
            return None
        deform = {b.name for b in arm.data.bones if b.use_deform}
        groups = {g.index for g in obj.vertex_groups if g.name in deform}
        unweighted = sum(1 for v in obj.data.vertices if not any(g.group in groups and g.weight > 0 for g in v.groups))
        missing = sorted(deform - {g.name for g in obj.vertex_groups})
        return (f"{unweighted} of {len(obj.data.vertices)} verts unweighted by {arm.name}"
                + (f"; deform bones with no group: {', '.join(missing[:10])}" + ("..." if len(missing) > 10 else "") if missing else ""))

    lines = []
    total = 0
    if root_name:
        root = bpy.data.objects.get(root_name)
        if root is None:
            return {"error": f"No object named {root_name!r}"}

        def walk(obj: Object, depth: int) -> None:
            nonlocal total
            total += 1
            if len(lines) < limit:
                lines.append(line(obj, depth))
            for child in obj.children:
                walk(child, depth + 1)

        walk(root, 0)
    else:
        if query:
            objs = [o for o in scene.objects if query in o.name.lower()]
        else:
            objs = [o for o in scene.objects if o.parent is None]
        total = len(objs)
        lines = [line(o) for o in objs[:limit]]

    counts = {}
    for o in scene.objects:
        counts[o.type.lower()] = counts.get(o.type.lower(), 0) + 1

    active = bpy.context.view_layer.objects.active
    selected = [o.name for o in bpy.context.selected_objects]
    header = {
        "scene": scene.name,
        "object_counts": counts,
        "selected": selected[:5],
        "selected_count": len(selected),
        "active": active.name if active else None,
        "mode": bpy.context.mode,
    }
    if "settings" in F:
        world = scene.world
        hdri = None
        if world and world.use_nodes:
            for n in world.node_tree.nodes:
                if n.type == "TEX_ENVIRONMENT" and n.image:
                    hdri = n.image.name
        header["settings"] = {
            "file": bpy.data.filepath or "(unsaved)",
            "engine": scene.render.engine,
            "frames": [scene.frame_start, scene.frame_end, scene.frame_current],
            "fps": scene.render.fps,
            "resolution": [scene.render.resolution_x, scene.render.resolution_y],
            "camera": scene.camera.name if scene.camera else None,
            "world_hdri": hdri,
            "unit_scale": scene.unit_settings.scale_length,
        }
    return {"header": header, "lines": lines, "total": total, "shown": len(lines)}


def look(args: LookArgs) -> LookInfo | Failure:
    """Render the viewport, camera, angles, frames or an image to one PNG.

    Ported from the addon's LOOK script. The picture is written to args["filepath"]
    as a PNG; the returned dict is what the look tool parses, carrying "error"
    when it could not take the picture and the width, height and mode otherwise.
    The caller reads the file from that path separately.
    """
    import bpy
    import math
    import gpu
    import numpy as np
    from mathutils import Vector, Matrix

    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mode = args["mode"]
    max_size = int(args.get("max_size") or 768)

    if mode == "image":
        # An image in the file ("Render Result", a texture) or on disk. Float images and
        # render results go through save_render so the scene's view transform applies,
        # as it would to the final render; byte images are shown as they are.
        import os
        ref = args.get("image") or ""
        src = bpy.data.images.get(ref)
        temp = []  # images this look created, removed at the end
        if src is None:
            # A path comes from the server already resolved under its file roots,
            # so it is absolute; a relative or // path is a name not in the file.
            path = ref
            if not os.path.isabs(path) or not os.path.isfile(path):
                return {"error": f"No image named {ref!r} in the file and no file at {path!r}"}
            try:
                src = bpy.data.images.load(path, check_existing=False)
            except Exception as e:
                return {"error": f"Couldn't load {path!r} as an image: {e}"}
            temp.append(src)
        out = args["filepath"]
        settings = scene.render.image_settings
        saved_settings = [(a, getattr(settings, a)) for a in ("file_format", "color_mode", "color_depth")]
        try:
            if src.type == "RENDER_RESULT" or src.is_float:
                settings.file_format = "PNG"
                settings.color_mode = "RGBA"
                settings.color_depth = "8"
                try:
                    src.save_render(out, scene=scene)
                except Exception as e:
                    return {"error": f"Couldn't read {src.name!r}" + (" (nothing rendered yet?)" if src.type == "RENDER_RESULT" else "") + f": {e}"}
                img = bpy.data.images.load(out, check_existing=False)
                temp.append(img)
            elif src in temp:
                img = src
            else:
                img = src.copy()  # never resize the user's own image
                temp.append(img)
            w0, h0 = img.size
            if not w0 or not h0:
                return {"error": f"{src.name!r} has no pixels"}
            s = min(1.0, max_size / max(w0, h0))
            if s < 1.0:
                img.scale(max(1, int(w0 * s)), max(1, int(h0 * s)))
            img.filepath_raw = out
            img.file_format = "PNG"
            img.save()
            w, h = img.size
        finally:
            for attr, value in saved_settings:
                try:
                    setattr(settings, attr, value)
                except Exception:
                    pass
            for im in temp:
                try:
                    bpy.data.images.remove(im)
                except Exception:
                    pass
        return {"mode": "image", "image": ref, "original_size": [w0, h0], "width": w, "height": h}

    area = space = region = None
    for a in bpy.context.screen.areas:
        if a.type == "VIEW_3D":
            area, space = a, a.spaces.active
            region = next((rg for rg in a.regions if rg.type == "WINDOW"), None)
            break
    if region is None:
        return {"error": "No 3D viewport is open in Blender"}

    names = args.get("target") or []
    if names:
        missing = [n for n in names if n not in bpy.data.objects]
        if missing:
            return {"error": "No object named " + ", ".join(repr(m) for m in missing)}
        targets = []

        def add(o: Object) -> None:
            if o not in targets:
                targets.append(o)
                for c in o.children:
                    add(c)

        for n in names:
            add(bpy.data.objects[n])
    else:
        targets = [o for o in scene.objects if o.visible_get() and o.type not in {"CAMERA", "LIGHT"}]

    def world_points(objs: Iterable[Object]) -> list[Vector]:
        pts = []
        for o in objs:
            if o.type in {"EMPTY"} and not o.children:
                pts.append(o.matrix_world.translation.copy())
                continue
            try:
                ev = o.evaluated_get(depsgraph)
                pts.extend(ev.matrix_world @ Vector(c) for c in ev.bound_box)
            except Exception:
                pts.append(o.matrix_world.translation.copy())
        return pts

    pts = world_points(targets) or [Vector((0, 0, 0))]
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    center = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 0.05)

    FOV = math.radians(35)

    def perspective(aspect: float, near: float, far: float) -> Matrix:
        f = 1 / math.tan(FOV / 2)
        return Matrix((
            (f / aspect, 0, 0, 0),
            (0, f, 0, 0),
            (0, 0, (far + near) / (near - far), 2 * far * near / (near - far)),
            (0, 0, -1, 0),
        ))

    def orbit(direction: Sequence[float], aspect: float) -> tuple[Matrix, Matrix]:
        direction = Vector(direction).normalized()
        fit = FOV / 2 if aspect >= 1 else math.atan(math.tan(FOV / 2) * aspect)
        dist = float(args.get("distance") or 0) or radius / math.sin(fit) * 1.1
        eye = center + direction * dist
        # The camera looks down its local -Z with local Y up; to_track_quat keeps
        # that Y as close to world Z as the direction allows, so the horizon stays level.
        rot = (center - eye).to_track_quat("-Z", "Y").to_matrix().to_4x4()
        view = (Matrix.Translation(eye) @ rot).inverted()
        return view, perspective(aspect, max(dist - radius * 3, dist * 0.01), dist + radius * 3)

    ANGLES = {
        "front": (0, -1, 0), "back": (0, 1, 0), "right": (1, 0, 0), "left": (-1, 0, 0),
        # Top is tilted a hair toward -Y so "up" in the image is +Y, as in Blender's top view.
        "top": (0, -0.001, 1), "three_quarter": (1, -1, 0.7),
    }

    def direction_of(v: object) -> tuple[float, ...] | None:
        """A named angle, or any [x, y, z] direction from the target towards the eye."""
        if isinstance(v, str):
            return ANGLES.get(v)
        if isinstance(v, (list, tuple)) and len(v) == 3 and any(v):
            return tuple(float(c) for c in v)
        return None

    def label(v: str | Sequence[float]) -> str:
        return v if isinstance(v, str) else "(" + ", ".join(f"{float(c):g}" for c in v) + ")"

    def current_view() -> tuple[Matrix, Matrix]:
        r3d = space.region_3d
        return r3d.view_matrix.copy(), r3d.window_matrix.copy()

    def camera_view(w: int, h: int) -> tuple[Matrix, Matrix] | None:
        cam = scene.camera
        if cam is None:
            return None
        win = cam.calc_matrix_camera(depsgraph, x=w, y=h,
                                     scale_x=scene.render.pixel_aspect_x, scale_y=scene.render.pixel_aspect_y)
        return cam.matrix_world.inverted(), win

    def draw(view: Matrix, win: Matrix, w: int, h: int) -> np.ndarray:
        off = gpu.types.GPUOffScreen(w, h)
        try:
            off.draw_view3d(scene, bpy.context.view_layer, space, region, view, win,
                            do_color_management=True)
            buf = off.texture_color.read()
        finally:
            off.free()
        buf.dimensions = w * h * 4
        return np.asarray(buf, dtype=np.float32).reshape(h, w, 4) / 255.0

    def sheet(tiles: Sequence[np.ndarray], cols: int) -> np.ndarray:
        h, w = tiles[0].shape[:2]
        rows = math.ceil(len(tiles) / cols)
        gap = 4
        out = np.ones((rows * h + (rows - 1) * gap, cols * w + (cols - 1) * gap, 4), dtype=np.float32)
        out[..., :3] = 0.08
        # Blender images are stored bottom row first, so the first tile goes top-left.
        for i, t in enumerate(tiles):
            r, c = divmod(i, cols)
            y = (rows - 1 - r) * (h + gap)
            x = c * (w + gap)
            out[y:y + h, x:x + w] = t
        return out

    # Settings each mode changes, restored afterwards.
    shading, overlay = space.shading, space.overlay
    saved = []

    def set_attr(obj: object, attr: str, value: object) -> None:
        if not hasattr(obj, attr):
            return
        saved.append((obj, attr, getattr(obj, attr)))
        try:
            setattr(obj, attr, value)
        except Exception:
            saved.pop()

    requested = args.get("shading")
    shading_types = {"solid": "SOLID", "material": "MATERIAL", "rendered": "RENDERED", "wireframe": "SOLID", "xray": "SOLID"}
    if requested:
        set_attr(shading, "type", shading_types[requested])

    info = {"mode": mode, "targets": len(targets), "center": [round(v, 2) for v in center],
            "size": [round(v, 2) for v in (hi - lo)]}

    if mode != "viewport":
        # The 3D cursor, light and camera gizmos and parent lines sit across generated views
        # and read as part of the scene.
        set_attr(overlay, "show_cursor", False)
        set_attr(overlay, "show_extras", False)
        set_attr(overlay, "show_relationship_lines", False)
        if mode == "camera" or args.get("view") == "camera" or shading.type in {"RENDERED", "MATERIAL"}:
            # Grid, light and camera gizmos aren't part of what's being judged.
            set_attr(overlay, "show_overlays", False)
        engine = scene.render.engine
        if shading.type == "RENDERED" and "EEVEE" not in engine and engine != "BLENDER_WORKBENCH":
            # Progressive engines like Cycles draw nothing into an offscreen view.
            return {"error": f"Rendered shading can't be captured with {engine}. Render and look at "
                             "image=\"Render Result\", use material shading, or switch the engine."}
    frame_before = scene.frame_current

    try:
        if requested == "wireframe":
            # Edges over a plain matcap surface: topology and form in one picture.
            set_attr(shading, "light", "MATCAP")
            set_attr(shading, "color_type", "SINGLE")
            set_attr(overlay, "show_overlays", True)
            set_attr(overlay, "show_wireframes", True)
            set_attr(overlay, "wireframe_threshold", 1.0)
        elif requested == "xray":
            set_attr(shading, "show_xray", True)
            set_attr(shading, "xray_alpha", 0.35)
            set_attr(overlay, "show_overlays", True)
            set_attr(overlay, "show_bones", True)
            rigs = {o for o in targets if o.type == "ARMATURE"}
            rigs |= {m.object for o in targets for m in getattr(o, "modifiers", [])
                     if m.type == "ARMATURE" and m.object}
            for o in rigs:
                set_attr(o, "show_in_front", True)

        if mode == "viewport":
            w, h = region.width, region.height
            s = min(1.0, max_size / max(w, h))
            w, h = max(1, int(w * s)), max(1, int(h * s))
            view, win = current_view()
            image = draw(view, win, w, h)
        elif mode == "camera":
            rx, ry = scene.render.resolution_x, scene.render.resolution_y
            s = max_size / max(rx, ry)
            w, h = max(1, int(rx * s)), max(1, int(ry * s))
            cv = camera_view(w, h)
            if cv is None:
                return {"error": "The scene has no camera. Add one or use mode='angles'."}
            info["camera"] = scene.camera.name
            image = draw(cv[0], cv[1], w, h)
        elif mode == "frames":
            start, end = scene.frame_start, scene.frame_end
            frames = args.get("frames") or []
            if not frames:
                n = max(2, min(int(args.get("frame_count") or 6), 12))
                frames = sorted({round(start + (end - start) * i / (n - 1)) for i in range(n)})
            frames = frames[:12]
            cols = 3 if len(frames) > 4 else 2
            w = max(64, max_size // cols)
            h = int(w * 0.75)
            use_camera = scene.camera is not None and args.get("view") == "camera"
            tiles = []
            for f in frames:
                scene.frame_set(int(f))
                if use_camera:
                    view, win = camera_view(w, h)
                elif direction_of(args.get("view")):
                    view, win = orbit(direction_of(args["view"]), w / h)
                else:
                    view, win = current_view()
                tiles.append(draw(view, win, w, h))
            info["frames"] = [int(f) for f in frames]
            image = sheet(tiles, cols)
        else:
            views = args.get("views") or ["front", "right", "top", "three_quarter"]
            views = [v for v in views if direction_of(v)][:6] or ["three_quarter"]
            cols = 1 if len(views) == 1 else (3 if len(views) > 4 else 2)
            w = max(64, max_size // cols)
            h = w
            tiles = [draw(*orbit(direction_of(v), 1.0), w, h) for v in views]
            info["views"] = [label(v) for v in views]
            image = sheet(tiles, cols)
    finally:
        if scene.frame_current != frame_before:
            scene.frame_set(frame_before)
        for obj, attr, value in reversed(saved):
            try:
                setattr(obj, attr, value)
            except Exception:
                pass

    h, w = image.shape[:2]
    img = bpy.data.images.new("mcp_look", w, h, alpha=True)
    try:
        img.pixels.foreach_set(image.ravel())
        img.filepath_raw = args["filepath"]
        img.file_format = "PNG"
        img.save()
    finally:
        bpy.data.images.remove(img)
    info["width"], info["height"] = w, h
    return info


def bounds(args: BoundsArgs) -> list[ObjectBounds]:
    """Bounding box of freshly imported objects: name, world_bounding_box, size.

    Ported from the addon's BOUNDS script. The returned list is what the
    generation success reply reads at /0/name and /0/world_bounding_box/...
    """
    import bpy
    from mathutils import Vector

    dg = bpy.context.evaluated_depsgraph_get()
    out = []
    for name in args["names"]:
        o = bpy.data.objects.get(name)
        if o is None:
            continue
        objs = [o] + list(o.children_recursive)
        pts = []
        for x in objs:
            if x.type in {"MESH", "CURVE", "SURFACE", "FONT", "META", "CURVES", "POINTCLOUD", "VOLUME"}:
                ev = x.evaluated_get(dg)
                pts.extend(ev.matrix_world @ Vector(c) for c in ev.bound_box)
        if not pts:
            continue
        lo = [round(min(p[i] for p in pts), 3) for i in range(3)]
        hi = [round(max(p[i] for p in pts), 3) for i in range(3)]
        out.append({"name": o.name, "world_bounding_box": [lo, hi],
                    "size": [round(hi[i] - lo[i], 3) for i in range(3)]})
    return out


def scene_items(args: SceneItemsArgs) -> SceneItems:
    """Objects, materials and collections whose names contain the query.

    Ported from the addon's list_scene_items. Names that start with the query
    rank before ones that merely contain it, and only names and cheap counts are
    read, so it stays quick on a large file.
    """
    import bpy

    needle = (args.get("query") or "").strip().lower()
    limit = max(1, min(int(args.get("limit") or 30), 200))

    material_users: dict[str, list[str]] = {}
    for obj in bpy.context.scene.objects:
        for slot in getattr(obj, "material_slots", None) or []:
            if slot.material:
                material_users.setdefault(slot.material.name, []).append(obj.name)

    candidates: list[SceneItem] = []
    for obj in bpy.context.scene.objects:
        detail = "%s object" % obj.type.title()
        if obj.users_collection:
            detail += " in collection '%s'" % obj.users_collection[0].name
        candidates.append({"kind": "object", "name": obj.name, "detail": detail})
    for mat in bpy.data.materials:
        users = material_users.get(mat.name, [])
        if users:
            shown = ", ".join(users[:3]) + (" and %d more" % (len(users) - 3) if len(users) > 3 else "")
            detail = "Material on " + shown
        else:
            detail = "Material not used by any object in this scene"
        candidates.append({"kind": "material", "name": mat.name, "detail": detail})
    for coll in bpy.data.collections:
        candidates.append({"kind": "collection", "name": coll.name, "detail": "Collection with %d objects" % len(coll.all_objects)})

    ranked: list[tuple[int, int, SceneItem]] = []
    for order, item in enumerate(candidates):
        lowered = item["name"].lower()
        if needle and needle not in lowered:
            continue
        ranked.append((0 if not needle or lowered.startswith(needle) else 1, order, item))
    ranked.sort(key=lambda entry: (entry[0], entry[1]))
    return {"items": [entry[2] for entry in ranked[:limit]], "total": len(ranked)}


def object_info(args: ObjectInfoArgs) -> ObjectInfo | Failure:
    """One object's name, type, transform, visibility and materials, and for a
    mesh its world bounding box and counts. Ported from the addon's
    get_object_info."""
    import bpy
    from mathutils import Vector

    name = args.get("name") or ""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return {"error": "Object not found: %s" % name}
    info: ObjectInfo = {
        "name": obj.name,
        "type": obj.type,
        "location": list(obj.location),
        "rotation": list(obj.rotation_euler),
        "scale": list(obj.scale),
        "visible": bool(obj.visible_get()),
        "materials": [slot.material.name for slot in obj.material_slots if slot.material],
    }
    if obj.type == "MESH":
        corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        info["world_bounding_box"] = [[min(c[i] for c in corners) for i in range(3)],
                                      [max(c[i] for c in corners) for i in range(3)]]
        mesh = obj.data
        info["mesh"] = {"vertices": len(mesh.vertices), "edges": len(mesh.edges), "polygons": len(mesh.polygons)}
    return info


def viewport_screenshot(args: ViewportArgs) -> ViewportShot | Failure:
    """The open 3D viewport as it is drawn, written as a PNG to args["filepath"]
    with its longest side at most max_size. Ported from the addon's
    get_viewport_screenshot: it draws offscreen, so it works while Blender's
    window sits behind others, and grabs the window instead when there is no
    GPU context. No setting is changed; look is the tool that changes them."""
    import bpy

    filepath = args.get("filepath") or ""
    if filepath == "":
        return {"error": "viewport_screenshot needs a filepath"}
    max_size = max(64, int(args.get("max_size") or 800))
    area = next((a for a in bpy.context.screen.areas if a.type == "VIEW_3D"), None)
    if area is None:
        return {"error": "No 3D viewport is open in Blender"}
    space = area.spaces.active
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    if space is None or region is None:
        return {"error": "No 3D viewport is open in Blender"}

    try:
        import gpu
        import numpy

        r3d = space.region_3d
        scale = min(1.0, max_size / max(region.width, region.height))
        width, height = max(1, int(region.width * scale)), max(1, int(region.height * scale))
        offscreen = gpu.types.GPUOffScreen(width, height)
        try:
            offscreen.draw_view3d(bpy.context.scene, bpy.context.view_layer, space, region,
                                  r3d.view_matrix, r3d.window_matrix, do_color_management=True)
            buf = offscreen.texture_color.read()
        finally:
            offscreen.free()
        buf.dimensions = width * height * 4
        pixels = numpy.asarray(buf, dtype=numpy.float32) / 255.0  # the GPU buffer is 0..255
        image = bpy.data.images.new("mcp_viewport", width, height, alpha=True)
        try:
            image.pixels.foreach_set(pixels.ravel())
            image.filepath_raw = filepath
            image.file_format = "PNG"
            image.save()
        finally:
            bpy.data.images.remove(image)
    except Exception as exc:
        print("viewport_screenshot: offscreen capture failed (%s); grabbing the window" % exc)
        with bpy.context.temp_override(area=area):
            bpy.ops.screen.screenshot_area(filepath=filepath)
        image = bpy.data.images.load(filepath)
        try:
            width, height = image.size
            if max(width, height) > max_size:
                scale = max_size / max(width, height)
                width, height = max(1, int(width * scale)), max(1, int(height * scale))
                image.scale(width, height)
                image.save()
        finally:
            bpy.data.images.remove(image)
    return {"width": width, "height": height, "filepath": filepath,
            "file": bpy.data.filepath, "scene": bpy.context.scene.name}


# --- Assets: importing what rust/blender_assets.rs downloaded ---
#
# The server does every network call and the download (asset_fetch), into a
# folder under the write roots; these functions only read files on disk. Ported
# from the mcp-for-blender add-on's Poly Haven, Sketchfab and Poly Pizza
# handlers. Every new image is packed into the .blend, and the download folder is
# deleted, so the file the user saves does not point at a folder that is gone.

DOWNLOAD_PREFIX = "mcp-asset-"  # rust/blender_assets.rs names its folders so; nothing else is deleted

COLOR_ROLES = {"base_color"}  # only the albedo is colour data; every other map is values


def _remove_download(folder: str) -> None:
    import os
    import shutil

    if folder and os.path.basename(os.path.normpath(folder)).startswith(DOWNLOAD_PREFIX):
        shutil.rmtree(folder, ignore_errors=True)


def _set_colorspace(image: Any, is_color: bool) -> str:
    """Set a colourspace that exists on this build: the names moved in 4.0."""
    for name in (("sRGB",) if is_color else ("Non-Color", "Linear Rec.709", "Linear")):
        try:
            image.colorspace_settings.name = name
            return name
        except Exception:
            continue
    return str(image.colorspace_settings.name)


def _tag(blocks: Iterable[Any], manifest: AssetManifest) -> None:
    """Record where a datablock came from, in the .blend that keeps it: the
    source's id, page, licence, authors and attribution, as <source>_* custom
    properties (polyhaven_id and so on, the names the old add-on wrote). 69% of
    Poly Pizza is CC-BY, so the credit has to outlive the session."""
    prefix = manifest.get("source") or "asset"
    fields = {"id": manifest.get("id"), "url": manifest.get("url"), "licence": manifest.get("licence"),
              "resolution": manifest.get("resolution"), "attribution": manifest.get("attribution")}
    authors = ", ".join(manifest.get("authors") or [])
    for block in blocks:
        if block is None:
            continue
        try:
            for field, value in fields.items():
                if value:
                    block["%s_%s" % (prefix, field)] = str(value)
            if authors:
                block["%s_authors" % prefix] = authors
            elif "%s_authors" % prefix in block.keys():
                # Never leave a previous asset's artist credited on a re-tagged block.
                del block["%s_authors" % prefix]
        except Exception:
            pass


def _credits(manifest: AssetManifest) -> AssetImported:
    return {"source": manifest.get("source") or "", "id": manifest.get("id") or "",
            "authors": list(manifest.get("authors") or []), "url": manifest.get("url"),
            "licence": manifest.get("licence"), "attribution": manifest.get("attribution")}


def _import_hdri(manifest: AssetManifest) -> AssetImported:
    """A new world lit by the HDRI. A new one rather than clearing the scene's:
    the old world is left intact, just unused."""
    import bpy

    asset_id = manifest.get("id") or "hdri"
    world = bpy.data.worlds.new("PolyHaven %s" % asset_id)
    bpy.context.scene.world = world
    world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()
    coord = tree.nodes.new(type="ShaderNodeTexCoord")
    coord.location = (-800, 0)
    mapping = tree.nodes.new(type="ShaderNodeMapping")
    mapping.location = (-600, 0)
    env = tree.nodes.new(type="ShaderNodeTexEnvironment")
    env.location = (-400, 0)
    env.image = bpy.data.images.load(manifest["path"], check_existing=True)
    env.image.name = "%s_%s" % (asset_id, manifest.get("resolution") or "")
    # The loader already tags .hdr/.exr as scene-linear; it is left as it is.
    background = tree.nodes.new(type="ShaderNodeBackground")
    background.location = (-200, 0)
    output = tree.nodes.new(type="ShaderNodeOutputWorld")
    output.location = (0, 0)
    tree.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
    tree.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
    tree.links.new(env.outputs["Color"], background.inputs["Color"])
    tree.links.new(background.outputs["Background"], output.inputs["Surface"])
    _tag([world, env.image], manifest)
    result = _credits(manifest)
    result.update({"message": "HDRI %s is now the scene's world" % asset_id, "world": world.name, "image": env.image.name})
    return result


def _build_material(name: str, maps: Mapping[str, tuple[str, Any]]) -> tuple[Any, list[str]]:
    """A Principled material from {map key: (role, image)}: every image node fed
    through one Mapping node (POINT, as Poly Haven authors its own), the normal
    map through a Normal Map node, displacement through a Displacement node."""
    import bpy

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    output = nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (600, 0)
    principled = nodes.new(type="ShaderNodeBsdfPrincipled")
    principled.location = (300, 0)
    links.new(principled.outputs[0], output.inputs["Surface"])
    coord = nodes.new(type="ShaderNodeTexCoord")
    coord.location = (-1000, 0)
    mapping = nodes.new(type="ShaderNodeMapping")
    mapping.location = (-800, 0)
    mapping.vector_type = "POINT"
    links.new(coord.outputs["UV"], mapping.inputs["Vector"])

    y = 300
    wired: list[str] = []
    for key, (role, image) in maps.items():
        tex = nodes.new(type="ShaderNodeTexImage")
        tex.location = (-500, y)
        tex.image = image
        _set_colorspace(image, role in COLOR_ROLES)
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        y -= 300
        if role == "base_color":
            links.new(tex.outputs["Color"], principled.inputs["Base Color"])
        elif role == "roughness":
            links.new(tex.outputs["Color"], principled.inputs["Roughness"])
        elif role == "metallic":
            links.new(tex.outputs["Color"], principled.inputs["Metallic"])
        elif role == "normal":
            normal = nodes.new(type="ShaderNodeNormalMap")
            normal.location = (-200, tex.location[1])
            links.new(tex.outputs["Color"], normal.inputs["Color"])
            links.new(normal.outputs["Normal"], principled.inputs["Normal"])
        elif role == "displacement":
            displace = nodes.new(type="ShaderNodeDisplacement")
            displace.location = (300, tex.location[1])
            # Poly Haven's height maps are centred on 0.5.
            displace.inputs["Midlevel"].default_value = 0.5
            displace.inputs["Scale"].default_value = 0.1
            links.new(tex.outputs["Color"], displace.inputs["Height"])
            links.new(displace.outputs["Displacement"], output.inputs["Displacement"])
            # Moved off material.cycles in 4.1.
            if hasattr(mat, "displacement_method"):
                mat.displacement_method = "BOTH"
            else:
                try:
                    mat.cycles.displacement_method = "BOTH"
                except Exception:
                    pass
        else:
            continue
        wired.append(key)
    return mat, wired


def _import_texture(manifest: AssetManifest, apply_to: Sequence[str]) -> AssetImported:
    """Load the maps, build one material, and give each named object its own
    material built from the same images (replacing its slots)."""
    import bpy

    asset_id = manifest.get("id") or "texture"
    maps: dict[str, tuple[str, Any]] = {}
    for entry in manifest.get("maps") or []:
        image = bpy.data.images.load(entry["path"], check_existing=True)
        image.name = "%s_%s" % (asset_id, entry["key"])
        _set_colorspace(image, entry["role"] in COLOR_ROLES)
        image["polyhaven_map"] = entry["key"]
        image["polyhaven_role"] = entry["role"]
        maps[entry["key"]] = (entry["role"], image)
    mat, wired = _build_material(asset_id, maps)
    _tag([mat] + [image for _role, image in maps.values()], manifest)
    dimensions = manifest.get("dimensions_mm")
    if dimensions:
        mat["polyhaven_scale_mm"] = list(dimensions)

    applied: dict[str, str] = {}
    missed: dict[str, str] = {}
    for name in apply_to:
        obj = bpy.data.objects.get(name)
        if obj is None:
            missed[name] = "no object by that name"
            continue
        if not hasattr(obj, "data") or not hasattr(obj.data, "materials"):
            missed[name] = "a %s object cannot take a material" % obj.type
            continue
        material_name = "%s_material_%s" % (asset_id, name)
        old = bpy.data.materials.get(material_name)
        if old is not None:
            bpy.data.materials.remove(old)
        own, _wired = _build_material(material_name, maps)
        own.name = material_name
        _tag([own], manifest)
        while len(obj.data.materials) > 0:
            obj.data.materials.pop(index=0)
        obj.data.materials.append(own)
        applied[name] = own.name

    mapping = next((n for n in mat.node_tree.nodes if n.type == "MAPPING"), None)
    result = _credits(manifest)
    message = "Texture %s imported as material %s" % (asset_id, mat.name)
    if applied:
        message += ", applied to %s (their material slots replaced)" % ", ".join(applied)
    result.update({"message": message, "material": mat.name, "maps": wired, "applied_to": applied,
                   "not_applied": missed, "scale_mm": list(dimensions) if dimensions else None,
                   "mapping_node": None if mapping is None else mapping.name})
    return result


def _blend_version(path: str) -> tuple[int, int] | None:
    """(major, minor) of the Blender that wrote a .blend, or None. The header is
    BLENDER-v293 up to 4.4 and BLENDER17-01v0502 from 4.5; files are usually
    gzip (to 2.93) or zstd (from 3.0) compressed."""
    import zlib

    try:
        with open(path, "rb") as f:
            raw = f.read(1 << 16)
    except OSError:
        return None
    head: bytes | None = raw
    if raw[:2] == b"\x1f\x8b":
        try:
            head = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw)
        except Exception:
            head = None
    elif raw[:7] != b"BLENDER":
        try:
            import zstandard  # not in every Blender build
            head = zstandard.ZstdDecompressor().decompressobj().decompress(raw)
        except Exception:
            head = None
    if not head or not head.startswith(b"BLENDER"):
        return None
    try:
        if head[7:9].isdigit():
            return int(head[13:15]), int(head[15:17])
        return int(head[9:10]), int(head[10:12])
    except (ValueError, IndexError):
        return None


def _append_blend(path: str, asset_id: str) -> list[Any]:
    """Append the asset's own collection (<slug>_LOD0, else <slug>) out of a Poly
    Haven .blend, rather than every object in the file."""
    import bpy

    with bpy.data.libraries.load(path, link=False) as (data_from, data_to):
        available = list(data_from.collections)
        wanted = next((n for n in ("%s_LOD0" % asset_id, asset_id) if n in available), None)
        if wanted:
            data_to.collections = [wanted]
        else:
            data_to.objects = data_from.objects
    linked = []
    for collection in data_to.collections:
        if collection is not None:
            bpy.context.scene.collection.children.link(collection)
            linked.append(collection)
    if not linked:
        for obj in data_to.objects:
            if obj is not None:
                bpy.context.collection.objects.link(obj)
    return linked


def _extract(archive: str, into: str) -> str:
    """Unzip a Sketchfab archive, refusing any entry that would land outside the
    folder or a total over 4 GiB, and return its shallowest .gltf or .glb."""
    import os
    import zipfile

    root = os.path.realpath(into)
    with zipfile.ZipFile(archive) as z:
        total = 0
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            target = os.path.realpath(os.path.join(root, name))
            if name.startswith("/") or ".." in name.split("/") or not (target == root or target.startswith(root + os.sep)):
                raise ValueError("the archive holds an unsafe path %r" % info.filename)
            total += info.file_size
        if total > 4 * 1024 ** 3:
            raise ValueError("the archive unpacks to more than 4 GiB")
        z.extractall(root)
    found = []
    for folder, _dirs, files in os.walk(root):
        found.extend(os.path.join(folder, f) for f in files if f.lower().endswith((".gltf", ".glb")))
    if not found:
        raise ValueError("no glTF file in the downloaded archive")
    found.sort(key=lambda p: (p.count(os.sep), p))
    return found[0]


def _fit(objects: Sequence[Object], target_size: float) -> tuple[list[list[float]] | None, list[float] | None, float]:
    """World bounding box and size of the meshes under these objects; with a
    target size, scale the root objects (children follow) so the largest
    dimension matches it first. Returns (box, dimensions, scale applied)."""
    import bpy
    from mathutils import Vector

    names = {o.name for o in objects}
    roots = [o for o in objects if o.parent is None or o.parent.name not in names]
    meshes: list[Object] = []

    def collect(obj: Object) -> None:
        if obj.type == "MESH":
            meshes.append(obj)
        for child in obj.children:
            collect(child)

    for root in roots:
        collect(root)
    if not meshes:
        return None, None, 1.0

    def box() -> tuple[list[float], list[float]]:
        lo = [float("inf")] * 3
        hi = [float("-inf")] * 3
        for mesh in meshes:
            for corner in mesh.bound_box:
                world = mesh.matrix_world @ Vector(corner)
                for i in range(3):
                    lo[i] = min(lo[i], world[i])
                    hi[i] = max(hi[i], world[i])
        return lo, hi

    lo, hi = box()
    scale = 1.0
    largest = max(hi[i] - lo[i] for i in range(3))
    if target_size > 0 and largest > 0:
        scale = target_size / largest
        for root in roots:
            root.scale = (root.scale.x * scale, root.scale.y * scale, root.scale.z * scale)
        bpy.context.view_layer.update()
        lo, hi = box()
    return ([[round(v, 4) for v in lo], [round(v, 4) for v in hi]],
            [round(hi[i] - lo[i], 4) for i in range(3)], round(scale, 6))


def _import_model(manifest: AssetManifest, target_size: float) -> AssetImported | AssetFallback | Failure:
    """A Poly Haven model (.blend appended, or glTF), a Sketchfab archive or a
    Poly Pizza .glb, scaled to target_size when one is given."""
    import bpy

    kind = manifest.get("kind")
    path = manifest.get("path") or ""
    before = {o.name for o in bpy.data.objects}
    collections: list[Any] = []
    if kind == "model" and (manifest.get("format") or "blend") == "blend":
        written_by = _blend_version(path)
        if written_by and written_by > tuple(bpy.app.version[:2]):
            return {"fallback": "written by Blender %d.%d" % written_by}
        try:
            collections = _append_blend(path, manifest.get("id") or "")
        except Exception as exc:
            return {"fallback": "could not be appended (%s)" % exc}
    else:
        if kind == "archive":
            path = _extract(path, manifest.get("dir") or "")
        bpy.ops.import_scene.gltf(filepath=path)

    imported = [o for o in bpy.data.objects if o.name not in before]
    if not imported:
        return {"error": "Imported %s but nothing arrived in the scene" % (manifest.get("id") or "the asset")}
    materials: list[Any] = []
    for obj in imported:
        for slot in getattr(obj, "material_slots", []):
            if slot.material is not None and slot.material not in materials:
                materials.append(slot.material)
    names = {o.name for o in imported}
    roots = [o for o in imported if o.parent is None or o.parent.name not in names]
    _tag((roots if kind != "model" else imported) + collections + materials, manifest)
    bbox, dimensions, scale = _fit(imported, target_size)
    result = _credits(manifest)
    label = manifest.get("name") or manifest.get("id") or "the model"
    result.update({"message": "Imported %s: %d object(s); check world_bounding_box and put it on the ground" % (label, len(imported)),
                   "imported_objects": [o.name for o in imported], "world_bounding_box": bbox,
                   "dimensions": dimensions, "scale_applied": scale})
    return result


@undoable
def import_asset(args: ImportAssetArgs) -> AssetImported | AssetFallback | Failure:
    """Bring one downloaded asset into the scene: an HDRI as the world, a texture
    as a material (and on the apply_to objects), or a model scaled to
    target_size. Every new image is packed into the .blend, then the download
    folder is deleted, whatever happened."""
    import bpy

    manifest: AssetManifest = args.get("manifest") or {}
    kind = manifest.get("kind")
    images_before = set(bpy.data.images)
    try:
        result: AssetImported | AssetFallback | Failure
        if kind == "hdri":
            result = _import_hdri(manifest)
        elif kind == "texture":
            result = _import_texture(manifest, args.get("apply_to") or [])
        elif kind in ("model", "archive", "glb"):
            result = _import_model(manifest, float(args.get("target_size") or 0.0))
        else:
            return {"error": "unknown asset kind %r" % (kind,)}
        for image in set(bpy.data.images) - images_before:
            try:
                if image.source == "FILE" and image.packed_file is None:
                    image.pack()
            except Exception:
                pass
        note = args.get("note") or ""
        if note and "message" in result:
            imported = cast("AssetImported", result)
            imported["message"] = imported.get("message", "") + note
        return result
    finally:
        _remove_download(manifest.get("dir") or "")


if __name__ == "__main__":
    import json
    import sys

    entries: dict[str, Callable[[Any], object]] = {"reveal": reveal, "text": text, "place": place, "material": material,
               "render": render, "render_animation": render_animation, "export": export, "remove": remove, "duplicate": duplicate,
               "array": array, "boolean": boolean, "aim": aim, "light": light, "wireframe": wireframe,
               "mesh_report": mesh_report, "image_report": image_report, "modifier": modifier,
               "scene_summary": scene_summary, "look": look, "bounds": bounds,
               "scene_items": scene_items, "object_info": object_info, "viewport_screenshot": viewport_screenshot,
               "import_asset": import_asset}
    wanted = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = sys.argv[2] if len(sys.argv) > 2 else "{}"
    if wanted not in entries:
        print("usage: blender --background --python mcp_scripts.py -- NAME '{...}'")
        print("known: " + ", ".join(sorted(entries)))
    else:
        print(json.dumps(entries[wanted](json.loads(payload)), indent=2, sort_keys=True))

