# typed: true
server "blender", version: "0.1.0", instructions: "MCP for Blender drives the user's live Blender. execute_code runs Python there with the full bpy API, so anything Blender can do, you can do; screenshot and look show you the result.\n\nStart with command(name: \"get_addon_info\") (Blender version, which libraries and generators are on) and scene_info.\n\nScripts run in someone else's Blender:\n- Look shader nodes up by type, never by name (names are localized): next(n for n in mat.node_tree.nodes if n.type == \"BSDF_PRINCIPLED\").\n- Never hardcode enum identifiers; read them, for example [i.identifier for i in bpy.types.RenderSettings.bl_rna.properties[\"file_format\"].enum_items]. scene.render.engine under-reports: read the current value, and assign a new one inside try/except TypeError, whose message lists the valid engines.\n- Material colors go on shader node inputs; material.diffuse_color only affects the viewport.\n\nlook is how you see your work; use it as much as you need. Images stay in the conversation, so a smaller max_size keeps long sessions cheap.\n\nObjects can also come from existing libraries (search_assets, then import_asset: Poly Haven, Sketchfab, Poly Pizza) or be made to order (generate_3d: one new textured model from text or an image, 1-3 minutes, may cost the user a credit). A generation is one object, never a whole scene, the ground or parts to assemble. Imported and generated models arrive at arbitrary scale: use the reported world_bounding_box to size them and put them on the ground." do
  use_bindings :json
  use_bindings :imagefile

  # The addon bridge lives in hand-written Rust beside this file: one persistent
  # connection, one command at a time, the reply back as JSON text.
  rust_file "blender_bridge.rs", as: :blender_bridge
  rust_fn :blender_call, args: [:string, :i64, :string], returns: :string, from: :blender_bridge

  # Ruby's strip and Rust's trim() agree on the text these tools handle (script
  # source, captured stdout, user-supplied names), and calling Rust's own trim
  # keeps the generated code idiomatic: every Ruby .strip otherwise compiles to an
  # explicit-set trim and earns a W-STR-STRIP-RUBY warning.
  #
  # The generation helpers below need three things the DSL cannot express itself:
  # a sleep between poll attempts (the DSL has no sleep, and the poll loop must
  # not spin), an image read as base64 and an extension for Hyper3D Rodin's
  # main-site request (it takes the bytes rather than a path), and Rust's trim
  # for the shared script installer. They live in blender_gen.rs beside the
  # bridge and are declared with rust_fn from: :blender_gen, so rustc checks
  # them as a file rather than as an inline string, and every Ruby .strip stays
  # warning-free. sleep_ms is async: a body that calls it (gen_wait) is compiled
  # async too, and the tool bodies that reach it (generate_3d, make_3d) await the
  # whole chain; the DSL infers that from the call, so no helper declares async.
  # base64 is already a binding crate, so blender_gen.rs may use it too.
  rust_file "blender_gen.rs", as: :blender_gen
  rust_fn :sleep_ms, args: [:i64], returns: :i64, async: true, from: :blender_gen
  rust_fn :gen_file_base64, args: [:string], returns: :string, from: :blender_gen
  rust_fn :gen_path_suffix, args: [:string], returns: :string, from: :blender_gen
  rust_fn :trim_text, args: [:string], returns: :string, from: :blender_gen

  # Reading an image as text, but in Rust rather than inside Blender: the
  # arithmetic is unit-testable with cargo test and needs no Blender session.
  # The image crate is declared in bindings/imagefile.rb; dependencies land in
  # the crate's Cargo.toml, so this module can use it directly.
  rust_file "textvision.rs", as: :textvision
  rust_fn :grid, args: [:string, :i32], returns: :string, from: :textvision
  rust_fn :ansi, args: [:string, :i32, :string, :string], returns: :string, from: :textvision

  setting :blender_host, env: "BLENDER_HOST", default: "localhost", description: "host of the Blender addon bridge"
  setting :blender_port, env: "BLENDER_PORT", default: "9876", description: "port of the Blender addon bridge"
  setting :blender_scripts, env: "BLENDER_SCRIPTS", default: "vendor/mcp-for-blender/src/blender_mcp/blender_scripts.py", description: "path to the addon's blender_scripts.py, whose scripts this server runs inside Blender"
  setting :mcp_token, env: "MCP_TOKEN", secret: true, description: "bearer token every request to the HTTP transport must carry; required, so every run needs MCP_TOKEN set"
  setting :blender_python, env: "BLENDER_PYTHON", default: "python/mcp_scripts.py", description: "path to the Python module the scene and output tools run: a real module, read here and installed into Blender once per content hash"

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

  # Run one entry point in our own Python module: a real file in the repository,
  # read here and installed into Blender's sys.modules under a hash of its text.
  # A changed file installs once under a new module name and every later call
  # sends only the short invocation, so the wire cost is a few hundred bytes per
  # call. compile() is handed the file's own path, so a traceback out of Blender
  # names a line in that file instead of a generated string. Each entry point
  # takes the tool's arguments as a dict and returns a dict whose "report" is the
  # text. Upstream's own blender_scripts.py constants keep using run_script.
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
    resp = raw || raise("Blender bridge unreachable; start the addon's server in Blender")
    status = Json.text(resp, "/status") || "error"
    stdout = Json.text(resp, "/result/result") || ""
    cold = if rust(:trim_text, stdout) == "__MCP_NEED_INSTALL__" then true else false end
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

  # --- 3D generation: text or image to one imported, textured object ---
  #
  # generate_3d and make_3d share this layer. The addon's generators (Tripo,
  # Hunyuan3D, Hyper3D Rodin) each have their own submit, poll and import
  # commands; the helpers below choose one, submit, poll with the async sleep
  # until the wait budget runs out, then import and report the model's world
  # bounding box and how to place it. A poll that outlives the budget returns
  # a resumable handle instead of losing the paid generation. Every
  # handler-level failure arrives as status: "success" with an {"error": ...}
  # result, so gen_problem checks for that rather than trusting the bridge's
  # status, and a reply that is not JSON at all is reported as unparseable.
  helper :gen_default_name, args: [:string], returns: :string do |prompt|
    cleaned = prompt.gsub(/[^A-Za-z0-9]/, " ")
    word = cleaned.split.first || ""
    if word == ""
      "Generated"
    else
      initial = (word[0, 1] || "").upcase
      tail = word[1, word.length - 1] || ""
      "#{initial}#{tail}"
    end
  end

  # A generator's status command returns {"enabled": ...}. gen_status reads
  # that flag as a bool, and gen_choose turns a false into the message that
  # names what to switch on in Blender's sidebar.
  helper :gen_status, args: [:string, :i64, :string], returns: :bool do |host, port, command|
    request = "{\"type\":\"#{command}\",\"params\":{}}"
    parsed = Json.parse(blender_request(host, port, request)) || raise("could not parse #{command}")
    enabled = Json.at(parsed, "/enabled") || raise("the #{command} reply has no enabled flag")
    flag = Json.dump(enabled) || raise("could not encode #{command}")
    flag == "true"
  end

  # Resolve the requested provider to one that is actually enabled: auto
  # prefers Tripo, then Hunyuan3D, then Hyper3D Rodin, and any other name must
  helper :gen_choose, args: [:string, :i64, :string], returns: :string do |host, port, requested|
    want = requested.downcase
    if want == "auto"
      tripo = gen_status(host, port, "get_tripo_status")
      hunyuan = gen_status(host, port, "get_hunyuan3d_status")
      hyper = gen_status(host, port, "get_hyper3d_status")
      if tripo then "tripo" elsif hunyuan then "hunyuan3d" elsif hyper then "hyper3d" else raise("No 3D generator is enabled. In Blender's MCP for Blender sidebar (press N in the 3D Viewport), turn on Hunyuan3D or Hyper3D Rodin with an API key, or use MCP for Blender Premium (no keys needed): https://mcp-for-blender.com/premium") end
    elsif want == "tripo"
      gen_status(host, port, "get_tripo_status") ? "tripo" : raise("Tripo is only available with MCP for Blender Premium. If Premium is on, update the Blender addon: run `uvx mcp-for-blender install-addon`, then restart Blender.")
    elsif want == "hunyuan3d"
      gen_status(host, port, "get_hunyuan3d_status") ? "hunyuan3d" : raise("Hunyuan3D is not enabled. Turn it on and add an API key (or point it at a local server) in the MCP for Blender sidebar in Blender (press N in the 3D Viewport), then restart the connection.")
    elsif want == "hyper3d"
      gen_status(host, port, "get_hyper3d_status") ? "hyper3d" : raise("Hyper3D Rodin is not enabled. Turn it on and add an API key in the MCP for Blender sidebar in Blender (press N in the 3D Viewport), then restart the connection.")
    else
      raise("Unknown provider '#{requested}'. Use one of: auto, hyper3d, hunyuan3d, tripo")
    end
  end

  # The addon's handlers answer status: "success" even when the command
  # failed; the failure is an {"error": ...} (or a code/message pair) inside
  # the result. gen_problem pulls that out and returns "" when there is none.
  helper :gen_problem, args: [:string], returns: :string do |text|
    parsed = Json.parse(text) || raise("the Blender addon returned an unparseable reply: #{text}")
    as_text = Json.text(parsed, "") || ""
    as_error = Json.text(parsed, "/error") || ""
    as_code = Json.text(parsed, "/code") || ""
    as_message = Json.text(parsed, "/message") || ""
    if as_text != "" && as_text.downcase.start_with?("error")
      as_text
    elsif as_code != ""
      if as_message != "" then "#{as_message} (code #{as_code}; tell the user as written and don't retry automatically)" else "#{as_code} (tell the user as written and don't retry automatically)" end
    else
      as_error
    end
  end

  # One raw addon command with a ready-made params object, through the shared
  # bridge helper, so the generation commands all take the same path.
  helper :gen_raw, args: [:string, :i64, :string, :string], returns: :string do |host, port, command, params|
    request = "{\"type\":\"#{command}\",\"params\":#{params}}"
    blender_request(host, port, request)
  end

  # Submit one job to the chosen provider and return a small JSON reply with
  # either {"status":"job","handle":...} or a finished local Hunyuan3D
  # {"status":"done",...}; a submit failure raises the handler's own message.
  helper :gen_submit, args: [:string, :i64, :string, :string, :string, :string, :string], returns: :string do |host, port, provider, prompt, image, quality, bbox_json|
    if provider == "tripo"
      quality_field = if quality == "" then "" else ",\"quality\":#{Json.quote(quality)}" end
      params = "{\"text_prompt\":#{Json.quote(prompt)},\"image\":#{Json.quote(image)}#{quality_field}}"
      raw = gen_raw(host, port, "create_tripo_job", params)
      problem = gen_problem(raw)
      raise problem unless problem == ""
      parsed = Json.parse(raw) || raise("could not parse the Tripo reply: #{raw}")
      request_id = Json.text(parsed, "/request_id") || ""
      raise "Tripo returned no request id: #{raw}" if request_id == ""
      "{\"status\":\"job\",\"handle\":\"tripo:rid:#{request_id}\"}"
    elsif provider == "hunyuan3d"
      quality_field = if quality == "" then "" else ",\"quality\":#{Json.quote(quality)}" end
      params = "{\"text_prompt\":#{Json.quote(prompt)},\"image\":#{Json.quote(image)}#{quality_field}}"
      raw = gen_raw(host, port, "create_hunyuan_job", params)
      problem = gen_problem(raw)
      raise problem unless problem == ""
      parsed = Json.parse(raw) || raise("could not parse the Hunyuan3D reply: #{raw}")
      nested_message = Json.text(parsed, "/Response/Error/Message") || ""
      nested_plain = Json.text(parsed, "/Response/Error") || ""
      nested_error = if nested_message != "" then nested_message else nested_plain end
      raise nested_error unless nested_error == ""
      job_id = Json.text(parsed, "/Response/JobId") || ""
      status = Json.text(parsed, "/status") || ""
      if job_id != ""
        "{\"status\":\"job\",\"handle\":\"hunyuan3d:job:job_#{job_id}\"}"
      elsif status == "DONE"
        "{\"status\":\"done\",\"message\":\"Generated and imported by the local Hunyuan3D server. Find it with get_scene_info.\"}"
      else
        raise("Hunyuan3D returned no job: #{raw}")
      end
    else
      images = if image == ""
        "null"
      elsif image.start_with?("http://") || image.start_with?("https://")
        "[#{Json.quote(image)}]"
      else
        data = rust(:gen_file_base64, image)
        raise "Image not found: #{image}. Give an absolute image file path or an http(s) URL, or use a prompt instead." if data == ""
        "[[#{Json.quote(rust(:gen_path_suffix, image))},#{Json.quote(data)}]]"
      end
      rodin_prompt = if image == "" then Json.quote(prompt) else "null" end
      params = "{\"text_prompt\":#{rodin_prompt},\"images\":#{images},\"bbox_condition\":#{bbox_json}}"
      raw = gen_raw(host, port, "create_rodin_job", params)
      problem = gen_problem(raw)
      raise problem unless problem == ""
      parsed = Json.parse(raw) || raise("could not parse the Hyper3D reply: #{raw}")
      uuid = Json.text(parsed, "/uuid") || ""
      subscription = Json.text(parsed, "/jobs/subscription_key") || ""
      request_id = Json.text(parsed, "/request_id") || ""
      if uuid != "" && subscription != ""
        "{\"status\":\"job\",\"handle\":\"hyper3d:main:#{uuid}|#{subscription}\"}"
      elsif request_id != ""
        "{\"status\":\"job\",\"handle\":\"hyper3d:fal:#{request_id}\"}"
      else
        raise("Hyper3D Rodin returned no job: #{raw}")
      end
    end
  end

  # One poll: ask the provider for the job's state and return a small JSON
  # object with a state of running, done or failed. The detail carries the
  helper :gen_poll, args: [:string, :i64, :string, :string, :string, :string], returns: :string do |host, port, provider, kind, ident, hint|
    if provider == "tripo" || (provider == "hyper3d" && kind == "fal")
      command = if provider == "tripo" then "poll_tripo_job_status" else "poll_rodin_job_status" end
      raw = gen_raw(host, port, command, "{\"request_id\":#{Json.quote(ident)}}")
      parsed = Json.parse(raw) || raise("could not parse the status reply: #{raw}")
      status = (Json.text(parsed, "/status") || "").upcase
      if status == "COMPLETED"
        problem = gen_problem(raw)
        raise "#{problem}. The generation may still be running or finished. #{hint}" unless problem == ""
        "{\"state\":\"done\",\"detail\":\"\"}"
      elsif status != "" && status != "IN_QUEUE" && status != "IN_PROGRESS"
        detail = Json.text(parsed, "/error") || status
        "{\"state\":\"failed\",\"detail\":#{Json.quote(detail)}}"
      else
        problem = gen_problem(raw)
        raise "#{problem}. The generation may still be running or finished. #{hint}" unless problem == ""
        detail = if status == "" then "IN_QUEUE" else status end
        "{\"state\":\"running\",\"detail\":#{Json.quote(detail)}}"
      end
    elsif provider == "hyper3d"
      subscription = ident.split("|").last || ident
      raw = gen_raw(host, port, "poll_rodin_job_status", "{\"subscription_key\":#{Json.quote(subscription)}}")
      problem = gen_problem(raw)
      raise "#{problem}. The generation may still be running or finished. #{hint}" unless problem == ""
      parsed = Json.parse(raw) || raise("could not parse the Rodin status reply: #{raw}")
      statuses = Json.text_list(parsed, "/status_list") || []
      joined = statuses.join(", ")
      done = statuses.length > 0 && joined.gsub("Done", "").gsub(",", "").gsub(" ", "") == ""
      failed = joined.include?("Failed") || joined.include?("Canceled")
      detail = if statuses.length == 0 then "Waiting" else joined end
      if done
        "{\"state\":\"done\",\"detail\":\"\"}"
      elsif failed
        "{\"state\":\"failed\",\"detail\":#{Json.quote(detail)}}"
      else
        "{\"state\":\"running\",\"detail\":#{Json.quote(detail)}}"
      end
    else
      raw = gen_raw(host, port, "poll_hunyuan_job_status", "{\"job_id\":#{Json.quote(ident)}}")
      problem = gen_problem(raw)
      raise "#{problem}. The generation may still be running or finished. #{hint}" unless problem == ""
      parsed = Json.parse(raw) || raise("could not parse the Hunyuan3D status reply: #{raw}")
      status = Json.text(parsed, "/Response/Status") || ""
      poll_message = Json.text(parsed, "/Response/ErrorMessage") || ""
      poll_plain = Json.text(parsed, "/Response/Error") || ""
      nested_error = if poll_message != "" then poll_message else poll_plain end
      if status == "DONE"
        file_count = Json.count(parsed, "/Response/ResultFile3Ds") || 0
        url0 = if file_count > 0 then Json.text(parsed, "/Response/ResultFile3Ds/0/Url") || "" else "" end
        type0 = if file_count > 0 then (Json.text(parsed, "/Response/ResultFile3Ds/0/Type") || "").upcase else "" end
        url1 = if file_count > 1 then Json.text(parsed, "/Response/ResultFile3Ds/1/Url") || "" else "" end
        type1 = if file_count > 1 then (Json.text(parsed, "/Response/ResultFile3Ds/1/Type") || "").upcase else "" end
        model = if type0 == "GLB" then url0 elsif type1 == "GLB" then url1 elsif url0 != "" then url0 else url1 end
        if model == ""
          "{\"state\":\"failed\",\"detail\":\"finished without a model file\"}"
        else
          "{\"state\":\"done\",\"detail\":#{Json.quote(model)}}"
        end
      elsif status == "FAIL" || nested_error != ""
        detail = if nested_error != "" then nested_error else "generation failed" end
        "{\"state\":\"failed\",\"detail\":#{Json.quote(detail)}}"
      else
        detail = if status == "" then "WAIT" else status end
        "{\"state\":\"running\",\"detail\":#{Json.quote(detail)}}"
      end
    end
  end

  # Import a finished job and return "" on success or a reason on failure;
  helper :gen_import, args: [:string, :i64, :string, :string, :string, :string, :string, :string], returns: :string do |host, port, provider, kind, ident, name, detail, hint|
    raw = if provider == "tripo"
      gen_raw(host, port, "import_generated_asset_tripo", "{\"request_id\":#{Json.quote(ident)},\"name\":#{Json.quote(name)}}")
    elsif provider == "hyper3d" && kind == "fal"
      gen_raw(host, port, "import_generated_asset", "{\"request_id\":#{Json.quote(ident)},\"name\":#{Json.quote(name)}}")
    elsif provider == "hyper3d"
      task_uuid = ident.split("|").first || ident
      gen_raw(host, port, "import_generated_asset", "{\"task_uuid\":#{Json.quote(task_uuid)},\"name\":#{Json.quote(name)}}")
    else
      gen_raw(host, port, "import_generated_asset_hunyuan", "{\"name\":#{Json.quote(name)},\"zip_file_url\":#{Json.quote(detail)}}")
    end
    problem = gen_problem(raw)
    raise "#{problem}. The generation may still be running or finished. #{hint}" unless problem == ""
    parsed = Json.parse(raw) || raise("could not parse the import reply: #{raw}")
    succeed = if Json.has?(parsed, "/succeed") then Json.dump(Json.at(parsed, "/succeed") || raise("could not read the import flag")) || "true" else "true" end
    if succeed == "false"
      reason_error = Json.text(parsed, "/error") || ""
      reason_message = Json.text(parsed, "/message") || ""
      reason = if reason_error != "" then reason_error elsif reason_message != "" then reason_message else "the addon reported no imported object" end
      raise("#{reason}. The generation may have finished but the import failed. #{hint}")
    else
      ""
    end
  end

  # The success reply: "Generated and imported ...", then the imported
  # object's world_bounding_box and size from the addon's BOUNDS script, plus
  # the placement guidance, so the model can be sized and grounded.
  helper :gen_success, args: [:string, :i64, :string, :string, :string], returns: :string do |host, port, scripts, name, provider|
    reply = "Generated and imported '#{name}' with #{provider}."
    arguments = "{\"names\":[#{Json.quote(name)}]}"
    bounds = Json.parse(run_script(host, port, scripts, "BOUNDS", arguments)) || raise("could not read the bounding box")
    count = Json.count(bounds, "") || 0
    if count == 0
      reply
    else
      b_name = Json.text(bounds, "/0/name") || name
      lo0 = Json.f64(bounds, "/0/world_bounding_box/0/0") || 0.0
      lo1 = Json.f64(bounds, "/0/world_bounding_box/0/1") || 0.0
      lo2 = Json.f64(bounds, "/0/world_bounding_box/0/2") || 0.0
      hi0 = Json.f64(bounds, "/0/world_bounding_box/1/0") || 0.0
      hi1 = Json.f64(bounds, "/0/world_bounding_box/1/1") || 0.0
      hi2 = Json.f64(bounds, "/0/world_bounding_box/1/2") || 0.0
      s0 = Json.f64(bounds, "/0/size/0") || 0.0
      s1 = Json.f64(bounds, "/0/size/1") || 0.0
      s2 = Json.f64(bounds, "/0/size/2") || 0.0
      "#{reply} world_bounding_box min [#{lo0}, #{lo1}, #{lo2}], max [#{hi0}, #{hi1}, #{hi2}] (size #{s0} x #{s1} x #{s2} m). Generated models have arbitrary scale and facing: scale it to real size, put its lowest point on the ground, rotate it to face the right way, then look(mode=\"angles\", target=[\"#{b_name}\"])."
    end
  end

  # Wait for a handle to finish: poll until the job is done, failed, or the
  # budget runs out, sleeping five seconds between polls. Done imports the
  # model and reports it; a timeout returns a reply that carries the handle
  # so the caller can resume without starting (and paying for) a new job.
  helper :gen_wait, args: [:string, :i64, :string, :string, :string, :i64], returns: :string do |host, port, scripts, handle, name, polls|
    provider = handle.split(":").first || ""
    rest = handle[provider.length + 1, handle.length] || ""
    kind = rest.split(":").first || ""
    ident = rest[kind.length + 1, rest.length] || ""
    known = provider == "tripo" || provider == "hunyuan3d" || provider == "hyper3d"
    raise "Not a generation job handle: #{handle}. It should look like provider:kind:id, as an earlier generate_3d reply returned." unless known && kind != "" && ident != ""
    hint = "Call generate_3d(job=\"#{handle}\", name=\"#{name}\") to keep waiting; it imports the model when it's ready. Don't start a new generation."
    polls.times.each do |i|
      polled = gen_poll(host, port, provider, kind, ident, hint)
      parsed = Json.parse(polled) || raise("could not parse the poll result: #{polled}")
      state = Json.text(parsed, "/state") || "running"
      detail = Json.text(parsed, "/detail") || ""
      if state == "done"
        import_failed = gen_import(host, port, provider, kind, ident, name, detail, hint)
        if import_failed != ""
          return "Import failed. #{hint}"
        else
          return gen_success(host, port, scripts, name, provider)
        end
      elsif state == "failed"
        return "Generation failed: #{detail}. This attempt was not imported. Start a new generation when you are ready."
      elsif i + 1 >= polls
        return "Still generating (#{provider}: #{detail}). #{hint}"
      else
        paused = rust(:sleep_ms, 5000)
        paused > 0
      end
    end
    "Still generating (#{provider}: unknown). #{hint}"
  end

  # Hyper3D Rodin's bbox_condition is three positive proportions or absent; a
  # three-element check here keeps the request well-formed.
  helper :gen_bbox, args: [:i64_list], returns: :string do |bbox_condition|
    if bbox_condition.length == 0
      "null"
    elsif bbox_condition.length != 3
      raise("bbox_condition must be three positive numbers [length, width, height]")
    elsif bbox_condition.any? { |value| value <= 0 }
      raise("bbox_condition must be three positive numbers [length, width, height]")
    else
      Json.i64_list_json(bbox_condition)
    end
  end

  # The one entry point both tools use. With a job handle it resumes; without
  # one it checks that exactly one of prompt/image was given, chooses a
  # provider, submits, then waits. wait_seconds is the caller's budget, capped
  helper :gen_run, args: [:string, :i64, :string, :string, :string, :string, :string, :string, :string, :string, :i64], returns: :string do |host, port, scripts, prompt, image, name, provider, quality, bbox_json, job, wait_seconds|
    budget = if wait_seconds > 45 then 45 else wait_seconds end
    polls = if budget < 5 then 1 else budget / 5 end
    if job != ""
      resume_name = if name == "" then "Generated" else name end
      gen_wait(host, port, scripts, job, resume_name, polls)
    else
      raise "give exactly one of prompt or image." if (prompt == "") == (image == "")
      chosen = gen_choose(host, port, provider.downcase)
      object_name = if name == "" then gen_default_name(prompt) else name end
      submitted = gen_submit(host, port, chosen, prompt, image, quality, bbox_json)
      parsed = Json.parse(submitted) || raise("could not parse the submit result: #{submitted}")
      status = Json.text(parsed, "/status") || ""
      if status == "job"
        job_handle = Json.text(parsed, "/handle") || raise("the generation returned no job handle")
        gen_wait(host, port, scripts, job_handle, object_name, polls)
      else
        message = Json.text(parsed, "/message") || "Generation finished."
        message
      end
    end
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
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "wireframe", args)) || raise("could not parse the wireframe result")
      result(:TextReport, report: Json.text(data, "/report") || raise("the wireframe script returned no text"))
    end
  end

  params :ImageReportParams do
    field :source, :string, description: "Name of an image already in the file, or a path to an image on disk"
    field :width, :i32, description: "Characters across; rows follow the image's aspect", default: 116, min: 40, max: 200
  end

  tool :image_report, params: :ImageReportParams, title: "Read an image as text",
       description: "Describe an image to a reader that cannot see it: dimensions and aspect, the mean colour and the six most common colours, then two character grids over the same cells, one for tone (dark to bright) and one for hue (red/yellow/green/cyan/blue/magenta, grey or desaturated as a dot). Use it when an image content block cannot be read directly.",
       output: :TextReport, read_only: true, open_world: true do
    body do |source, width|
      args = "{\"source\":#{Json.quote(source)},\"width\":#{width}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "image_report", args)) || raise("could not parse the image report")
      result(:TextReport, report: Json.text(data, "/report") || raise("the image script returned no text"))
    end
  end

  params :ImageReportRustParams do
    field :source, :string, description: "Path to an image file on the machine this server runs on"
    field :width, :i32, description: "Cells across; rows follow the image's aspect at 2:1 cells", default: 96, min: 40, max: 200
  end

  tool :image_report_rust, params: :ImageReportRustParams, title: "Read an image as text (Rust)",
       description: "The same job as image_report, and more, computed in this server's own Rust rather than inside Blender: dimensions, aspect, mean and the most common colours, a tone grid, a hue-and-strength grid (case carries saturation), a spectrum ordered by hue, and a summary naming what is in the picture and roughly where. It reads the file itself, so it needs no Blender session and works while the addon is stopped. Kept beside image_report so one picture can go through both and the texts compared.",
       output: :TextReport, read_only: true, open_world: true do
    body do |source, width|
      report = rust(:grid, source, width)
      bytes = ImageFile.size(source)
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
       description: "Delete named objects from the scene and report the cost: what went, which of their children were left unparented, what the orphan purge freed, and what is left. The counterpart of text, place and import_asset. Blender's own undo may not cover it, so treat a removal as final.",
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
       description: "Add, remove or list one modifier on a mesh: subdivision, bevel, mirror, solidify, decimate or wireframe, with the setting that matters for that kind typed. The report gives the base and evaluated face counts, so an effect that did nothing is visible rather than assumed. The long tail of modifier properties is not typed; use command or execute_code when a specific one is needed.",
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
    field :source, :string, description: "Path to an image file on the machine this server runs on"
    field :width, :i32, description: "Cells across", default: 64, min: 20, max: 200
    field :mode, :string, description: "half: two samples stacked, two colours. braille: eight samples (a 4x2 dot grid) as one dithered glyph, four times the vertical detail. blend: the same eight samples with two colours, the lit dots in front and the gaps behind", enum: ["half", "braille", "blend"], default: "blend"
    field :dither, :string, description: "diffusion: Floyd-Steinberg, where each dot's rounding error spills into its neighbours, giving irregular dots that read as tone. ordered: a 4x4 Bayer threshold, regular by construction and so more textured. threshold: a hard 50% cut", enum: ["diffusion", "ordered", "threshold"], default: "diffusion"
  end

  tool :image_view, params: :ImageViewParams, title: "Show an image in the terminal",
       description: "The image itself, as truecolour text for a human to look at, in three modes: half draws two stacked samples per cell with two colours; braille draws a dithered 4x2 dot grid as one glyph, four times the vertical detail, which makes a flat tone read as tone; blend does braille with the lit dots in one colour and the gaps in another, so shape and colour both survive. This is for eyes, not for a model: a text model should read image_report or image_report_rust, which cost a fraction of the tokens. It needs a client that passes ANSI through, a terminal that renders truecolour, and a font carrying braille and block glyphs.",
       output: :TextReport, read_only: true, open_world: true do
    body do |source, width, mode, dither|
      result(:TextReport, report: rust(:ansi, source, width, mode, dither))
    end
  end

  output :FileReport do
    field :path, :string, description: "Absolute path of the file that was written"
    field :report, :string, description: "Plain text: what was written and with what settings"
  end

  params :RenderParams do
    field :file, :string, description: "Where to write the PNG; unset writes <name>-render.png beside the .blend, or on the Desktop for an unsaved file", optional: true
    field :camera, :string, description: "Camera to render from; unset uses the scene camera", optional: true
    field :width, :i32, description: "Pixels across; unset keeps the file's setting", optional: true, min: 16, max: 8192
    field :height, :i32, description: "Pixels down; unset keeps the file's setting", optional: true, min: 16, max: 8192
    field :samples, :i32, description: "Samples for the current engine; unset keeps the file's setting", optional: true, min: 1, max: 8192
    field :frame, :i32, description: "Frame to render; unset renders the current one", optional: true
  end

  tool :render, params: :RenderParams, title: "Render to a file",
       description: "Render the scene to a PNG at the resolution and sample count asked for and leave it on disk, so the result is a file the user keeps and can open. The report names the path, the size and the settings; read the picture back as text with image_report, or use look with mode camera when the picture should come back as an image in the reply.",
       output: :FileReport, destructive: true, open_world: true do
    body do |file, camera, width, height, samples, frame|
      wanted_file = file || ""
      wanted_camera = camera || ""
      qwidth = if width.nil? then "null" else width.to_s end
      qheight = if height.nil? then "null" else height.to_s end
      qsamples = if samples.nil? then "null" else samples.to_s end
      qframe = if frame.nil? then "null" else frame.to_s end
      args = "{\"file\":#{Json.quote(wanted_file)},\"camera\":#{Json.quote(wanted_camera)},\"width\":#{qwidth},\"height\":#{qheight},\"samples\":#{qsamples},\"frame\":#{qframe}}"
      data = Json.parse(run_module(setting(:blender_host), Integer(setting(:blender_port), 10), setting(:blender_python), "render", args)) || raise("could not parse the render report")
      result(:FileReport, path: Json.text(data, "/path") || "", report: Json.text(data, "/report") || raise("the render script returned no text"))
    end
  end

  params :ExportParams do
    field :file, :string, description: "Where to write the model; unset writes <name>.glb (or .fbx) beside the .blend", optional: true
    field :format, :string, description: "glb carries materials and animation; fbx is the fallback for importers that need it", enum: ["glb", "fbx"], default: "glb"
    field :objects, :string_list, description: "Objects to export, children included; unset exports everything visible", optional: true
    field :selection_only, :bool, description: "Export the viewport selection instead", default: false
    field :apply_modifiers, :bool, description: "Apply modifiers on the way out", default: true
  end

  tool :export, params: :ExportParams, title: "Export the scene",
       description: "Write the scene, or named objects with their children, to glTF (.glb) or FBX, so the work leaves Blender as one file. The report names the path, the size, and anything skipped because it is not in the current view layer. It replaces the viewport selection as a side effect, which the report says, so call reveal afterwards if the selection mattered.",
       output: :FileReport, destructive: true, open_world: true do
    body do |file, format, objects, selection_only, apply_modifiers|
      wanted_file = file || ""
      listed = Json.str_list_json(objects || [])
      args = "{\"file\":#{Json.quote(wanted_file)},\"format\":#{Json.quote(format)},\"objects\":#{listed},\"selection_only\":#{selection_only},\"apply_modifiers\":#{apply_modifiers}}"
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

  params :Generate3dParams do
    field :prompt, :string, description: "What to make, in plain words; one object, for example \"a weathered wooden treasure chest\". Give prompt or image, not both", optional: true
    field :image, :string, description: "An absolute image file path or an http(s) URL to model from, instead of a prompt; images attached in chat cannot be passed", optional: true
    field :name, :string, description: "Name for the imported object; unset derives one from the prompt", optional: true
    field :provider, :string, description: "Which generator to use; auto prefers Tripo, then Hunyuan3D, then Hyper3D Rodin, whichever is enabled", enum: ["auto", "hyper3d", "hunyuan3d", "tripo"], default: "auto"
    field :quality, :string, description: "Tripo and Hunyuan3D only, Premium: standard or high; omit for the user's default", enum: ["standard", "high"], optional: true
    field :bbox_condition, :i64_list, description: "Hyper3D Rodin only: [length, width, height] proportions, three positive integers", optional: true
    field :job, :string, description: "A handle from an earlier call, to resume waiting for that generation instead of starting a new one", optional: true
    field :wait_seconds, :i32, description: "How long to wait before returning a job handle; a single call is capped at 45 seconds and generation usually takes 1-3 minutes", default: 45, min: 5, max: 300
  end

  tool :generate_3d, params: :Generate3dParams, title: "Generate a 3D model",
       description: "Make one new textured 3D model from a text prompt or an image, and import it into the scene. One object per call, never a whole scene, the ground or parts to assemble. It arrives at arbitrary scale and facing; the reply reports its world_bounding_box and how to place it. Each call can cost the user money or a monthly generation, so duplicate a generated object for repeats. Waits up to wait_seconds (a single call is capped at 45 s), then imports; if it is not done in time the reply names the provider and gives a job handle to resume with, so a client timeout never strands a paid generation.",
       destructive: true, open_world: true do
    body do |prompt, image, name, provider, quality, bbox_condition, job, wait_seconds|
      host = setting(:blender_host)
      port = Integer(setting(:blender_port), 10)
      scripts = setting(:blender_scripts)
      got = prompt || ""
      img = image || ""
      wanted = name || ""
      q = quality || ""
      bbox_list = bbox_condition || []
      bbox_json = gen_bbox(bbox_list)
      resume = job || ""
      seconds = Integer(wait_seconds.to_s, 10)
      gen_run(host, port, scripts, got, img, wanted, provider, q, bbox_json, resume, seconds)
    end
  end

  params :Make3dParams do
    field :prompt, :string, description: "What to make, in plain words; one object, for example \"a weathered wooden treasure chest\""
    field :name, :string, description: "Name for the imported object; unset derives one from the prompt", optional: true
    field :job, :string, description: "A handle from an earlier call, to resume waiting for that generation instead of starting a new one", optional: true
  end

  tool :make_3d, params: :Make3dParams, title: "Quick generate a 3D model",
       description: "Make one new textured 3D model from a single text prompt and import it into the scene: the quick path, which chooses the provider automatically and waits the same 45 seconds. Reach for generate_3d instead when you need to choose a provider, supply an image, or set quality or bbox_condition, or to wait longer than 45 seconds. Like generate_3d it makes one object, never a whole scene, ground or parts to assemble, and each call can cost the user money or a monthly generation. The reply reports the imported object's world_bounding_box and how to place it, or a job handle to resume with.",
       destructive: true, open_world: true do
    body do |prompt, name, job|
      host = setting(:blender_host)
      port = Integer(setting(:blender_port), 10)
      scripts = setting(:blender_scripts)
      wanted = name || ""
      resume = job || ""
      gen_run(host, port, scripts, prompt, "", wanted, "auto", "", "null", resume, 45)
    end
  end

  transport :http, port: 8787, auth_setting: :mcp_token
end

