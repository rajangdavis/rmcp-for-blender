# typed: true
server "blender", version: "0.1.0", instructions: "MCP for Blender drives the user's live Blender. execute_code runs Python there with the full bpy API, so anything Blender can do, you can do; screenshot and look show you the result.\n\nStart with command(name: \"get_addon_info\") (Blender version, which libraries and generators are on) and scene_info.\n\nScripts run in someone else's Blender:\n- Look shader nodes up by type, never by name (names are localized): next(n for n in mat.node_tree.nodes if n.type == \"BSDF_PRINCIPLED\").\n- Never hardcode enum identifiers; read them, for example [i.identifier for i in bpy.types.RenderSettings.bl_rna.properties[\"file_format\"].enum_items]. scene.render.engine under-reports: read the current value, and assign a new one inside try/except TypeError, whose message lists the valid engines.\n- Material colors go on shader node inputs; material.diffuse_color only affects the viewport.\n\nlook is how you see your work; use it as much as you need. Images stay in the conversation, so a smaller max_size keeps long sessions cheap.\n\nObjects can also come from existing libraries (search_assets, then import_asset: Poly Haven, Sketchfab, Poly Pizza) or be made to order (generate_3d: one new textured model from text or an image, 1-3 minutes, may cost the user a credit). A generation is one object, never a whole scene, the ground or parts to assemble. Imported and generated models arrive at arbitrary scale: use the reported world_bounding_box to size them and put them on the ground." do
  use_bindings :json

  # The addon bridge lives in hand-written Rust beside this file: one persistent
  # connection, one command at a time, the reply back as JSON text.
  rust_file "blender_bridge.rs", as: :blender_bridge
  rust_fn :blender_call, args: [:string, :i64, :string], returns: :string, from: :blender_bridge

  # Ruby's strip and Rust's trim() agree on the text these tools handle (script
  # source, captured stdout, user-supplied names), and calling Rust's own trim
  # keeps the generated code idiomatic: every Ruby .strip otherwise compiles to an
  # explicit-set trim and earns a W-STR-STRIP-RUBY warning.
  rust_item "fn trim_text(text: impl AsRef<str>) -> String { text.as_ref().trim().to_string() }"
  rust_fn :trim_text, args: [:string], returns: :string

  setting :blender_host, env: "BLENDER_HOST", default: "localhost", description: "host of the Blender addon bridge"
  setting :blender_port, env: "BLENDER_PORT", default: "9876", description: "port of the Blender addon bridge"
  setting :blender_scripts, env: "BLENDER_SCRIPTS", default: "vendor/mcp-for-blender/src/blender_mcp/blender_scripts.py", description: "path to the addon's blender_scripts.py, whose scripts this server runs inside Blender"
  setting :mcp_token, env: "MCP_TOKEN", secret: true, description: "bearer token every request to the HTTP transport must carry; required, so every run needs MCP_TOKEN set"
  setting :blender_extras, env: "BLENDER_EXTRAS", default: "mcp_extras.py", description: "path to mcp_extras.py, whose WIREFRAME and MESH_REPORT scripts this server runs inside Blender"

  # One command over the bridge: send, check the addon's status, and return the
  # result as JSON text (helpers cannot carry an opaque Json::Value).
  helper :blender_request, args: [:string, :i64, :string], returns: :string do |host, port, request|
    resp = Json.parse(rust(:blender_call, host, port, request)) || raise("Blender bridge unreachable; start the addon's server in Blender")
    status = Json.text(resp, "/status") || "error"
    raise (Json.text(resp, "/message") || "Blender returned an error") unless status == "success"
    Json.dump(Json.at(resp, "/result") || raise("the bridge returned no result")) || raise("could not encode the result")
  end

  # Run one of the addon's bundled blender_scripts.py scripts inside Blender via
  # execute_code, using its ARGS/RESULT_MARKER protocol, and return the JSON text
  # the script produced. The script is installed into Blender's session once and
  # then only named: the first call for a script sends its source, later calls
  # send a short invocation, so a long session does not resend the source.
  helper :run_script, args: [:string, :i64, :string, :string, :string], returns: :string do |host, port, scripts, name, arguments|
    script = Json.py_constant(scripts, name) || raise("#{name} not found in #{scripts}")
    qargs = Json.quote(arguments)
    qmodule = Json.quote("_mcp_scripts_#{name}_#{Json.short_hash(script)}")
    indented = rust(:trim_text, script).gsub(/\n/, "\n    ")
    source = "import json as _json\ndef _main():\n    #{indented}\n"
    qsource = Json.quote(source)
    invoke = "import sys, json as _json\nmod = sys.modules.get(#{qmodule})\nif mod is None:\n    print('__MCP_NEED_INSTALL__')\nelse:\n    mod.ARGS = _json.loads(#{qargs})\n    print('__MCP_RESULT__' + _json.dumps(mod._main()))\n"
    install = "import sys, types, json as _json\nmod = sys.modules.get(#{qmodule})\nif mod is None:\n    mod = types.ModuleType(#{qmodule})\n    exec(compile(#{qsource}, '<mcp_scripts>', 'exec'), mod.__dict__)\n    sys.modules[#{qmodule}] = mod\nmod.ARGS = _json.loads(#{qargs})\nprint('__MCP_RESULT__' + _json.dumps(mod._main()))\n"
    invoke_request = "{\"type\":\"execute_code\",\"params\":{\"code\":#{Json.quote(invoke)}}}"
    install_request = "{\"type\":\"execute_code\",\"params\":{\"code\":#{Json.quote(install)}}}"
    raw = Json.parse(rust(:blender_call, host, port, invoke_request))
    resp = raw || raise("Blender bridge unreachable; start the addon's server in Blender")
    status = Json.text(resp, "/status") || "error"
    stdout = Json.text(resp, "/result/result") || ""
    cold = if rust(:trim_text, stdout) == "__MCP_NEED_INSTALL__" then true else false end
    # A cold Blender has not seen this script yet: installing it and running it
    # in one more command costs a round trip once, and every later call sends
    # only the short invocation above.
    retry_resp = if cold then (Json.parse(rust(:blender_call, host, port, install_request)) || raise("Blender bridge unreachable; start the addon's server in Blender")) else resp end
    retry_status = if cold then (Json.text(retry_resp, "/status") || "error") else status end
    retry_stdout = if cold then (Json.text(retry_resp, "/result/result") || "") else stdout end
    raise (Json.text(retry_resp, "/message") || "Blender returned an error") unless retry_status == "success"
    retry_stdout.split("__MCP_RESULT__").last || raise("the script finished without a result")
  end

  # The native viewport capture: the addon's own screenshot command, which
  # needs no open 3D viewport area. Returns the PNG as base64.
  helper :viewport_png, args: [:string, :i64, :i32], returns: :string do |host, port, max_size|
    path = Json.temp_png("viewport")
    request = "{\"type\":\"get_viewport_screenshot\",\"params\":{\"max_size\":#{max_size},\"filepath\":#{Json.quote(path)}}}"
    value = Json.parse(blender_request(host, port, request)) || raise("could not parse the screenshot result")
    problem = Json.text(value, "/error") || ""
    raise problem unless problem == ""
    Json.take_file_base64(path) || raise("could not read the screenshot file")
  end

  # Run the addon's LOOK script with a ready-made argument object and return the
  # JSON it reports: what it drew, which views or frames, the framed size and
  # centre. The PNG it wrote is read separately. Unlike the native capture it
  # needs an open 3D viewport area, which is why viewport mode prefers
  # viewport_png.
  helper :look_info, args: [:string, :i64, :string, :string], returns: :string do |host, port, scripts, look_args|
    info = Json.parse(run_script(host, port, scripts, "LOOK", look_args)) || raise("could not parse the look result")
    problem = Json.text(info, "/error") || ""
    raise problem unless problem == ""
    Json.dump(info) || raise("could not encode the look result")
  end

  params :SceneParams do

    field :query, :string, description: "Case-insensitive filter on item names; empty means everything", default: ""
    field :limit, :i32, description: "How many items to return", default: 30, min: 1, max: 200
  end

  output :Scene do
    field :items, Json::Value, description: "The addon's list_scene_items result: items and total"
  end

  tool :scene, params: :SceneParams, title: "Scene items",
       description: "List objects, materials and collections in the current Blender scene, optionally filtered by name",
       output: :Scene, read_only: true, open_world: true do
    body do |query, limit|
      quoted = Json.quote(query)
      request = "{\"type\":\"list_scene_items\",\"params\":{\"query\":#{quoted},\"limit\":#{limit}}}"
      value = Json.parse(blender_request(setting(:blender_host), Integer(setting(:blender_port), 10), request)) || raise("could not parse the scene items")
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
       description: "Facts about the scene: what is there, where, how big, and how healthy meshes and rigs are. Runs the addon's scene-summary script inside Blender through execute_code",
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
      data = Json.parse(run_script(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_scripts), "SCENE_SUMMARY", arguments)) || raise("could not parse the scene summary")
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
      data = Json.parse(run_script(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_extras), "WIREFRAME", args)) || raise("could not parse the wireframe result")
      result(:TextReport, report: Json.text(data, "/report") || raise("the wireframe script returned no text"))
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
      data = Json.parse(run_script(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_extras), "MESH_REPORT", args)) || raise("could not parse the mesh report")
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
       description: "Run Python inside the running Blender session and return what it printed. Arbitrary code runs with Blender's own privileges",
       output: :CodeResult, destructive: true, open_world: true do
    body do |code|
      quoted = Json.quote(code)
      request = "{\"type\":\"execute_code\",\"params\":{\"code\":#{quoted}}}"
      value = Json.parse(blender_request(setting(:blender_host), Integer(setting(:blender_port), 10), request)) || raise("could not parse the result")
      output = Json.text(value, "/result") || ""
      result(:CodeResult, output: output)
    end
  end

  params :ObjectParams do
    field :name, :string, description: "Exact name of an object in the scene"
  end

  output :Object do
    field :object, Json::Value, description: "The addon's object info"
  end

  tool :object_info, params: :ObjectParams, title: "Object info",
       description: "Return details for one scene object by name",
       output: :Object, read_only: true, open_world: true do
    body do |name|
      quoted = Json.quote(name)
      request = "{\"type\":\"get_object_info\",\"params\":{\"name\":#{quoted}}}"
      value = Json.parse(blender_request(setting(:blender_host), Integer(setting(:blender_port), 10), request)) || raise("could not parse the object info")
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
      image(viewport_png(setting(:blender_host), Integer(setting(:blender_port), 10), max_size), "image/png")
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
    field :image, :string, description: "For image: an image in the file, or a path on disk, to show", optional: true
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
      image_name = image || ""
      target_json = Json.str_list_json(targets || [])
      views_json = Json.str_list_json(views || [])
      frames_json = Json.i64_list_json(frames || [])
      host = setting(:blender_host)
      port = Integer(setting(:blender_port), 10)
      path = Json.temp_png("look")
      arguments = "{\"mode\":#{Json.quote(mode)},\"shading\":#{Json.quote(s)},\"target\":#{target_json},\"views\":#{views_json},\"distance\":#{distance},\"view\":#{Json.quote(v)},\"frames\":#{frames_json},\"frame_count\":#{frame_count},\"max_size\":#{max_size},\"image\":#{Json.quote(image_name)},\"filepath\":#{Json.quote(path)}}"
      scripted = !(mode == "viewport" && s == "")
      caption = if scripted then look_info(host, port, setting(:blender_scripts), arguments) else "Viewport capture." end
      data = if scripted then (Json.take_file_base64(path) || raise("could not read the look image")) else viewport_png(host, port, max_size) end
      [image(data, "image/png"), text(caption)]
    end
  end

  params :CommandParams do
    field :name, :string, description: "The addon command to run",
          enum: ["ping", "get_scene_info", "get_world_state_snapshot", "get_addon_info",
                 "get_object_info", "list_scene_items", "get_viewport_screenshot",
                 "pick_viewport_object", "execute_code", "describe_node_type", "bpy_api_lookup",
                 "drain_human_activity", "get_telemetry_consent", "set_telemetry_consent",
                 "get_polyhaven_status", "get_hyper3d_status", "get_sketchfab_status",
                 "get_polypizza_status", "get_hunyuan3d_status", "get_tripo_status",
                 "export_scene", "get_polyhaven_categories", "search_polyhaven_assets",
                 "download_polyhaven_asset", "get_polyhaven_asset_preview", "set_texture",
                 "create_rodin_job", "poll_rodin_job_status", "import_generated_asset",
                 "search_sketchfab_models", "get_sketchfab_model_preview", "download_sketchfab_model",
                 "search_polypizza_models", "download_polypizza_model", "create_hunyuan_job",
                 "poll_hunyuan_job_status", "import_generated_asset_hunyuan"]
    field :args, :string, description: "JSON object of that command's arguments; {} when it takes none", default: "{}"
  end

  output :CommandResult do
    field :result, Json::Value, description: "The addon's raw result for the command"
  end

  tool :command, params: :CommandParams, title: "Blender command",
       description: "Run any command the Blender addon supports and return its raw result. Prefer the typed tools when one fits; use this for the long tail and for commands that take no arguments",
       output: :CommandResult, destructive: true, open_world: true do
    body do |name, args|
      request = "{\"type\":\"#{name}\",\"params\":#{args}}"
      value = Json.parse(blender_request(setting(:blender_host), Integer(setting(:blender_port), 10), request)) || raise("could not parse the result")
      result(:CommandResult, result: value)
    end
  end

  # --- Asset libraries: Poly Haven, Sketchfab, Poly Pizza ---
  #
  # Poly Pizza's API filters on numeric ids and the addon only validates ids,
  # so its category and licence names are resolved here, exactly as the Python
  # server's _polypizza_category_id / _polypizza_licence_id do.

  helper :polypizza_category_id, args: [:string], returns: :string do |category|
    stripped = rust(:trim_text, category)
    digits_only = stripped != "" && stripped.gsub(/[0-9]/, "") == ""
    if digits_only
      value = stripped.to_i
      raise "Poly Pizza category id #{value} is out of range (valid ids are 0-11)" if value > 11
      "#{value}"
    else
      key = stripped.downcase.gsub(/[^a-z0-9]/, "")
      case key
      when "fooddrink", "food", "drink", "drinks" then "0"
      when "clutter" then "1"
      when "weapons", "weapon" then "2"
      when "transport", "vehicle", "vehicles", "transportation" then "3"
      when "furnituredecor", "furniture", "decor" then "4"
      when "objects", "object", "prop", "props" then "5"
      when "nature", "plant", "plants" then "6"
      when "animals", "animal" then "7"
      when "buildings", "building", "architecture", "buildingsarchitecture" then "8"
      when "peoplecharacters", "person", "character", "characters", "people" then "9"
      when "sceneslevels", "scene", "scenes", "level", "levels" then "10"
      when "other" then "11"
      else raise("Unknown Poly Pizza category '#{category}'. Valid categories: Food & Drink, Clutter, Weapons, Transport, Furniture & Decor, Objects, Nature, Animals, Buildings, People & Characters, Scenes & Levels, Other.")
      end
    end
  end

  helper :polypizza_licence_id, args: [:string], returns: :string do |licence|
    stripped = rust(:trim_text, licence)
    digits_only = stripped != "" && stripped.gsub(/[0-9]/, "") == ""
    if digits_only
      value = stripped.to_i
      raise "Poly Pizza licence id #{value} is invalid (0 = CC-BY, 1 = CC0)" if value > 1
      "#{value}"
    else
      key = stripped.downcase.gsub(/[^a-z0-9]/, "")
      if key.start_with?("ccby") then "0"
      elsif key.start_with?("cc0") then "1"
      elsif key == "publicdomain" then "1"
      else raise("Unknown Poly Pizza licence '#{licence}'. Use 'CC0' or 'CC-BY'.")
      end
    end
  end

  helper :download_polyhaven, args: [:string, :i64, :string, :string, :string, :string], returns: :string do |host, port, id, asset_type, resolution, file_format|
    raise "polyhaven needs asset_type: hdris, textures or models" unless asset_type == "hdris" || asset_type == "textures" || asset_type == "models"
    ff = if file_format == "" then "null" else Json.quote(file_format) end
    request = "{\"type\":\"download_polyhaven_asset\",\"params\":{\"asset_id\":#{Json.quote(id)},\"asset_type\":#{Json.quote(asset_type)},\"resolution\":#{Json.quote(resolution)},\"file_format\":#{ff}}}"
    blender_request(host, port, request)
  end

  helper :download_sketchfab, args: [:string, :i64, :string, :f64], returns: :string do |host, port, id, target_size|
    raise "sketchfab needs target_size (metres, largest dimension)" if target_size == 0.0
    request = "{\"type\":\"download_sketchfab_model\",\"params\":{\"uid\":#{Json.quote(id)},\"normalize_size\":true,\"target_size\":#{target_size}}}"
    blender_request(host, port, request)
  end

  helper :download_polypizza, args: [:string, :i64, :string, :f64], returns: :string do |host, port, id, target_size|
    normalize = target_size != 0.0
    size = if normalize then target_size else 1.0 end
    request = "{\"type\":\"download_polypizza_model\",\"params\":{\"model_id\":#{Json.quote(id)},\"normalize_size\":#{normalize},\"target_size\":#{size}}}"
    blender_request(host, port, request)
  end

  helper :apply_texture_one, args: [:string, :string, :string, :i64, :string, :string], returns: :string do |source, asset_type, host, port, object_name, texture_id|
    if source == "polyhaven" && asset_type == "textures"
      request = "{\"type\":\"set_texture\",\"params\":{\"object_name\":#{Json.quote(object_name)},\"texture_id\":#{Json.quote(texture_id)}}}"
      blender_request(host, port, request)
    else
      ""
    end
  end

  params :AssetSearchParams do
    field :source, :string, description: "Which library to search", enum: ["polyhaven", "sketchfab", "polypizza"]
    field :query, :string, description: "What you are looking for, in plain words", default: ""
    field :asset_type, :string, description: "polyhaven only: which asset types to search", enum: ["all", "hdris", "textures", "models"], default: "all"
    field :category, :string, description: "polyhaven: a category path; sketchfab: comma-separated categories; polypizza: a category name such as \"Furniture & Decor\" or an id 0-11", optional: true
    field :min_size_m, :f64, description: "polyhaven only: minimum real-world size in metres; use 2+ for walls, floors and ground", optional: true
    field :licence, :string, description: "polypizza only: \"CC0\" or \"CC-BY\"", optional: true
    field :animated, :bool, description: "polypizza only: return animated models only", default: false
    field :limit, :i32, description: "How many results to return", default: 20, min: 1, max: 50
  end

  tool :search_assets, params: :AssetSearchParams, title: "Search asset libraries",
       description: "Search Poly Haven (HDRIs, PBR textures and models, all CC0), Sketchfab (user-made models) or Poly Pizza (stylised low-poly models) and return the addon's results as JSON; each result carries the id that import_asset takes. Poly Haven attribute filters are not typed; run them with command(name: \"search_polyhaven_assets\", args: ...). Result thumbnails (previews in the Python server, up to 6) are not fetched; to see one, call command(name: \"get_polyhaven_asset_preview\", ...) or get_sketchfab_model_preview.",
       read_only: true, open_world: true do
    body do |source, query, asset_type, category, min_size_m, licence, animated, limit|
      category_text = category || ""
      licence_text = licence || ""
      raise "sketchfab needs a query" if source == "sketchfab" && query == ""
      raise "polypizza needs a query or at least one filter (category, licence, or animated)" if source == "polypizza" && rust(:trim_text, query) == "" && category_text == "" && licence_text == "" && !animated
      host = setting(:blender_host)
      port = Integer(setting(:blender_port), 10)
      query_json = Json.quote(query)
      category_json = if category_text == "" then "null" else Json.quote(category_text) end
      min_size_json = if min_size_m.nil? then "null" else min_size_m.to_s end
      polypizza_category_json = if source != "polypizza" || category_text == "" then "null" else polypizza_category_id(category_text) end
      licence_json = if source != "polypizza" || licence_text == "" then "null" else polypizza_licence_id(licence_text) end
      request = if source == "polyhaven"
        "{\"type\":\"search_polyhaven_assets\",\"params\":{\"asset_type\":#{Json.quote(asset_type)},\"category\":#{category_json},\"query\":#{query_json},\"limit\":#{limit},\"min_size_m\":#{min_size_json}}}"
      elsif source == "sketchfab"
        "{\"type\":\"search_sketchfab_models\",\"params\":{\"query\":#{query_json},\"categories\":#{category_json},\"count\":#{limit},\"downloadable\":true}}"
      else
        "{\"type\":\"search_polypizza_models\",\"params\":{\"query\":#{query_json},\"category\":#{polypizza_category_json},\"licence\":#{licence_json},\"animated\":#{animated},\"limit\":#{limit}}}"
      end
      blender_request(host, port, request)
    end
  end

  params :AssetImportParams do
    field :source, :string, description: "Which library the asset came from", enum: ["polyhaven", "sketchfab", "polypizza"]
    field :id, :string, description: "The asset's id from search_assets (the uid for sketchfab)"
    field :asset_type, :string, description: "polyhaven only, required: hdris (becomes the world lighting), textures (builds a PBR material) or models", enum: ["hdris", "textures", "models"], optional: true
    field :target_size, :f64, description: "Metres across the model's largest dimension (chair 1.0, car 4.5, cup 0.12); required for sketchfab, recommended for polypizza", optional: true
    field :apply_to, :string_list, description: "Objects to apply a downloaded texture to; polyhaven textures only, replaces their materials", optional: true
    field :resolution, :string, description: "polyhaven only: texture or HDRI resolution", enum: ["1k", "2k", "4k", "8k"], default: "1k"
    field :file_format, :string, description: "polyhaven only: hdr/exr for HDRIs, jpg/png/exr for textures", optional: true
  end

  tool :import_asset, params: :AssetImportParams, title: "Import an asset",
       description: "Download an asset found with search_assets and bring it into the scene: Poly Haven through download_polyhaven_asset, Sketchfab through download_sketchfab_model, Poly Pizza through download_polypizza_model. A Poly Haven texture given apply_to is also applied to each named object with set_texture. Check the reported world_bounding_box and put the model on the ground",
       destructive: true, open_world: true do
    body do |source, id, asset_type, target_size, apply_to, resolution, file_format|
      host = setting(:blender_host)
      port = Integer(setting(:blender_port), 10)
      at = asset_type || ""
      ts = target_size || 0.0
      ff = file_format || ""
      names = apply_to || []
      imported = if source == "polyhaven"
        download_polyhaven(host, port, id, at, resolution, ff)
      elsif source == "sketchfab"
        download_sketchfab(host, port, id, ts)
      else
        download_polypizza(host, port, id, ts)
      end
      parsed = Json.parse(imported)
      problem = Json.text(parsed || raise("could not parse the download result"), "/error") || ""
      if source == "polyhaven" && at == "textures" && problem == ""
        names.each { |object_name| apply_texture_one(source, at, host, port, object_name, id) }
        "#{imported}\n\nApplied the texture to the given objects."
      else
        imported
      end
    end
  end

  transport :http, port: 8787, auth_setting: :mcp_token
end
