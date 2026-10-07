#!/usr/bin/env bash
# Exercise every tool and check the shape of the reply.
#
#   MCP_TOKEN=… bash smoke.sh          hermetic: inventory, read-only tools, error paths
#   MCP_TOKEN=… bash smoke.sh --full   also makes a probe, changes it, cleans up
#
# `generate_3d`, `make_3d` and `import_asset` are never called: they spend money or
# download, and a smoke test has to be safe to run on a whim.
set -uo pipefail
cd "$(dirname "$0")"
FULL=0; [ "${1:-}" = "--full" ] && FULL=1
pass=0; fail=0

expect() {  # tool, args, a substring the reply must contain
  local out; out=$(bash mcp.sh tool "$1" "$2" 2>&1 | head -3 | tr '\n' ' ')
  case "$out" in
    *"$3"*) printf '  %-14s ok    %s\n' "$1" "$(printf '%s' "$out" | cut -c1-62)"; pass=$((pass+1)) ;;
    *)      printf '  %-14s FAIL  wanted %s in: %s\n' "$1" "$3" "$(printf '%s' "$out" | cut -c1-62)"; fail=$((fail+1)) ;;
  esac
}
refuses() {  # a tool that should refuse, because refusals must surface
  local out; out=$(bash mcp.sh tool "$1" "$2" 2>&1 | head -2 | tr '\n' ' ')
  case "$out" in
    *ERROR*|*error*) printf '  %-14s ok    refused, as it should\n' "$1"; pass=$((pass+1)) ;;
    *)  printf '  %-14s FAIL  expected a refusal, got: %s\n' "$1" "$(printf '%s' "$out" | cut -c1-62)"; fail=$((fail+1)) ;;
  esac
}

echo "== inventory =="
listed=$(bash mcp.sh tools 2>/dev/null | sort | tr '\n' ' ')
echo "  the server advertises $(printf '%s' "$listed" | wc -w) tools"
for want in scene scene_info reveal text place material remove duplicate array boolean aim light \
            modifier render export wireframe mesh_report image_report look screenshot command \
            execute_code object_info search_assets import_asset generate_3d make_3d image_report_rust image_view; do
  case " $listed " in *" $want "*) ;; *) printf '  %-14s FAIL  not advertised\n' "$want"; fail=$((fail+1));; esac
done
[ $fail -eq 0 ] && echo "  all 29 present"

echo "== preflight: is anything answering in Blender? =="
if bash mcp.sh tool command '{"name":"ping"}' 2>/dev/null | grep -q result; then
  echo "  the addon answers"
else
  echo "  the addon's server is not answering in Blender: start it in Blender and re-run." >&2
  echo "  (checked with command ping; nothing else was called)" >&2
  exit 2
fi

echo "== read-only paths, and the refusals they should give =="
expect reveal '{}' '"report"'
expect reveal '{"name":"definitely-not-here"}' 'no object named'
expect scene '{"limit":3}' 'items'
expect scene_info '{}' 'data'
expect command '{"name":"ping"}' 'result'
expect execute_code '{"code":"print(1)"}' '1'
expect image_report '{"source":"definitely-not-here.png"}' 'cannot load'
expect look '{"mode":"viewport","max_size":200}' '[image'
expect screenshot '{"max_size":200}' '[image'
refuses object_info '{"name":"definitely-not-here"}'
# wireframe and mesh_report are Python entry points, and every one of those
# reports a miss as text ("no mesh object named X") rather than failing the call;
# only the addon's native commands come back as errors. Check the message, not the
# shape, so the smoke does not pin a convention the module does not hold.
expect wireframe '{"name":"definitely-not-here"}' 'no mesh object named'
expect mesh_report '{"name":"definitely-not-here"}' 'no mesh object named'

