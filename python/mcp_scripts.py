"""The Blender-side scripts the MCP tools run.

Each function takes the tool's arguments as a dict and returns a dict whose
"report" holds the text. The server ships this whole file to Blender once per
content hash, then calls one function by name (run_module in blender.rmcp.rb).
This is a real module rather than a string constant: it can be linted, imported
and reviewed, and a traceback out of Blender names a line in this file.

One entry point by hand, with no server and no bridge:

    blender --background --python python/mcp_scripts.py -- reveal '{"name": "Chair"}'
"""

def push_step(message):
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


def undoable(fn):
    """Wrap an entry point so it opens an undo step before it changes anything."""
    import functools

    @functools.wraps(fn)
    def wrapped(args):
        subject = args.get("name") or args.get("names") or args.get("target") or args.get("file") or ""
        if isinstance(subject, (list, tuple)):
            subject = ", ".join(str(s) for s in subject[:3])
        push_step("%s: %s" % (fn.__name__, subject) if str(subject) != "" else fn.__name__)
        return fn(args)

    return wrapped


@undoable
def reveal(args):
    import bpy

    # Why an object is not on screen is a property of the view and the view layer,
    # not of the object. This reports both, clears the traps it finds, and frames
    # the object so the next screenshot has something in it.

    name = (args.get("name") or "").strip()
    want_frame = args.get("frame")
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

@undoable
def text(args):
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
def place(args):
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

    def want(key):
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
def material(args):
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
def render(args):
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
    return {"path": path, "report": "\n".join(lines)}

@undoable
def export(args):
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
def remove(args):
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


def look_at_rotation(location, point):
    """A camera-style rotation (looking along -Z, +Y up) from a position to a point."""
    from mathutils import Vector

    direction = Vector(point) - Vector(location)
    if direction.length < 1e-6:
        return (0.0, 0.0, 0.0)
    return tuple(direction.to_track_quat("-Z", "Y").to_euler())


def bounds_of(objects):
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


def view_direction(view, distance):
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
def duplicate(args):
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
def array(args):
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
def boolean(args):
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
def aim(args):
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
def light(args):
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



def wireframe(args):
    """Draw a mesh as text: front, side or top edge projections at true proportions."""
    import bpy

    # Inputs from the MCP tool. ARGS is set on the module before _main() runs.
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

def mesh_report(args):
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

def image_report(args):
    """Describe an image as text: dimensions, aspect, mean and top colours, and two character grids."""
    import bpy, numpy as np

    source = args.get("source") or ""
    cols = max(40, min(int(args.get("width") or 116), 200))
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

@undoable
def modifier(args):
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

    def counted():
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


if __name__ == "__main__":
    import json
    import sys

    entries = {"reveal": reveal, "text": text, "place": place, "material": material,
               "render": render, "export": export, "remove": remove, "duplicate": duplicate,
               "array": array, "boolean": boolean, "aim": aim, "light": light, "wireframe": wireframe,
               "mesh_report": mesh_report, "image_report": image_report, "modifier": modifier}
    wanted = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = sys.argv[2] if len(sys.argv) > 2 else "{}"
    if wanted not in entries:
        print("usage: blender --background --python mcp_scripts.py -- NAME '{...}'")
        print("known: " + ", ".join(sorted(entries)))
    else:
        print(json.dumps(entries[wanted](json.loads(payload)), indent=2, sort_keys=True))
