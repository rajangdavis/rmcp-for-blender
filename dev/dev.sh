#!/usr/bin/env bash
# Dev loop: rebuild and restart the Blender MCP server whenever its sources change.
#
#   MCP_TOKEN=<token> bash dev/dev.sh
#
# Watches the DSL file, every binding, and the injected Rust - all of it,
# because the compiler copies those in at build time and an edit that triggers
# no build is invisible.
# On a change it runs `rmcp_dsl check` first (fast, Ruby only, no cargo) and only
# builds and restarts when the DSL itself accepts the file — so a typo never takes
# the running server down; it keeps serving the last good build. Ctrl-C stops it.
#
# No dependencies beyond shasum (it hashes file contents, so it does not care
# about mtimes). Linux: swap shasum for sha256sum.
set -uo pipefail
cd "$(dirname "$0")/.."
TOKEN="${MCP_TOKEN:?set MCP_TOKEN to the token your client sends}"
# Persist the token so a client in another shell (or a fresh login shell) can read
# it without re-exporting: dev/mcp.sh falls back to this file. Mode 600, gitignored.
printf %s "$TOKEN" > .mcp-token && chmod 600 .mcp-token
BIN=./build/blender.rmcp/target/debug/blender
PIDFILE=/tmp/mcp-server.pid
BUILDLOG=/tmp/mcp-build.log
SERVERLOG=/tmp/mcp-server.log
WATCH=(blender.rmcp.rb bindings/*.rb rust/*.rs)

stamp() { cat "${WATCH[@]}" 2>/dev/null | shasum -a 256 | cut -c1-16; }
stop() {
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    kill "$(cat "$PIDFILE")" 2>/dev/null
  fi
  rm -f "$PIDFILE"
}
start() {
  MCP_TOKEN="$TOKEN" "$BIN" >>"$SERVERLOG" 2>&1 &
  echo $! > "$PIDFILE"
}
# One instance only. Six once ran at once: they fought over cargo's build lock and
# each other's restarts, which shows up as "Blocking waiting for file lock on
# build directory" and then a dead port. A pidfile is not enough — a killed
# instance leaves a stale pid and the next start sails past it — so ask the
# process table.
OTHERS=$(pgrep -f 'dev\.sh' | grep -v "^$$\$" || true)
if [ -n "$OTHERS" ]; then
  echo "another dev.sh is already running (pid(s): $(echo $OTHERS | tr '\n' ' ')); stop it first" >&2
  exit 2
fi
trap 'stop; echo "server stopped"' EXIT INT TERM

# Optional: tell an agent when the loop breaks, so a dead call is explained.
#   RAJ_NOTIFY=raj-0b6990fc bash dev.sh
notify() {
  if [ -n "${RAJ_NOTIFY:-}" ] && command -v raj >/dev/null 2>&1; then
    printf "%s\n" "$1" | raj ctl send --as dev-watch --to "$RAJ_NOTIFY" --text-file - >/dev/null 2>&1 || true
  fi
}

# The Python module the tools run is read at call time, so editing it needs no
# rebuild - but it should not wait for a Blender call to prove it parses. uv is
# what this repo already uses for Python (the vendored addon carries a
# .python-version and a uv venv), so try it first and fall back to whatever
# python3 the machine has. Whichever wins is proved here, at startup, rather
# than discovered at lint time; the check is ast.parse, so no bpy import and no
# bytecode written into the tree.
pick_python() {
  for candidate in "uv run --quiet --no-project python" "python3" "python"; do
    if $candidate -c 'import ast' >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}
PYRUN="$(pick_python || true)"
pystamp() { cat python/mcp_scripts.py 2>/dev/null | shasum -a 256 | cut -c1-16; }
lint() {
  if [ -z "$PYRUN" ]; then
    echo "$(date +%T) lint    no uv and no python3 here, so the Python was not checked"
    return 0
  fi
  if $PYRUN -c 'import ast, sys
for path in sys.argv[1:]:
    try:
        ast.parse(open(path).read(), path)
    except SyntaxError as e:
        print("%s:%s: %s" % (path, e.lineno, e.msg))
        sys.exit(1)' python/mcp_scripts.py >"$BUILDLOG" 2>&1; then
    echo "$(date +%T) lint    the Python parses (via $PYRUN)"
  else
    echo "$(date +%T) LINT    the Python does not parse:"
    cat "$BUILDLOG"
    notify "Python lint failed: $(head -n 1 "$BUILDLOG")"
  fi
}

# A restart is not proof the new build works: a binary that panics on startup
# looks exactly like one that is serving. Ask the port, using bash's own /dev/tcp
# so this needs no curl and no nc.
server_port() { grep -m1 'transport :http, port:' blender.rmcp.rb | grep -oE '[0-9]+' | head -1; }
listening() {
  local port; port=$(server_port)
  [ -n "$port" ] || return 0
  (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null
}
wait_alive() {
  local tries=0
  while [ $tries -lt 10 ]; do
    if listening; then return 0; fi
    tries=$((tries + 1)); sleep 0.5
  done
  notify "MCP server did not come up after the rebuild: $(tail -n 3 "$SERVERLOG" | tr "\n" " ")"
  echo "$(date +%T) START   the new build is not listening - the log says:"
  tail -n 12 "$SERVERLOG"
  return 1
}

lastpy=""
last=""
while true; do
  nowpy=$(pystamp)
  if [ "$nowpy" != "$lastpy" ]; then
    lastpy="$nowpy"
    lint
  fi
  now=$(stamp)
  if [ "$now" != "$last" ]; then
    last="$now"
    if rmcp_dsl check blender.rmcp.rb >"$BUILDLOG" 2>&1; then
      if rmcp_dsl build blender.rmcp.rb >>"$BUILDLOG" 2>&1; then
        stop; start
        if wait_alive; then
          echo "$(date +%T) ok      rebuilt and restarted (pid $(cat "$PIDFILE"))"
        fi
      else
        notify "MCP build failed: $(tail -n 5 "$BUILDLOG" | tr "\n" " ")"
        echo "$(date +%T) BUILD   failed — still serving the last good build:"
        tail -n 15 "$BUILDLOG"
      fi
    else
      notify "MCP DSL check failed: $(tail -n 3 "$BUILDLOG" | tr "\n" " ")"
      echo "$(date +%T) CHECK   failed — still serving the last good build:"
      tail -n 10 "$BUILDLOG"
    fi
  fi
  sleep 1
done


