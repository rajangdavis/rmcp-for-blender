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
# Whatever still listens on the server's port when a build starts is a stale
# server (an earlier run that outlived its dev.sh, or one started by hand): it
# would keep answering while the new build dies on "address in use". Kill it
# outright, and say which process it was.
free_port() {
  local owner pid
  owner=$(port_owner)
  [ -n "$owner" ] || return 0
  for pid in $owner; do
    echo "$(date +%T) kill    pid $pid ($(ps -o comm= -p "$pid" 2>/dev/null)) was holding port $(server_port): kill -9"
    kill -9 "$pid" 2>/dev/null
  done
  sleep 0.3
}
start() {
  free_port
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

# The Python the tools run (and the add-on Blender loads) is read at call time,
# so editing it needs no rebuild - but it should not wait for a Blender call to
# prove it parses. Try uv first and fall back to whatever python3 the machine
# has. Whichever wins is proved here, at startup, rather
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
PYFILES=(python/mcp_scripts.py python/mcp_guard.py python/safe_mode.py addon/mcp_bridge.py)
pystamp() { cat "${PYFILES[@]}" 2>/dev/null | shasum -a 256 | cut -c1-16; }
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
        sys.exit(1)' "${PYFILES[@]}" >"$BUILDLOG" 2>&1; then
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
# The port answering is not proof either: an older server still holding it makes
# a new one die on "address in use" while the port keeps answering. So the
# process this script started must be alive and be the one listening. lsof names
# the owner; without lsof only the first half is checked.
port_owner() {
  command -v lsof >/dev/null 2>&1 || return 0
  lsof -nP -iTCP:"$(server_port)" -sTCP:LISTEN -t 2>/dev/null
}
wait_alive() {
  local tries=0 pid owner problem
  pid=$(cat "$PIDFILE" 2>/dev/null)
  problem="the new build is not listening"
  while [ $tries -lt 10 ]; do
    if ! kill -0 "$pid" 2>/dev/null; then
      problem="the new build (pid $pid) exited"
      break
    fi
    if listening; then
      owner=$(port_owner)
      if [ -z "$owner" ] || printf '%s\n' "$owner" | grep -qx "$pid"; then return 0; fi
      problem="port $(server_port) is held by pid $(echo $owner), not this build's pid $pid, and kill -9 did not free it"
      break
    fi
    tries=$((tries + 1)); sleep 0.5
  done
  notify "MCP server did not come up after the rebuild: $problem"
  echo "$(date +%T) START   $problem - the log says:"
  tail -n 12 "$SERVERLOG"
  return 1
}

# Which server is running, for the log line: the version declared in the DSL
# (what MCP clients see in the handshake) and a hash of the sources it was built from.
server_version() { grep -m1 '^server "blender", version:' blender.rmcp.rb | grep -oE 'version: "[^"]+"' | cut -d'"' -f2; }
identity() { echo "pid $(cat "$PIDFILE"), blender $(server_version), sources $(stamp)"; }

# "Still serving the last good build" has to be made true on the first pass:
# nothing is running yet, so a check or build that fails at startup would
# otherwise leave no server at all. Start the binary already on disk instead.
serving() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }
keep_serving() {
  if ! serving && [ -x "$BIN" ]; then
    start
    if wait_alive; then
      echo "$(date +%T) stale   started the last good build on disk (pid $(cat "$PIDFILE")); fix the error above to replace it"
    fi
  fi
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
          echo "$(date +%T) ok      rebuilt and restarted ($(identity))"
        fi
      else
        notify "MCP build failed: $(tail -n 5 "$BUILDLOG" | tr "\n" " ")"
        echo "$(date +%T) BUILD   failed — still serving the last good build:"
        tail -n 15 "$BUILDLOG"
        keep_serving
      fi
    else
      notify "MCP DSL check failed: $(tail -n 3 "$BUILDLOG" | tr "\n" " ")"
      echo "$(date +%T) CHECK   failed — still serving the last good build:"
      tail -n 10 "$BUILDLOG"
      keep_serving
    fi
  fi
  sleep 1
done


