# typed: true
server "blender", version: "0.2.0", instructions: "MCP for Blender drives the user's live Blender. The typed tools cover the everyday work; screenshot and look show you the result. execute_code runs Python there with the bpy API, guarded: import only bpy, bmesh, mathutils and pure-Python helpers (no os, open, subprocess, sockets or numpy), and every file path you hand Blender must sit under the server's roots. Write under BLENDER_WRITE_ROOTS (by default the directory the server runs in; a relative path lands under the first), read under those or BLENDER_READ_ROOTS. A refusal names the line and the rule; rewrite the script rather than working around it, and use render and export for output files.\n\nStart with scene_info.\n\nScripts run in someone else's Blender:\n- Look shader nodes up by type, never by name (names are localized): next(n for n in mat.node_tree.nodes if n.type == \"BSDF_PRINCIPLED\").\n- Never hardcode enum identifiers; read them, for example [i.identifier for i in bpy.types.RenderSettings.bl_rna.properties[\"file_format\"].enum_items]. scene.render.engine under-reports: read the current value, and assign a new one inside try/except TypeError, whose message lists the valid engines.\n- Material colors go on shader node inputs; material.diffuse_color only affects the viewport.\n\nlook is how you see your work; use it as much as you need. Images stay in the conversation, so a smaller max_size keeps long sessions cheap.\n\nObjects, materials and lighting can also come from existing libraries: search_assets, then import_asset (Poly Haven needs no account; Sketchfab and Poly Pizza need the user's API keys on this server). Imported models arrive at arbitrary scale: pass target_size, or use the reported world_bounding_box to size them, and put them on the ground." do
  use_bindings :json
  use_bindings :imagefile

  # The bridge to Blender lives in hand-written Rust beside this file: one
  # persistent connection to the MCP Bridge add-on (addon/mcp_bridge.py), one
  # command at a time, the reply back as JSON text.
  rust_file "rust/blender_bridge.rs", as: :blender_bridge
  rust_fn :blender_call, args: [:string, :i64, :string], returns: :string, from: :blender_bridge
  # The same call with the caller's own read timeout in seconds, for an operation
  # that legitimately outlives the default (a render, an animation, an import).
  # A timeout returns {"status":"timeout",...}, not the empty string that means
  # "unreachable", so a caller can tell "may still be running" from "no reply".
  rust_fn :blender_call_timeout, args: [:string, :i64, :string, :i64], returns: :string, from: :blender_bridge

  # Reading an image as text, but in Rust rather than inside Blender: the
  # arithmetic is unit-testable with cargo test and needs no Blender session.
  # The image crate is declared in bindings/imagefile.rb; dependencies land in
  # the crate's Cargo.toml, so this module can use it directly.
  rust_file "rust/textvision.rs", as: :textvision
  rust_fn :grid, args: [:string, :i32], returns: :string, from: :textvision
  rust_fn :ansi, args: [:string, :i32, :string, :string], returns: :string, from: :textvision

  # The path jail: every file path a tool takes is resolved in Rust, symlinks
  # followed, and refused unless it sits under a file root. canonicalize is
  # filesystem work the DSL cannot express, and the check has to see the path
  # as the OS will, not as the agent wrote it.
  rust_file "rust/blender_jail.rs", as: :blender_jail
  rust_fn :jail_path, args: [:string, :string, :string, :string], returns: :string, from: :blender_jail
  rust_fn :jail_roots, args: [:string], returns: :string, from: :blender_jail

  # The asset libraries (Poly Haven, Sketchfab, Poly Pizza): every network call
  # and download happens in this server, with the API keys from its environment
  # (BLENDERMCP_SKETCHFAB_API_KEY, BLENDERMCP_POLYPIZZA_API_KEY), and Blender only
  # imports files already on disk, through import_asset in python/mcp_scripts.py.
  rust_file "rust/blender_assets.rs", as: :blender_assets
  rust_fn :asset_search, args: [:string, :string, :string, :string, :string, :f64, :bool, :i64], returns: :string, from: :blender_assets
  rust_fn :asset_fetch, args: [:string, :string, :string, :string, :string, :string], returns: :string, from: :blender_assets

  setting :blender_host, env: "BLENDER_HOST", default: "localhost", description: "host of the Blender addon bridge"
  setting :blender_port, env: "BLENDER_PORT", default: "9876", description: "port of the Blender addon bridge"
  setting :write_roots, env: "BLENDER_WRITE_ROOTS", default: ".", description: "directories where tools and execute_code may write, and read; a list like PATH (':' between entries, ';' on Windows). A relative path lands under the first, and outputs default to its renders and exports folders. The default is the directory this server runs in"
  setting :read_roots, env: "BLENDER_READ_ROOTS", default: "", description: "extra directories tools and execute_code may read but not write, such as a texture library or the system fonts; a list like PATH. Empty by default"
  setting :code_policy, env: "BLENDER_CODE_POLICY", default: "guarded", description: "how execute_code runs: guarded (the default) checks the code with upstream's validator, then runs it with every file path held to the roots and no processes, network or native code; open runs it unchecked, as the user, with the whole filesystem in reach; off refuses it"
  setting :mcp_token, env: "MCP_TOKEN", secret: true, description: "bearer token every request to the HTTP transport must carry; required, so every run needs MCP_TOKEN set"
  setting :blender_python, env: "BLENDER_PYTHON", default: "python/mcp_scripts.py", description: "path to the Python module the scene and output tools run: a real module, read here and installed into Blender once per content hash"

  # One command over the bridge: send, check the addon's status, and return the
  # result as JSON text (helpers cannot carry an opaque Json::Value).
  helper :blender_request, args: [:string, :i64, :string], returns: :string do |host, port, request|
    resp = Json.parse(rust(:blender_call, host, port, request)) || raise("Blender bridge unreachable: start the MCP Bridge add-on (addon/mcp_bridge.py) in Blender's sidebar, and give this server its token as BLENDER_BRIDGE_TOKEN")
    status = Json.text(resp, "/status") || "error"
    raise (Json.text(resp, "/message") || "Blender returned an error") unless status == "success"
    Json.dump(Json.at(resp, "/result") || raise("the bridge returned no result")) || raise("could not encode the result")
  end

  # A path a tool was given, resolved under the file roots; a refusal is raised
  # as the jail worded it.
  helper :jail, args: [:string, :string, :string, :string], returns: :string do |path, write_roots, read_roots, mode|
    resolved = rust(:jail_path, path, write_roots, read_roots, mode)
    raise resolved if resolved.start_with?("refused:")
    resolved
  end

  # An image a tool takes by name or by path. A name has no slash and goes to
  # Blender as is, which only looks it up among the file's images; anything with
  # a slash, or a ~, is a path and goes through the jail.
  helper :image_ref, args: [:string, :string, :string], returns: :string do |name_or_path, write_roots, read_roots|
    if name_or_path.include?("/") || name_or_path.start_with?("~") then jail(name_or_path, write_roots, read_roots, "read") else name_or_path end
  end

  # The roots as a JSON list of resolved directories, for Blender: the guard
  # around execute_code compares against exactly the directories the jail does.
  helper :roots_json, args: [:string], returns: :string do |list|
    resolved = rust(:jail_roots, list)
    Json.str_list_json(resolved.split("\n"))
  end

  # Run one entry point in our own Python module: a real file in the repository,
  # read here and installed into Blender's sys.modules under a hash of its text.
  # A changed file installs once under a new module name and every later call
  # sends only the short invocation, so the wire cost is a few hundred bytes per
  # call. compile() is handed the file's own path, so a traceback out of Blender
  # names a line in that file instead of a generated string. Each entry point
  # takes the tool's arguments as a dict and returns a dict whose "report" is the
  # text.
  helper :run_module, args: [:string, :i64, :string, :string, :string], returns: :string do |host, port, path, entry, arguments|
    module_source = Json.read_text(path) || raise("#{path} not found: the Python module these tools run lives there")
    qargs = Json.quote(arguments)
    qentry = Json.quote(entry)
    qpath = Json.quote(path)
    qmodule = Json.quote("_mcp_module_#{Json.short_hash(module_source)}")
    qsource = Json.quote(module_source)
    call = "print('__MCP_RESULT__' + _json.dumps(getattr(mod, #{qentry})(_json.loads(#{qargs}))))"
    invoke = "import sys, json as _json\nmod = sys.modules.get(#{qmodule})\nif mod is None:\n    print('__MCP_NEED_INSTALL__')\nelse:\n    #{call}\n"
    install = "import sys, types, json as _json\nmod = sys.modules.get(#{qmodule})\nif mod is None:\n    mod = types.ModuleType(#{qmodule})\n    mod.__file__ = #{qpath}\n    exec(compile(#{qsource}, #{qpath}, 'exec'), mod.__dict__)\n    sys.modules[#{qmodule}] = mod\n#{call}\n"
    invoke_request = "{\"type\":\"execute_code\",\"params\":{\"code\":#{Json.quote(invoke)}}}"
    install_request = "{\"type\":\"execute_code\",\"params\":{\"code\":#{Json.quote(install)}}}"
    raw = Json.parse(rust(:blender_call, host, port, invoke_request))
    resp = raw || raise("Blender bridge unreachable: start the MCP Bridge add-on (addon/mcp_bridge.py) in Blender's sidebar, and give this server its token as BLENDER_BRIDGE_TOKEN")
    status = Json.text(resp, "/status") || "error"
    stdout = Json.text(resp, "/result/result") || ""
    cold = if Rust::Str(stdout).trim.to_s == "__MCP_NEED_INSTALL__" then true else false end
    retry_resp = if cold then (Json.parse(rust(:blender_call, host, port, install_request)) || raise("Blender bridge unreachable: start the MCP Bridge add-on (addon/mcp_bridge.py) in Blender's sidebar, and give this server its token as BLENDER_BRIDGE_TOKEN")) else resp end
    retry_status = if cold then (Json.text(retry_resp, "/status") || "error") else status end
    retry_stdout = if cold then (Json.text(retry_resp, "/result/result") || "") else stdout end
    raise (Json.text(retry_resp, "/message") || "Blender returned an error") unless retry_status == "success"
    retry_stdout.split("__MCP_RESULT__").last || raise("the script finished without a result")
  end

  # run_module with the caller's own bridge timeout in seconds: the same call,
  # willing to wait as long as the operation needs. A timeout on a long render is
  # the failure this exists to prevent, and it is threaded by hand because the
  # DSL has no default arguments, so a second helper is the only way to vary it
  # without touching every other run_module call site.
  helper :run_module_timeout, args: [:string, :i64, :string, :string, :string, :i64], returns: :string do |host, port, path, entry, arguments, timeout|
    module_source = Json.read_text(path) || raise("#{path} not found: the Python module these tools run lives there")
    qargs = Json.quote(arguments)
    qentry = Json.quote(entry)
    qpath = Json.quote(path)
    qmodule = Json.quote("_mcp_module_#{Json.short_hash(module_source)}")
    qsource = Json.quote(module_source)
    call = "print('__MCP_RESULT__' + _json.dumps(getattr(mod, #{qentry})(_json.loads(#{qargs}))))"
    invoke = "import sys, json as _json\nmod = sys.modules.get(#{qmodule})\nif mod is None:\n    print('__MCP_NEED_INSTALL__')\nelse:\n    #{call}\n"
    install = "import sys, types, json as _json\nmod = sys.modules.get(#{qmodule})\nif mod is None:\n    mod = types.ModuleType(#{qmodule})\n    mod.__file__ = #{qpath}\n    exec(compile(#{qsource}, #{qpath}, 'exec'), mod.__dict__)\n    sys.modules[#{qmodule}] = mod\n#{call}\n"
    invoke_request = "{\"type\":\"execute_code\",\"params\":{\"code\":#{Json.quote(invoke)}}}"
    install_request = "{\"type\":\"execute_code\",\"params\":{\"code\":#{Json.quote(install)}}}"
    raw = Json.parse(rust(:blender_call_timeout, host, port, invoke_request, timeout))
    resp = raw || raise("Blender bridge unreachable: start the MCP Bridge add-on (addon/mcp_bridge.py) in Blender's sidebar, and give this server its token as BLENDER_BRIDGE_TOKEN")
    status = Json.text(resp, "/status") || "error"
    stdout = Json.text(resp, "/result/result") || ""
    cold = if Rust::Str(stdout).trim.to_s == "__MCP_NEED_INSTALL__" then true else false end
    retry_resp = if cold then (Json.parse(rust(:blender_call_timeout, host, port, install_request, timeout)) || raise("Blender bridge unreachable: start the MCP Bridge add-on (addon/mcp_bridge.py) in Blender's sidebar, and give this server its token as BLENDER_BRIDGE_TOKEN")) else resp end
    retry_status = if cold then (Json.text(retry_resp, "/status") || "error") else status end
    retry_stdout = if cold then (Json.text(retry_resp, "/result/result") || "") else stdout end
    raise (Json.text(retry_resp, "/message") || "Blender returned an error") unless retry_status == "success"
    retry_stdout.split("__MCP_RESULT__").last || raise("the script finished without a result")
  end

  # The plain viewport capture: viewport_screenshot in our own module draws the
  # open 3D viewport offscreen, as it is, with no setting changed. Returns the
  # PNG as base64.
  helper :viewport_png, args: [:string, :i64, :string, :i32], returns: :string do |host, port, path, max_size|
    shot = Json.temp_png("viewport")
    value = Json.parse(run_module(host, port, path, "viewport_screenshot", "{\"max_size\":#{max_size},\"filepath\":#{Json.quote(shot)}}")) || raise("could not parse the screenshot result")
    problem = Json.text(value, "/error") || ""
    raise problem unless problem == ""
    Json.take_file_base64(shot) || raise("could not read the screenshot file")
  end

  # Run the look entry point with a ready-made argument object and return the
  # JSON it reports: what it drew, which views or frames, the framed size and
  # centre. The PNG it wrote is read separately. It changes shading and overlays
  # to take the picture (and restores them), which is why plain viewport mode
  # uses viewport_png instead.
  helper :look_info, args: [:string, :i64, :string, :string], returns: :string do |host, port, path, look_args|
    info = Json.parse(run_module(host, port, path, "look", look_args)) || raise("could not parse the look result")
    problem = Json.text(info, "/error") || ""
    raise problem unless problem == ""
    Json.dump(info) || raise("could not encode the look result")
  end

  params :SceneParams do

    field :query, :string, description: "Case-insensitive filter on item names; empty means everything", default: ""
    field :limit, :i32, description: "How many items to return", default: 30, min: 1, max: 200
  end

  output :Scene do
    field :items, Json::Value, description: "Matching items (kind, name, detail), names starting with the query first, and the total"
  end

  tool :scene, params: :SceneParams, title: "Scene items",
       description: "List objects, materials and collections in the current Blender scene, optionally filtered by name",
       output: :Scene, read_only: true, open_world: true do
    body do |query, limit|
      arguments = "{\"query\":#{Json.quote(query)},\"limit\":#{limit}}"
      value = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "scene_items", arguments)) || raise("could not parse the scene items")
      result(:Scene, items: value)
    end
  end

  params :SceneInfoParams do
    field :query, :string, description: "Name filter across all objects", optional: true
    field :root, :string, description: "Object whose hierarchy to list", optional: true
    field :detail, :string, description: "Which per-object fields to show",
          enum: ["default", "placement", "contents", "health", "settings", "all"], default: "default"
    field :limit, :i32, description: "Maximum object lines", default: 20, min: 1, max: 500
  end

  output :SceneInfo do
    field :data, Json::Value, description: "The scene summary script's header, lines, total and shown"
  end

  tool :scene_info, params: :SceneInfoParams, title: "Scene facts",
       description: "Facts about the scene: what is there, where, how big, and how healthy meshes and rigs are. Runs the scene-summary entry point of this server's own Python module inside Blender",
       output: :SceneInfo, read_only: true, open_world: true do
    body do |query, root, detail, limit|
      q = query || ""
      r = root || ""
      fields = if detail == "placement"
        "[\"location\",\"size\",\"ground\",\"rotation\",\"scale\",\"parent\"]"
      elsif detail == "contents"
        "[\"children\",\"hidden\",\"details\",\"materials\",\"modifiers\",\"animation\"]"
      elsif detail == "health"
        "[\"topology\",\"weights\"]"
      elsif detail == "settings"
        "[\"settings\"]"
      elsif detail == "all"
        "[\"location\",\"rotation\",\"scale\",\"size\",\"ground\",\"parent\",\"details\",\"materials\",\"modifiers\",\"animation\",\"hidden\",\"children\",\"topology\",\"weights\",\"settings\"]"
      else
        "[\"location\",\"size\",\"children\",\"hidden\"]"
      end
      jq = Json.quote(q)
      jr = Json.quote(r)
      arguments = "{\"query\":#{jq},\"root\":#{jr},\"limit\":#{limit},\"fields\":#{fields}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "scene_summary", arguments)) || raise("could not parse the scene summary")
      result(:SceneInfo, data: data)
    end
  end

  params :WireframeParams do
    field :name, :string, description: "Exact name of a mesh object in the scene"
    field :views, :string_list, description: "front, side or top; unset draws front and side", optional: true
    field :width, :i32, description: "characters across", default: 78, min: 40, max: 160
    field :height, :i32, description: "characters tall", default: 34, min: 20, max: 60
  end

  output :TextReport do
    field :report, :string, description: "Plain text: the drawn views or the measurements"
  end

  tool :wireframe, params: :WireframeParams, title: "Mesh wireframe",
       description: "Draw a mesh as text: front, side or top edge projections at true proportions, one character per cell. A cheap, readable alternative to a screenshot when judging shape or diagnosing floating or disjoint parts.",
       output: :TextReport, read_only: true, open_world: true do
    body do |name, views, width, height|
      args = "{\"name\":#{Json.quote(name)},\"views\":#{Json.str_list_json(views || [])},\"width\":#{width},\"height\":#{height}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "wireframe", args)) || raise("could not parse the wireframe result")
      result(:TextReport, report: Json.text(data, "/report") || raise("the wireframe script returned no text"))
    end
  end

  params :ImageReportParams do
    field :source, :string, description: "Name of an image already in the file, or a path to an image on disk under the file roots"
    field :width, :i32, description: "Characters across; rows follow the image's aspect", default: 116, min: 40, max: 200
  end

  tool :image_report, params: :ImageReportParams, title: "Read an image as text",
       description: "Describe an image to a reader that cannot see it: dimensions and aspect, the mean colour and the six most common colours, then two character grids over the same cells, one for tone (dark to bright) and one for hue (red/yellow/green/cyan/blue/magenta, grey or desaturated as a dot). Use it when an image content block cannot be read directly.",
       output: :TextReport, read_only: true, open_world: true do
    body do |source, width|
      args = "{\"source\":#{Json.quote(image_ref(source, setting(:write_roots), setting(:read_roots)))},\"width\":#{width}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "image_report", args)) || raise("could not parse the image report")
      result(:TextReport, report: Json.text(data, "/report") || raise("the image script returned no text"))
    end
  end

  params :ImageReportRustParams do
    field :source, :string, description: "Path to an image file under the file roots, on the machine this server runs on"
    field :width, :i32, description: "Cells across; rows follow the image's aspect at 2:1 cells", default: 116, min: 40, max: 200
  end

  tool :image_report_rust, params: :ImageReportRustParams, title: "Read an image as text (Rust)",
       description: "The same job as image_report, and more, computed in this server's own Rust rather than inside Blender: dimensions, aspect, mean and the most common colours, a tone grid, a hue-and-strength grid (case carries saturation), a spectrum ordered by hue, and a summary naming what is in the picture and roughly where. It reads the file itself, so it needs no Blender session and works while the addon is stopped. Kept beside image_report so one picture can go through both and the texts compared.",
       output: :TextReport, read_only: true, open_world: true do
    body do |source, width|
      path = jail(source, setting(:write_roots), setting(:read_roots), "read")
      report = rust(:grid, path, width)
      bytes = ImageFile.size(path)
      measured = if bytes.nil? then report else "#{report}\nfile #{bytes || 0} bytes" end
      result(:TextReport, report: measured)
    end
  end

  # --- Scene and output: seeing, making, placing, colouring, rendering, exporting ---
  #
  # These run python/mcp_scripts.py through run_module: a real module in the
  # repository, read here and installed into Blender once per content hash, so a
  # change to it needs no rebuild and a traceback names a line in the file.

  params :RevealParams do
    field :name, :string, description: "Exact name of the object to reveal and frame; unset reports the view instead", optional: true
    field :frame, :bool, description: "Frame the object in every 3D viewport", default: true
  end

  tool :reveal, params: :RevealParams, title: "Reveal an object",
       description: "Say why an object is not on screen and clear what is hiding it: leave local view, leave camera view, unhide the object and its collections, select it and frame it. The report names the file, scene, view layer, window and viewport count, which is also the answer to which Blender, and which file, a change landed in. Run it before believing a screenshot.",
       output: :TextReport, read_only: true, open_world: true do
    body do |name, frame|
      wanted = name || ""
      args = "{\"name\":#{Json.quote(wanted)},\"frame\":#{frame}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "reveal", args)) || raise("could not parse the reveal report")
      result(:TextReport, report: Json.text(data, "/report") || raise("reveal returned no text"))
    end
  end

  params :TextParams do
    field :text, :string, description: "The characters to draw; a newline starts another line"
    field :name, :string, description: "Object name; unset derives it from the first line", optional: true
    field :size, :f64, description: "Cap height in metres", default: 1.0, min: 0.01
    field :extrude, :f64, description: "Depth in metres; 0 stays flat", default: 0.0, min: 0.0
    field :spacing, :f64, description: "Letter spacing; 1 is Blender's own default", optional: true, min: 0.01
    field :align, :string, description: "How the lines line up around the origin", enum: ["LEFT", "CENTER", "RIGHT", "JUSTIFY", "FLUSH"], default: "CENTER"
    field :x, :f64, description: "Location X in metres", default: 0.0
    field :y, :f64, description: "Location Y in metres", default: 0.0
    field :z, :f64, description: "Location Z in metres", default: 0.0
    field :as_mesh, :bool, description: "Convert it to a mesh, so wireframe, mesh_report and export can read it", default: true
  end

  tool :text, params: :TextParams, title: "Make 3D text",
       description: "Create one text object from a string, and convert it to a mesh unless as_mesh is false. Text is a curve in Blender, so a mesh is what wireframe, mesh_report and an export can actually read; keep the curve when the text has to stay editable. Colour it with material, position it with place.",
       output: :TextReport, destructive: true, open_world: true do
    body do |text, name, size, extrude, spacing, align, x, y, z, as_mesh|
      wanted = name || ""
      spacing_json = if spacing.nil? then "null" else spacing.to_s end
      args = "{\"text\":#{Json.quote(text)},\"name\":#{Json.quote(wanted)},\"size\":#{size},\"extrude\":#{extrude},\"spacing\":#{spacing_json},\"align\":#{Json.quote(align)},\"x\":#{x},\"y\":#{y},\"z\":#{z},\"as_mesh\":#{as_mesh}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "text", args)) || raise("could not parse the text report")
      result(:TextReport, report: Json.text(data, "/report") || raise("the text script returned no text"))
    end
  end

  params :PlaceParams do
    field :name, :string, description: "Exact name of the object to move"
    field :x, :f64, description: "X in metres; unset leaves X alone", optional: true
    field :y, :f64, description: "Y in metres; unset leaves Y alone", optional: true
    field :z, :f64, description: "Z in metres; unset leaves Z alone", optional: true
    field :rx, :f64, description: "Rotation about X in degrees; unset leaves it alone", optional: true
    field :ry, :f64, description: "Rotation about Y in degrees; unset leaves it alone", optional: true
    field :rz, :f64, description: "Rotation about Z in degrees; unset leaves it alone", optional: true
    field :scale, :f64, description: "Uniform scale; unset leaves the scale alone", optional: true, min: 0.0
    field :relative, :bool, description: "Add to the current values instead of replacing them", default: false
  end

  tool :place, params: :PlaceParams, title: "Move an object",
       description: "Set an object's location, rotation or uniform scale: absolute by default, added to the current values when relative is set. Only the axes given are touched, so an unset axis keeps its value instead of being zeroed, which is what makes a relative nudge usable. The report gives what changed, the dimensions afterwards, whether a parent makes these numbers local, and any constraint that could override the result.",
       output: :TextReport, destructive: true, open_world: true do
    body do |name, x, y, z, rx, ry, rz, scale, relative|
      qx = if x.nil? then "null" else x.to_s end
      qy = if y.nil? then "null" else y.to_s end
      qz = if z.nil? then "null" else z.to_s end
      qrx = if rx.nil? then "null" else rx.to_s end
      qry = if ry.nil? then "null" else ry.to_s end
      qrz = if rz.nil? then "null" else rz.to_s end
      qscale = if scale.nil? then "null" else scale.to_s end
      args = "{\"name\":#{Json.quote(name)},\"x\":#{qx},\"y\":#{qy},\"z\":#{qz},\"rx\":#{qrx},\"ry\":#{qry},\"rz\":#{qrz},\"scale\":#{qscale},\"relative\":#{relative}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "place", args)) || raise("could not parse the placement report")
      result(:TextReport, report: Json.text(data, "/report") || raise("place returned no text"))
    end
  end

  params :MaterialParams do
    field :name, :string, description: "Exact name of the object whose material to set"
    field :colour, :string, description: "A colour to set: a hex value (#rrggbb or #rgb) or a name such as red, wood or steel", optional: true
    field :material, :string, description: "Name an existing material to assign instead of a colour", optional: true
    field :roughness, :f64, description: "Principled roughness 0-1; unset leaves it", optional: true, min: 0.0, max: 1.0
    field :metallic, :f64, description: "Principled metallic 0-1; unset leaves it", optional: true, min: 0.0, max: 1.0
  end

  tool :material, params: :MaterialParams, title: "Colour an object",
       description: "Set or create the material on an object, from a hex colour or a name: it uses the object's existing material when it has one and otherwise makes one. Both the Principled base colour a render uses and the flat viewport colour a solid screenshot shows are set, and the report says which slot the faces actually use, so a colour that cannot show up says so instead of looking applied. Call it with no colour to read what an object has.",
       output: :TextReport, destructive: true, open_world: true do
    body do |name, colour, material, roughness, metallic|
      wanted_colour = colour || ""
      wanted_material = material || ""
      qrough = if roughness.nil? then "null" else roughness.to_s end
      qmetal = if metallic.nil? then "null" else metallic.to_s end
      args = "{\"name\":#{Json.quote(name)},\"colour\":#{Json.quote(wanted_colour)},\"material\":#{Json.quote(wanted_material)},\"roughness\":#{qrough},\"metallic\":#{qmetal}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "material", args)) || raise("could not parse the material report")
      result(:TextReport, report: Json.text(data, "/report") || raise("material returned no text"))
    end
  end

  params :RemoveParams do
    field :names, :string_list, description: "Exact names of the objects to remove"
    field :purge, :bool, description: "After removing, purge data left with no user: meshes, materials, images", default: true
  end

  tool :remove, params: :RemoveParams, title: "Remove objects",
       description: "Delete named objects from the scene and report the cost: what went, which of their children were left unparented, what the orphan purge freed, and what is left. The counterpart of text and place. Blender's own undo may not cover it, so treat a removal as final.",
       output: :TextReport, destructive: true, open_world: true do
    body do |names, purge|
      listed = Json.str_list_json(names)
      args = "{\"names\":#{listed},\"purge\":#{purge}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "remove", args)) || raise("could not parse the removal report")
      result(:TextReport, report: Json.text(data, "/report") || raise("remove returned no text"))
    end
  end

  # --- Modelling: copy, stack, cut, light, and put the camera where it belongs ---

  params :DuplicateParams do
    field :names, :string_list, description: "Exact names of the objects to copy"
    field :count, :i32, description: "How many copies of each", default: 1, min: 1, max: 200
    field :dx, :f64, description: "Offset per copy along X, in metres", default: 0.0
    field :dy, :f64, description: "Offset per copy along Y, in metres", default: 0.0
    field :dz, :f64, description: "Offset per copy along Z, in metres", default: 0.0
    field :linked, :bool, description: "Share the original's mesh data instead of copying it", default: false
  end

  tool :duplicate, params: :DuplicateParams, title: "Copy objects",
       description: "Copy one or more objects, offsetting each copy by a fixed step, so one generated chair becomes a row. Full copies by default, each with its own mesh; linked copies share the original's data and change together. Copies land in the original's collections and keep its parent.",
       output: :TextReport, destructive: true, open_world: true do
    body do |names, count, dx, dy, dz, linked|
      listed = Json.str_list_json(names)
      args = "{\"names\":#{listed},\"count\":#{count},\"dx\":#{dx},\"dy\":#{dy},\"dz\":#{dz},\"linked\":#{linked}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "duplicate", args)) || raise("could not parse the copy report")
      result(:TextReport, report: Json.text(data, "/report") || raise("duplicate returned no text"))
    end
  end

  params :ArrayParams do
    field :name, :string, description: "Exact name of the mesh object to stack"
    field :count, :i32, description: "How many copies the modifier makes, the original included", default: 3, min: 1, max: 1000
    field :mode, :string, description: "constant: offsets are metres; relative: they are factors of the object's own size", enum: ["constant", "relative"], default: "constant"
    field :offset_x, :f64, description: "Offset per copy along X; unset uses the object's width", optional: true
    field :offset_y, :f64, description: "Offset per copy along Y; unset is 0", optional: true
    field :offset_z, :f64, description: "Offset per copy along Z; unset is 0", optional: true
  end

  tool :array, params: :ArrayParams, title: "Stack copies with a modifier",
       description: "Add or update an array modifier on one mesh, so it repeats along an axis without duplicating objects: the row follows the original, and renders and exports apply it. mesh_report and wireframe read the base mesh, so they still see a single copy.",
       output: :TextReport, destructive: true, open_world: true do
    body do |name, count, mode, offset_x, offset_y, offset_z|
      qx = if offset_x.nil? then "null" else offset_x.to_s end
      qy = if offset_y.nil? then "null" else offset_y.to_s end
      qz = if offset_z.nil? then "null" else offset_z.to_s end
      args = "{\"name\":#{Json.quote(name)},\"count\":#{count},\"mode\":#{Json.quote(mode)},\"offset_x\":#{qx},\"offset_y\":#{qy},\"offset_z\":#{qz}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "array", args)) || raise("could not parse the array report")
      result(:TextReport, report: Json.text(data, "/report") || raise("array returned no text"))
    end
  end

  params :BooleanParams do
    field :name, :string, description: "Exact name of the object to modify"
    field :operand, :string, description: "Exact name of the second object: the cutter, the joiner or the overlap"
    field :operation, :string, description: "difference cuts the operand out, union joins it in, intersect keeps only the overlap", enum: ["difference", "union", "intersect"], default: "difference"
    field :apply, :bool, description: "Apply the modifier into the mesh instead of leaving it live", default: true
    field :hide_operand, :bool, description: "Hide the operand afterwards, as a cutter usually is", default: true
  end

  tool :boolean, params: :BooleanParams, title: "Cut or join two meshes",
       description: "Boolean one mesh against another and report the result's face count, so a cut that missed shows up now rather than at render time. Applied by default, which changes the mesh itself; with apply false it stays a live modifier. Both must be meshes, and a difference needs them to overlap.",
       output: :TextReport, destructive: true, open_world: true do
    body do |name, operand, operation, apply, hide_operand|
      args = "{\"name\":#{Json.quote(name)},\"operand\":#{Json.quote(operand)},\"operation\":#{Json.quote(operation)},\"apply\":#{apply},\"hide_operand\":#{hide_operand}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "boolean", args)) || raise("could not parse the boolean report")
      result(:TextReport, report: Json.text(data, "/report") || raise("boolean returned no text"))
    end
  end

  params :AimParams do
    field :target, :string, description: "Exact name of the object the camera should frame"
    field :camera, :string, description: "Camera to move; unset uses the scene camera, creating one if there is none", optional: true
    field :view, :string, description: "Which side to stand on", enum: ["three_quarter", "front", "back", "left", "right", "top"], default: "three_quarter"
    field :distance, :f64, description: "Metres from the target; unset fits the target's size to the lens", optional: true, min: 0.0
    field :lens, :f64, description: "Focal length in millimetres; unset keeps the camera's own", optional: true, min: 1.0
  end

  tool :aim, params: :AimParams, title: "Point the camera at something",
       description: "Put a camera where it frames a target, from a named side, at a distance that fits the target's size to the lens, and make it the scene camera. This is what makes render and look show the subject: a camera left facing the wrong way renders a flat grey world and nothing else reports that. Use place afterwards for an exact transform.",
       output: :TextReport, destructive: true, open_world: true do
    body do |target, camera, view, distance, lens|
      wanted_camera = camera || ""
      qdistance = if distance.nil? then "null" else distance.to_s end
      qlens = if lens.nil? then "null" else lens.to_s end
      args = "{\"target\":#{Json.quote(target)},\"camera\":#{Json.quote(wanted_camera)},\"view\":#{Json.quote(view)},\"distance\":#{qdistance},\"lens\":#{qlens}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "aim", args)) || raise("could not parse the camera report")
      result(:TextReport, report: Json.text(data, "/report") || raise("aim returned no text"))
    end
  end

  params :LightParams do
    field :name, :string, description: "Light to adjust; unset creates one", optional: true
    field :kind, :string, description: "sun is even and distance-independent; point, area and spot fall off", enum: ["sun", "point", "area", "spot"], default: "sun"
    field :energy, :f64, description: "Sun: irradiance, where 3 reads as daylight. Others: watts, where 1000 is a lamp. Unset uses those", optional: true, min: 0.0
    field :size, :f64, description: "Area size in metres, or spot angle in degrees", optional: true, min: 0.0
    field :target, :string, description: "Object to aim at; unset aims at the middle of the scene's objects", optional: true
    field :x, :f64, description: "X in metres; unset places it above and in front of the subject", optional: true
    field :y, :f64, description: "Y in metres; unset places it above and in front of the subject", optional: true
    field :z, :f64, description: "Z in metres; unset places it above and in front of the subject", optional: true
  end

  tool :light, params: :LightParams, title: "Make or move a light",
       description: "Create a light or adjust one that exists, aimed at an object or at the middle of the scene, so a render is lit on purpose rather than by whatever the file came with. Reports the type, energy and target, and lists every light in the file. A sun is the steady choice for a quick look; the others fall off with distance.",
       output: :TextReport, destructive: true, open_world: true do
    body do |name, kind, energy, size, target, x, y, z|
      wanted_name = name || ""
      wanted_target = target || ""
      qenergy = if energy.nil? then "null" else energy.to_s end
      qsize = if size.nil? then "null" else size.to_s end
      qx = if x.nil? then "null" else x.to_s end
      qy = if y.nil? then "null" else y.to_s end
      qz = if z.nil? then "null" else z.to_s end
      args = "{\"name\":#{Json.quote(wanted_name)},\"kind\":#{Json.quote(kind)},\"energy\":#{qenergy},\"size\":#{qsize},\"target\":#{Json.quote(wanted_target)},\"x\":#{qx},\"y\":#{qy},\"z\":#{qz}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "light", args)) || raise("could not parse the light report")
      result(:TextReport, report: Json.text(data, "/report") || raise("light returned no text"))
    end
  end

  params :ModifierParams do
    field :name, :string, description: "Exact name of the mesh object"
    field :action, :string, description: "add creates or updates one, remove takes the first of that kind off, list reports what is there", enum: ["add", "remove", "list"], default: "add"
    field :kind, :string, description: "Which modifier; required for add and remove", enum: ["subdivision", "bevel", "mirror", "solidify", "decimate", "wireframe"], optional: true
    field :count, :i32, description: "subdivision: viewport levels. Unset keeps what is there", optional: true, min: 0, max: 8
    field :amount, :f64, description: "bevel, solidify or wireframe thickness in metres; decimate ratio 0-1. Unset keeps the modifier's own value", optional: true
    field :axis, :string, description: "mirror: which axis to mirror on", enum: ["x", "y", "z"], optional: true
    field :apply, :bool, description: "Apply it into the mesh instead of leaving it live", default: false
  end

  tool :modifier, params: :ModifierParams, title: "Add or remove a modifier",
       description: "Add, remove or list one modifier on a mesh: subdivision, bevel, mirror, solidify, decimate or wireframe, with the setting that matters for that kind typed. The report gives the base and evaluated face counts, so an effect that did nothing is visible rather than assumed. The long tail of modifier properties is not typed; set one with execute_code.",
       output: :TextReport, destructive: true, open_world: true do
    body do |name, action, kind, count, amount, axis, apply|
      wanted_kind = kind || ""
      wanted_axis = axis || ""
      qcount = if count.nil? then "null" else count.to_s end
      qamount = if amount.nil? then "null" else amount.to_s end
      args = "{\"name\":#{Json.quote(name)},\"action\":#{Json.quote(action)},\"kind\":#{Json.quote(wanted_kind)},\"count\":#{qcount},\"amount\":#{qamount},\"axis\":#{Json.quote(wanted_axis)},\"apply\":#{apply}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "modifier", args)) || raise("could not parse the modifier report")
      result(:TextReport, report: Json.text(data, "/report") || raise("modifier returned no text"))
    end
  end

  params :ImageViewParams do
    field :source, :string, description: "Path to an image file under the file roots, on the machine this server runs on"
    field :width, :i32, description: "Cells across", default: 64, min: 20, max: 200
    field :mode, :string, description: "half: two samples stacked, two colours. braille: eight samples (a 4x2 dot grid) as one dithered glyph, four times the vertical detail. blend: the same eight samples with two colours, the lit dots in front and the gaps behind", enum: ["half", "braille", "blend"], default: "blend"
    field :dither, :string, description: "diffusion: Floyd-Steinberg, where each dot's rounding error spills into its neighbours, giving irregular dots that read as tone. ordered: a 4x4 Bayer threshold, regular by construction and so more textured. threshold: a hard 50% cut", enum: ["diffusion", "ordered", "threshold"], default: "diffusion"
  end

  tool :image_view, params: :ImageViewParams, title: "Show an image in the terminal",
       description: "The image itself, as truecolour text for a human to look at, in three modes: half draws two stacked samples per cell with two colours; braille draws a dithered 4x2 dot grid as one glyph, four times the vertical detail, which makes a flat tone read as tone; blend does braille with the lit dots in one colour and the gaps in another, so shape and colour both survive. This is for eyes, not for a model: a text model should read image_report or image_report_rust, which cost a fraction of the tokens. It needs a client that passes ANSI through, a terminal that renders truecolour, and a font carrying braille and block glyphs.",
       output: :TextReport, read_only: true, open_world: true do
    body do |source, width, mode, dither|
      path = jail(source, setting(:write_roots), setting(:read_roots), "read")
      result(:TextReport, report: rust(:ansi, path, width, mode, dither))
    end
  end

  output :FileReport do
    field :path, :string, description: "Absolute path of the file that was written"
    field :report, :string, description: "Plain text: what was written and with what settings"
  end

  params :RenderParams do
    field :file, :string, description: "Where to write the PNG, under the write roots (BLENDER_WRITE_ROOTS); a relative path lands under the first root, and unset writes <name>-render.png in its renders folder", optional: true
    field :camera, :string, description: "Camera to render from; unset uses the scene camera", optional: true
    field :width, :i32, description: "Pixels across; unset keeps the file's setting", optional: true, min: 16, max: 8192
    field :height, :i32, description: "Pixels down; unset keeps the file's setting", optional: true, min: 16, max: 8192
    field :samples, :i32, description: "Samples for the current engine; unset keeps the file's setting", optional: true, min: 1, max: 8192
    field :frame, :i32, description: "Frame to render; unset renders the current one", optional: true
    field :timeout_seconds, :i64, description: "How long to wait for Blender before giving up; unset waits 900 s, which covers a Cycles still that outruns the default 60 s bridge timeout", optional: true, min: 1, max: 86400
  end

  tool :render, params: :RenderParams, title: "Render to a file",
       description: "Render the scene to a PNG at the resolution and sample count asked for and leave it on disk, so the result is a file the user keeps and can open. The report names the path, the size and the settings; read the picture back as text with image_report, or use look with mode camera when the picture should come back as an image in the reply.",
       output: :FileReport, destructive: true, open_world: true do
    body do |file, camera, width, height, samples, frame, timeout_seconds|
      roots = setting(:write_roots)
      readable = setting(:read_roots)
      wanted_file = if file.nil? then "" else jail(file || "", roots, readable, "write") end
      folder = jail("renders", roots, readable, "write")
      wanted_camera = camera || ""
      qwidth = if width.nil? then "null" else width.to_s end
      qheight = if height.nil? then "null" else height.to_s end
      qsamples = if samples.nil? then "null" else samples.to_s end
      qframe = if frame.nil? then "null" else frame.to_s end
      wait = timeout_seconds || 900
      args = "{\"file\":#{Json.quote(wanted_file)},\"folder\":#{Json.quote(folder)},\"camera\":#{Json.quote(wanted_camera)},\"width\":#{qwidth},\"height\":#{qheight},\"samples\":#{qsamples},\"frame\":#{qframe}}"
      data = Json.parse(run_module_timeout(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "render", args, wait)) || raise("could not parse the render report")
      result(:FileReport, path: Json.text(data, "/path") || "", report: Json.text(data, "/report") || raise("the render script returned no text"))
    end
  end

  params :RenderAnimationParams do
    field :file, :string, description: "Where to write the output, under the write roots (BLENDER_WRITE_ROOTS); a directory for format png (files land as <stem>_0001.png), or a file for a video; a relative path lands under the first root, and unset writes in its renders folder", optional: true
    field :scene, :string, description: "Scene to render; unset uses the window's active scene", optional: true
    field :camera, :string, description: "Camera to render from; unset uses the scene camera", optional: true
    field :frame_start, :i32, description: "First frame of the range; unset uses the scene's frame_start", optional: true
    field :frame_end, :i32, description: "Last frame of the range; unset uses the scene's frame_end", optional: true
    field :fps, :i32, description: "Frames per second for the video; unset keeps the file's setting", optional: true
    field :width, :i32, description: "Pixels across; unset keeps the file's setting", optional: true, min: 16, max: 8192
    field :height, :i32, description: "Pixels down; unset keeps the file's setting", optional: true, min: 16, max: 8192
    field :samples, :i32, description: "Samples for the current engine; unset keeps the file's setting", optional: true, min: 1, max: 8192
    field :format, :string, description: "mp4, webm and mkv write a video through Blender's FFMPEG output; png writes a numbered sequence", enum: ["mp4", "webm", "mkv", "png"], default: "mp4"
    field :timeout_seconds, :i64, description: "How long to wait for Blender before giving up; unset waits 3600 s, because a long range will outlive the default 60 s bridge timeout", optional: true, min: 1, max: 86400
  end

  tool :render_animation, params: :RenderAnimationParams, title: "Render an animation to a file",
       description: "Render the frame range of a scene to a video (mp4, webm or mkv through Blender's FFMPEG output) or a PNG sequence, and leave it on disk. A long range can outlive the default bridge timeout, so raise timeout_seconds for it (or render in chunks). The report names the path, the frames and the format; a timed-out range is not lost, so check what was written before re-running.",
       output: :FileReport, destructive: true, open_world: true do
    body do |file, scene, camera, frame_start, frame_end, fps, width, height, samples, format, timeout_seconds|
      roots = setting(:write_roots)
      readable = setting(:read_roots)
      wanted_file = if file.nil? then "" else jail(file || "", roots, readable, "write") end
      folder = jail("renders", roots, readable, "write")
      wanted_scene = scene || ""
      wanted_camera = camera || ""
      qframe_start = if frame_start.nil? then "null" else frame_start.to_s end
      qframe_end = if frame_end.nil? then "null" else frame_end.to_s end
      qfps = if fps.nil? then "null" else fps.to_s end
      qwidth = if width.nil? then "null" else width.to_s end
      qheight = if height.nil? then "null" else height.to_s end
      qsamples = if samples.nil? then "null" else samples.to_s end
      wait = timeout_seconds || 3600
      args = "{\"file\":#{Json.quote(wanted_file)},\"folder\":#{Json.quote(folder)},\"scene\":#{Json.quote(wanted_scene)},\"camera\":#{Json.quote(wanted_camera)},\"frame_start\":#{qframe_start},\"frame_end\":#{qframe_end},\"fps\":#{qfps},\"width\":#{qwidth},\"height\":#{qheight},\"samples\":#{qsamples},\"format\":#{Json.quote(format)}}"
      data = Json.parse(run_module_timeout(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "render_animation", args, wait)) || raise("could not parse the render_animation report")
      result(:FileReport, path: Json.text(data, "/path") || "", report: Json.text(data, "/report") || raise("the render_animation script returned no text"))
    end
  end

  params :ExportParams do
    field :file, :string, description: "Where to write the model, under the write roots (BLENDER_WRITE_ROOTS); a relative path lands under the first root, and unset writes <name>.glb (or .fbx) in its exports folder", optional: true
    field :format, :string, description: "glb carries materials and animation; fbx is the fallback for importers that need it", enum: ["glb", "fbx"], default: "glb"
    field :objects, :string_list, description: "Objects to export, children included; unset exports everything visible", optional: true
    field :selection_only, :bool, description: "Export the viewport selection instead", default: false
    field :apply_modifiers, :bool, description: "Apply modifiers on the way out", default: true
  end

  tool :export, params: :ExportParams, title: "Export the scene",
       description: "Write the scene, or named objects with their children, to glTF (.glb) or FBX, so the work leaves Blender as one file. The report names the path, the size, and anything skipped because it is not in the current view layer. It replaces the viewport selection as a side effect, which the report says, so call reveal afterwards if the selection mattered.",
       output: :FileReport, destructive: true, open_world: true do
    body do |file, format, objects, selection_only, apply_modifiers|
      roots = setting(:write_roots)
      readable = setting(:read_roots)
      wanted_file = if file.nil? then "" else jail(file || "", roots, readable, "write") end
      folder = jail("exports", roots, readable, "write")
      listed = Json.str_list_json(objects || [])
      args = "{\"file\":#{Json.quote(wanted_file)},\"folder\":#{Json.quote(folder)},\"format\":#{Json.quote(format)},\"objects\":#{listed},\"selection_only\":#{selection_only},\"apply_modifiers\":#{apply_modifiers}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "export", args)) || raise("could not parse the export report")
      result(:FileReport, path: Json.text(data, "/path") || "", report: Json.text(data, "/report") || raise("the export script returned no text"))
    end
  end

  params :MeshReportParams do
    field :name, :string, description: "Exact name of a mesh object in the scene"
  end

  tool :mesh_report, params: :MeshReportParams, title: "Mesh report",
       description: "Measure a mesh: dimensions, world bounding box, faces and vertices, materials, modifiers, location and scale, the loose parts with their bounds, and a face-orientation histogram. Use it to check scale, placement and whether an assembly is actually joined.",
       output: :TextReport, read_only: true, open_world: true do
    body do |name|
      args = "{\"name\":#{Json.quote(name)}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "mesh_report", args)) || raise("could not parse the mesh report")
      result(:TextReport, report: Json.text(data, "/report") || raise("the mesh report script returned no text"))
    end
  end

  params :CodeParams do
    field :code, :string, description: "Blender Python to run in the live session; what it prints is returned"
  end

  output :CodeResult do
    field :output, :string, description: "Everything the code printed to stdout"
  end

  tool :execute_code, params: :CodeParams, title: "Execute Blender Python",
       description: "Run Python inside the running Blender session and return what it printed. Guarded by default (BLENDER_CODE_POLICY): the code may import only bpy, bmesh, mathutils and pure-Python helpers, may not start processes, open sockets or load native code, and every file path it hands Blender must sit under the server's roots. A refusal names the line and the rule",
       output: :CodeResult, destructive: true, open_world: true do
    body do |code|
      host = setting(:blender_host)
      port = Integer(setting(:blender_port), 10)
      policy = setting(:code_policy)
      raise "execute_code is off on this server (BLENDER_CODE_POLICY=off); use the typed tools" if policy == "off"
      raise "BLENDER_CODE_POLICY is #{policy}; it must be guarded, open or off" unless policy == "guarded" || policy == "open"
      if policy == "open"
        # Unchecked, as the user: the whole filesystem is in reach. Only for a
        # session the user chose to open.
        request = "{\"type\":\"execute_code\",\"params\":{\"code\":#{Json.quote(code)}}}"
        value = Json.parse(blender_request(host, port, request)) || raise("could not parse the result")
        result(:CodeResult, output: Json.text(value, "/result") || "")
      else
        # Guarded: upstream's validator first, unmodified, then python/mcp_guard.py
        # runs the code with every path held to the roots (see its docstring).
        verdict = Json.parse(run_module(host, port, "python/safe_mode.py", "is_safe", Json.quote(code))) || raise("could not parse the validator's verdict")
        safe = Json.dump(Json.at(verdict, "/0") || raise("the validator returned no verdict")) || "false"
        raise "refused by the validator, #{Json.text(verdict, "/1") || "no reason given"}. Rewrite the script within the rules, or use a typed tool" unless safe == "true"
        arguments = "{\"code\":#{Json.quote(code)},\"write\":#{roots_json(setting(:write_roots))},\"read\":#{roots_json(setting(:read_roots))}}"
        ran = Json.parse(run_module(host, port, "python/mcp_guard.py", "run", arguments)) || raise("could not parse the guard's result")
        output = Json.text(ran, "/output") || ""
        problem = Json.text(ran, "/error") || ""
        # Interpolated, not assigned, so problem is not moved before the check
        # below reads it: the generated Rust would not clone it.
        failure = if output == "" then "#{problem}" else "#{problem}\n\nprinted before it stopped:\n#{output}" end
        raise failure unless problem == ""
        result(:CodeResult, output: output)
      end
    end
  end

  params :ObjectParams do
    field :name, :string, description: "Exact name of an object in the scene"
  end

  output :Object do
    field :object, Json::Value, description: "Name, type, location, rotation, scale, visibility, materials, and for a mesh its world bounding box and counts"
  end

  tool :object_info, params: :ObjectParams, title: "Object info",
       description: "Return details for one scene object by name",
       output: :Object, read_only: true, open_world: true do
    body do |name|
      value = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "object_info", "{\"name\":#{Json.quote(name)}}")) || raise("could not parse the object info")
      problem = Json.text(value, "/error") || ""
      raise problem unless problem == ""
      result(:Object, object: value)
    end
  end

  params :ShotParams do
    field :max_size, :i32, description: "Longest edge of the screenshot in pixels", default: 800, min: 64, max: 2048
  end

  tool :screenshot, params: :ShotParams, title: "Viewport screenshot",
       description: "Capture the 3D viewport as a PNG image the model can look at. The visual feedback loop: look, then change",
       read_only: true, open_world: true do
    body do |max_size|
      image(viewport_png(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), max_size), "image/png")
    end
  end

  params :LookParams do
    field :mode, :string, description: "Where the view comes from: the viewport, the scene camera, several angles around the target, an animation strip, or one image already in the file",
          enum: ["viewport", "camera", "angles", "frames", "image"], default: "viewport"
    field :shading, :string, description: "How it is drawn; unset uses the viewport's own shading",
          enum: ["solid", "material", "rendered", "wireframe", "xray"], optional: true
    field :targets, :string_list, description: "Objects to frame, children included; unset frames every visible object", optional: true
    field :views, :string_list, description: "For angles: which sides to draw from (front, back, left, right, top, three_quarter); unset draws the default set", optional: true
    field :frames, :i64_list, description: "For frames: the frame numbers to sample; unset samples frame_count frames across the scene's range", optional: true
    field :view, :string, description: "An angle name, or \"camera\", to look from; unset keeps the current view", optional: true
    field :image, :string, description: "For image: an image in the file, or a path on disk under the file roots, to show", optional: true
    field :distance, :f64, description: "Metres from the target centre to the eye; 0 fits the target automatically", default: 0.0, min: 0.0
    field :frame_count, :i32, description: "For frames: how many frames to sample when frames is unset", default: 6, min: 2, max: 12
    field :max_size, :i32, description: "Longest side in pixels; smaller keeps long sessions cheap", default: 768, min: 200, max: 2000
  end

  tool :look, params: :LookParams, title: "Look at the scene",
       description: "See the scene as one image: the viewport, the camera, several angles around targets, a strip over the animation, or an image in the file. Every setting it changes to take the picture is restored",
       read_only: true, open_world: true do
    body do |mode, shading, targets, views, frames, view, image, distance, frame_count, max_size|
      s = shading || ""
      v = view || ""
      image_name = if image.nil? then "" else image_ref(image || "", setting(:write_roots), setting(:read_roots)) end
      target_json = Json.str_list_json(targets || [])
      views_json = Json.str_list_json(views || [])
      frames_json = Json.i64_list_json(frames || [])
      host = setting(:blender_host)
      port = Integer(setting(:blender_port), 10)
      path = Json.temp_png("look")
      arguments = "{\"mode\":#{Json.quote(mode)},\"shading\":#{Json.quote(s)},\"target\":#{target_json},\"views\":#{views_json},\"distance\":#{distance},\"view\":#{Json.quote(v)},\"frames\":#{frames_json},\"frame_count\":#{frame_count},\"max_size\":#{max_size},\"image\":#{Json.quote(image_name)},\"filepath\":#{Json.quote(path)}}"
      scripted = !(mode == "viewport" && s == "")
      caption = if scripted then look_info(host, port, setting(:blender_python), arguments) else "Viewport capture." end
      data = if scripted then (Json.take_file_base64(path) || raise("could not read the look image")) else viewport_png(host, port, setting(:blender_python), max_size) end
      [image(data, "image/png"), text(caption)]
    end
  end

  # --- Asset libraries: Poly Haven, Sketchfab, Poly Pizza ---
  #
  # search_assets answers rust/blender_assets.rs's JSON as it is. import_asset
  # downloads into a fresh folder under the first write root's downloads/ (the
  # Rust side), then has Blender import it and delete the folder once every new
  # image is packed (import_asset in python/mcp_scripts.py).

  params :AssetSearchParams do
    field :source, :string, description: "Which library to search: polyhaven (CC0 HDRIs, PBR textures and models; no key needed), sketchfab or polypizza (each needs its API key in this server's environment)", enum: ["polyhaven", "sketchfab", "polypizza"]
    field :query, :string, description: "What you are looking for, in plain words", default: ""
    field :asset_type, :string, description: "polyhaven only: which asset types to search", enum: ["all", "hdris", "textures", "models"], default: "all"
    field :category, :string, description: "polyhaven: a taxonomy path such as \"Metal/Sheet & Corrugated\"; sketchfab: comma-separated category slugs; polypizza: a category name such as \"Furniture & Decor\" or an id 0-11", optional: true
    field :min_size_m, :f64, description: "polyhaven only: minimum real-world size in metres; use 2+ for walls, floors and ground", optional: true
    field :licence, :string, description: "polypizza only: \"CC0\" or \"CC-BY\"", optional: true
    field :animated, :bool, description: "polypizza only: return animated models only", default: false
    field :limit, :i32, description: "How many results to return (sketchfab at most 24, polypizza 32)", default: 20, min: 1, max: 50
  end

  tool :search_assets, params: :AssetSearchParams, title: "Search asset libraries",
       description: "Search Poly Haven (HDRIs, PBR textures and models, all CC0), Sketchfab (user-made models) or Poly Pizza (stylised low-poly models) and return the results as JSON; each result carries the id import_asset takes. Poly Haven textures report their real-world size (dimensions_mm). Sketchfab and Poly Pizza need API keys in this server's environment (BLENDERMCP_SKETCHFAB_API_KEY, BLENDERMCP_POLYPIZZA_API_KEY); without one the search says so, which is a message for the user.",
       read_only: true, open_world: true do
    body do |source, query, asset_type, category, min_size_m, licence, animated, limit|
      found = rust(:asset_search, source, query, asset_type, category || "", licence || "", min_size_m || 0.0, animated, Integer(limit.to_s, 10))
      value = Json.parse(found) || raise("could not parse the search result")
      problem = Json.text(value, "/error") || ""
      raise problem unless problem == ""
      found
    end
  end

  params :AssetImportParams do
    field :source, :string, description: "Which library the asset came from", enum: ["polyhaven", "sketchfab", "polypizza"]
    field :id, :string, description: "The asset's id from search_assets (the uid for sketchfab)"
    field :asset_type, :string, description: "polyhaven only, required: hdris (becomes the world lighting), textures (builds a PBR material) or models", enum: ["hdris", "textures", "models"], optional: true
    field :target_size, :f64, description: "Metres across the model's largest dimension (chair 1.0, car 4.5, cup 0.12); required for sketchfab, recommended for every model", optional: true
    field :apply_to, :string_list, description: "polyhaven textures only: objects to give a material built from the texture; replaces their materials", optional: true
    field :resolution, :string, description: "polyhaven only: texture, HDRI or model resolution", enum: ["1k", "2k", "4k", "8k"], default: "1k"
    field :file_format, :string, description: "polyhaven only: hdr or exr for HDRIs; jpg, png or exr for textures; blend (the default, the artist's own materials) or gltf for models", optional: true
    field :timeout_seconds, :i64, description: "How long to wait for Blender before giving up; unset waits 900 s, covering a download and import that outruns the default 60 s bridge timeout", optional: true, min: 1, max: 86400
  end

  tool :import_asset, params: :AssetImportParams, title: "Import an asset",
       description: "Download an asset found with search_assets and bring it into the scene: a Poly Haven HDRI becomes the world, a texture becomes a PBR material (and is applied to the apply_to objects), and a model from any library is imported, scaled to target_size when given. Images are packed into the .blend and the download is deleted. Check the reported world_bounding_box and put the model on the ground. Sketchfab and Poly Pizza need API keys in this server's environment.",
       destructive: true, open_world: true do
    body do |source, id, asset_type, target_size, apply_to, resolution, file_format, timeout_seconds|
      host = setting(:blender_host)
      port = Integer(setting(:blender_port), 10)
      kind = asset_type || ""
      raise "polyhaven needs asset_type: hdris, textures or models" if source == "polyhaven" && kind == ""
      raise "sketchfab needs target_size (metres across the largest dimension)" if source == "sketchfab" && target_size.nil?
      wait = timeout_seconds || 900
      downloads = jail("downloads", setting(:write_roots), setting(:read_roots), "write")
      size = target_size || 0.0
      names = Json.str_list_json(apply_to || [])
      manifest = rust(:asset_fetch, source, id, kind, resolution, file_format || "", downloads)
      fetched = Json.parse(manifest) || raise("could not parse the download result")
      problem = Json.text(fetched, "/error") || ""
      raise problem unless problem == ""
      first = run_module_timeout(host, port, setting(:blender_python), "import_asset", "{\"manifest\":#{manifest},\"target_size\":#{size},\"apply_to\":#{names}}", wait)
      result = Json.parse(first) || raise("could not parse the import result")
      fallback = Json.text(result, "/fallback") || ""
      if fallback == ""
        failure = Json.text(result, "/error") || ""
        raise failure unless failure == ""
        first
      else
        # A .blend written by a newer Blender cannot be opened here at all, and
        # Poly Haven publishes a glTF of every model: a poorer record of the
        # materials, but a model rather than none.
        gltf = rust(:asset_fetch, source, id, kind, resolution, "gltf", downloads)
        refetched = Json.parse(gltf) || raise("could not parse the download result")
        refused = Json.text(refetched, "/error") || ""
        raise "Model #{id} is #{fallback}, which this Blender cannot open, and the glTF fallback failed too: #{refused}" unless refused == ""
        note = " Imported from glTF rather than .blend, because the .blend was #{fallback}; its materials are a conversion rather than the ones the artist built."
        second = run_module_timeout(host, port, setting(:blender_python), "import_asset", "{\"manifest\":#{gltf},\"target_size\":#{size},\"apply_to\":[],\"note\":#{Json.quote(note)}}", wait)
        again = Json.parse(second) || raise("could not parse the import result")
        failed = Json.text(again, "/error") || ""
        raise failed unless failed == ""
        second
      end
    end
  end

  transport :http, port: 8787, auth_setting: :mcp_token,
          allowed_hosts: ["host.docker.internal", "127.0.0.1", "localhost"]
end



