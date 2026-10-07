# Driving the Blender MCP server over HTTP

## Why

An agent in a sandbox cannot run the server: `raj ctl exec` is refused over TCP
by design, and the sandbox has no workspace mount, so every build and every test
was a human round trip. With `transport :http` the server keeps running where
Blender is and the agent calls it directly — the same arrangement the raj editor
bridge already uses.

## Server side

```ruby
setting :mcp_token, env: "MCP_TOKEN", secret: true,
        description: "bearer token every request to the HTTP transport must carry"
transport :http, port: 8787, auth_setting: :mcp_token
```

- It binds **127.0.0.1 only**. A container reaches it through
  `host.docker.internal` (Docker Desktop forwards the host's loopback; confirmed
  with a plain TCP connect before building anything).
- `auth_setting:` must name a `secret:` setting, and **a secret setting cannot be
  `optional:`** — it is either there or the server refuses to start. So every run,
  stdio included, needs `MCP_TOKEN` set.
- The DSL allows **exactly one `transport`** (`duplicate transport`), so adding
  HTTP replaces stdio rather than joining it. The binary then *listens* and never
  reads stdin: `... | ./build/.../blender` simply hangs.

## The two client quirks

**1. Host header.** rmcp enforces a DNS-rebinding check and answers
`Forbidden: Host header is not allowed` unless `Host` is one it trusts
(`127.0.0.1:<port>`, `localhost`). A client reaching the server from another host
must connect to `host.docker.internal` but *present* `Host: 127.0.0.1:8787`.
`fetch` cannot set `Host` (it is a forbidden header name), so use `node:http`, or
`curl -H 'Host: …'`.

**2. SSE framing.** Replies are `text/event-stream` whose first `data:` line is
**empty**:

```
data: 
id: 0
retry: 3000

data: {"jsonrpc":"2.0","id":1,"result":{…}}
```

Taking the first `data:` line parses nothing. Join every `data:` line, then parse.

Also: `initialize` returns the session id in the `mcp-session-id` **response
header**, and later requests must send it back as `Mcp-Session-Id`.
Notifications answer `202` with an empty body. A client that initialises per
invocation is fine — sessions are cheap, and it survives a server restart.

## What needs a save, and what does not

- **Save then rebuild**: `blender.rmcp.rb`, `bindings/*.rb` — the compiler reads
  them from disk. `mcp_extras.py` the *server* reads from disk on every call.
- **No save needed**: `execute_code` payloads. The agent reads the file out of the
  editor's **buffer** (`raj ctl read --json F | jq -r .text`) and ships the text
  in the request, so an unsaved edit can be run immediately.
- **Cache-busting**: Blender caches an installed script by module name, so editing
  a script had *no effect* until Blender restarted. `run_script` now names the
  module `_mcp_scripts_<NAME>_<hash of the script text>`, so a changed script
  installs fresh on the next call — no rebuild and no restart.

## The dev loop

`dev.sh` hashes the four sources once a second; on a change it runs
`rmcp_dsl check` (Ruby only, instant) then `rmcp_dsl build` then restarts the
server. A failed check or build **leaves the last good build serving**, so a typo
never turns into a dead port for a caller mid-loop, and `RAJ_NOTIFY=<key>` sends
the failure to an agent's mailbox through `raj ctl send`.

`rmcp_dsl` itself has no watch mode; `check` is the fast gate and `build` the slow
one — worth keeping separate, since `check` catches most mistakes without cargo.

## Clients

- `mcp.sh` (curl + jq): `tool NAME 'JSON'`, `code FILE.py`, `raw FILE`. Add
  `MCP_HOST_HEADER` when calling across a sandbox boundary.
- A node variant over `node:http` for sandboxes without curl.

Both render text blocks as text and summarise images
(`[image image/png 82 KB omitted]`) — the base64 is never useful to a text agent,
and a 78x34 wireframe is ~1 KB against ~80 KB for a screenshot.

## Security

That token is a **full-power credential** for the machine it points at:
`execute_code` runs arbitrary Python with the user's privileges and can read or
write any file the user can. Keep the port loopback-only (or reachable solely
through the host gateway), rotate the token per session, and never bind it to a
shared network. The blast radius is wider than the raj bridge's for exactly that
reason: Blender's Python is not sandboxed at all.