if [ $FULL -eq 1 ]; then
  echo "== full: one probe, changed and cleaned up =="
  expect text '{"text":"SMOKE","name":"smoke_probe","size":0.25,"z":1.0}' 'converted to MESH'
  expect wireframe '{"name":"smoke_probe","views":["top"],"width":64,"height":20}' 'wireframe v2'
  expect mesh_report '{"name":"smoke_probe"}' 'face orientation'
  expect material '{"name":"smoke_probe","colour":"#3fa9f5"}' 'principled node'
  expect place '{"name":"smoke_probe","rz":15,"relative":true}' 'changed: rotation'
  expect duplicate '{"names":["smoke_probe"],"count":1,"dx":1.0}' 'full copies'
  expect array '{"name":"smoke_probe.001","count":3,"offset_z":0.4}' 'with the modifier applied'
  expect modifier '{"name":"smoke_probe.001","kind":"subdivision","count":1}' 'with the modifiers applied'
  expect modifier '{"name":"smoke_probe.001","action":"list"}' 'carries'
  expect modifier '{"name":"smoke_probe.001","action":"remove","kind":"subdivision"}' 'removed modifier'
  expect boolean '{"name":"smoke_probe","operand":"smoke_probe.001","operation":"intersect","apply":false}' 'faces'
  # aim moves the scene camera and light creates one, so both are recorded and put
  # back at the end: a smoke test should leave the file as it found it.
  saved_camera=$(bash mcp.sh tool execute_code "$(jq -nc --arg c 'import bpy; c = next((o for o in bpy.data.objects if o.type == "CAMERA"), None); print("CAMERA " + " ".join(repr(float(v)) for row in c.matrix_world for v in row))' '{code:$c}')" \
    | sed -n 's/.*"output":"CAMERA \([^"\\]*\)\\n".*/\1/p' | head -1)
  # The light is created unnamed (a `name` would select an existing light to adjust
  # and create nothing), and the cleanup below removes whatever light was not here
  # before, so nothing parses the tool's own name -- which contains a space.
  # The value is JSON, so read it with jq: a sed character class that cannot span a
  # quote silently captured nothing, and the guard below then skipped the removal.
  lights_before=$(bash mcp.sh tool execute_code "$(jq -nc '{code:"import bpy, json; print(\"LIGHTS \" + json.dumps(sorted(o.name for o in bpy.data.objects if o.type == \"LIGHT\")))"}')" \
    | head -1 | jq -r .output | sed -n 's/^LIGHTS //p')
  if [ -z "$lights_before" ]; then
    printf '  %-14s FAIL  could not read the light list before the run\n' lights
    fail=$((fail+1))
  fi
  expect aim '{"target":"smoke_probe"}' 'scene camera'
  expect light '{"target":"smoke_probe"}' '(created)'

  rendered=$(bash mcp.sh tool render '{"file":"mcp-smoke.png","width":320,"height":200,"samples":8}' 2>&1)
  case "$rendered" in *wrote*) printf '  %-14s ok    %s\n' render "$(printf '%s' "$rendered" | head -1 | cut -c1-62)"; pass=$((pass+1));; *) printf '  %-14s FAIL  %s\n' render "$(printf '%s' "$rendered" | head -1 | cut -c1-62)"; fail=$((fail+1));; esac
  png=$(printf '%s' "$rendered" | sed -n 's/.*wrote \([^ ]*\.png\).*/\1/p' | head -1)
  if [ -n "$png" ]; then expect image_report "{\"source\":\"$png\"}" 'aspect'; fi

  exported=$(bash mcp.sh tool export '{"file":"mcp-smoke.glb","objects":["smoke_probe"]}' 2>&1)
  case "$exported" in *GLB*) printf '  %-14s ok    %s\n' export "$(printf '%s' "$exported" | head -1 | cut -c1-62)"; pass=$((pass+1));; *) printf '  %-14s FAIL  %s\n' export "$(printf '%s' "$exported" | head -1 | cut -c1-62)"; fail=$((fail+1));; esac
  glb=$(printf '%s' "$exported" | sed -n 's/.*wrote \([^ ]*\.glb\).*/\1/p' | head -1)

  expect remove '{"names":["smoke_probe","smoke_probe.001"]}' 'purged data with no user left'
  # Remove whatever light the run created, by set difference against the names
  # captured before it: the old version parsed the created name out of the report
  # and silently skipped this step when the pattern did not match.
  if [ -n "$lights_before" ]; then
    expect execute_code "$(jq -nc --arg b "$lights_before" '{code:("import bpy, json; keep = json.loads(" + ($b|@json) + "); gone = []; [gone.append(o.name) or bpy.data.objects.remove(o, do_unlink=True) for o in list(bpy.data.objects) if o.type == \"LIGHT\" and o.name not in keep]; print(\"removed %d light(s)\" % len(gone))")}')" 'removed 1 light'
  fi

  # render and export write real files: delete both rather than leave litter
  # beside the .blend for the user to find later.
  for leftover in "$png" "$glb"; do
    if [ -n "$leftover" ]; then
      expect execute_code "$(jq -nc --arg p "$leftover" '{code:("import os; p = " + ($p|@json) + "; os.path.exists(p) and os.remove(p); print(\"removed\")")}')" removed
    fi
  done

  # aim left the camera pointing where the probe was; hand it back.
  if [ -n "$saved_camera" ]; then
    expect execute_code "$(jq -nc --arg v "$saved_camera" '{code:("import bpy, mathutils; v = [float(x) for x in " + ($v|@json) + ".split()]; c = next((o for o in bpy.data.objects if o.type == \"CAMERA\"), None); c.matrix_world = mathutils.Matrix((v[0:4], v[4:8], v[8:12], v[12:16])); print(\"camera restored\")")}')" 'camera restored'
  fi
  expect reveal '{}' '"report"'
fi

echo "== $pass passed, $fail failed =="
[ $fail -eq 0 ]
