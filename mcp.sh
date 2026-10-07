#!/usr/bin/env bash
# A one-line client for the Blender MCP server, over streamable HTTP.
#
#   bash mcp.sh tool NAME 'JSON'    call a tool with a JSON argument object
#   bash mcp.sh code FILE.py        run a file's Python inside Blender
#   bash mcp.sh raw FILE.jsonl      send prepared request lines after initialize
#
# The server must be running with a token:
#   MCP_TOKEN=$(openssl rand -hex 16) ./build/blender.rmcp/target/debug/blender &
# and this client sends the same one:
#   MCP_TOKEN=<that token> bash mcp.sh tool mesh_report '{"name":"Chair"}'
# From another sandbox, aim it at the host:
#   MCP_URL=http://host.docker.internal:8787/mcp MCP_TOKEN=... bash mcp.sh ...
set -euo pipefail
URL="${MCP_URL:-http://127.0.0.1:8787/mcp}"
TOKEN="${MCP_TOKEN:?set MCP_TOKEN to the token the server was started with}"
HDR=(-fsS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json'
         -H 'Accept: application/json, text/event-stream')
# rmcp checks the Host header (DNS-rebinding); a client reaching this server from
# another sandbox must present a host it trusts.
[ -n "${MCP_HOST_HEADER:-}" ] && HDR+=(-H "Host: $MCP_HOST_HEADER")
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"mcp.sh","version":"1"}}}'
DONE='{"jsonrpc":"2.0","method":"notifications/initialized"}'

SIDFILE=$(mktemp); trap 'rm -f "$SIDFILE"' EXIT
curl "${HDR[@]}" -D "$SIDFILE" -o /dev/null -d "$INIT" "$URL"
SID=$(tr -d '\r' < "$SIDFILE" | sed -n 's/^[Mm]cp-[Ss]ession-[Ii]d: //p' || true)
[ -n "$SID" ] && HDR+=(-H "Mcp-Session-Id: $SID")
curl "${HDR[@]}" -o /dev/null -d "$DONE" "$URL"

post() { local r; r=$(curl "${HDR[@]}" -d "$1" "$URL")
         # The reply is an SSE stream whose first data: line is empty, so join
         # every data: line rather than taking the first.
         case "$r" in
           *data:*) printf '%s\n' "$(printf '%s\n' "$r" | sed -n 's/^data: //p' | tr -d '\n')" ;;
           *)       printf '%s\n' "$r" ;;
         esac; }
call() { jq -nc --argjson id "$1" --arg n "$2" --argjson a "$3" \
           '{jsonrpc:"2.0",id:$id,method:"tools/call",params:{name:$n,arguments:$a}}'; }
blocks() {
  jq -r 'select(.id==2) | .result as $r
         | if $r.isError then "ERROR: " + (($r.content[0].text) // "")
           else ($r.content[]?
                 | if .type=="text" then .text
                   elif .type=="image" then "[image \(.mimeType) \((.data|length/1024|floor)) KB omitted]"
                   else "[\(.type)]" end)
           end'
}
stdout() {
  jq -r 'select(.id==2) | .result as $r
         | if $r.isError then "ERROR: " + (($r.content[0].text) // "")
           else (($r.structuredContent.output) // ($r.content[0].text) // "") end'
}
case "${1:-}" in
  tool) [ $# -eq 3 ] || { echo "usage: bash mcp.sh tool NAME 'JSON'" >&2; exit 2; }
        post "$(call 2 "$2" "$3")" | blocks ;;
  code) [ $# -eq 2 ] || { echo "usage: bash mcp.sh code FILE.py" >&2; exit 2; }
        post "$(call 2 execute_code "$(jq -nc --rawfile c "$2" '{code:$c}')")" | stdout ;;
  raw)  [ $# -eq 2 ] || { echo "usage: bash mcp.sh raw FILE" >&2; exit 2; }
        post "$(cat "$2")" | stdout ;;
  *)    sed -n '3,7p' "$0" >&2; exit 2 ;;
esac
