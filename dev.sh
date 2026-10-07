#!/usr/bin/env bash
# Dev loop: rebuild and restart the Blender MCP server whenever its sources change.
#
#   MCP_TOKEN=<token> bash dev.sh
#
# Watches blender.rmcp.rb, bindings/json.rb, blender_bridge.rs and mcp_extras.py.
# On a change it runs `rmcp_dsl check` first (fast, Ruby only, no cargo) and only
# builds and restarts when the DSL itself accepts the file — so a typo never takes
# the running server down; it keeps serving the last good build. Ctrl-C stops it.
#
# No dependencies beyond shasum (it hashes file contents, so it does not care
# about mtimes). Linux: swap shasum for sha256sum.
set -uo pipefail
cd "$(dirname "$0")"
TOKEN="${MCP_TOKEN:?set MCP_TOKEN to the token your client sends}"
BIN=./build/blender.rmcp/target/debug/blender
PIDFILE=/tmp/mcp-server.pid
BUILDLOG=/tmp/mcp-build.log
SERVERLOG=/tmp/mcp-server.log
WATCH=(blender.rmcp.rb bindings/json.rb blender_bridge.rs mcp_extras.py)

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
OTHERS=$(pgrep -f 'bash dev\.sh' | grep -v "^$$\$" || true)
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

last=""
while true; do
  now=$(stamp)
  if [ "$now" != "$last" ]; then
    last="$now"
    if rmcp_dsl check blender.rmcp.rb >"$BUILDLOG" 2>&1; then
      if rmcp_dsl build blender.rmcp.rb >>"$BUILDLOG" 2>&1; then
        stop; start
        echo "$(date +%T) ok      rebuilt and restarted (pid $(cat "$PIDFILE"))"
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


