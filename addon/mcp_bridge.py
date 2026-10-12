"""MCP Bridge: the Blender side of blender.rmcp.rb.

A socket on this machine's loopback that runs the server's own Python on
Blender's main thread, and nothing else. It replaces the vendored
mcp-for-blender add-on: every tool's behaviour lives in python/mcp_scripts.py
(and execute_code's guard in python/mcp_guard.py), which the server installs
through the one code-running command here.

The protocol is the one rust/blender_bridge.rs speaks: JSON objects back to back
on a kept TCP connection, no framing, one reply object per request.

    {"type": "ping" | "execute_code", "params": {...}, "token": "..."}
    {"status": "success", "result": ...}  or  {"status": "error", "message": "..."}

`ping` is answered on the reader thread the instant it arrives and is never
queued, so it reaches the client even while a long command holds Blender's main
thread; the client's timeout-then-ping check can then tell "Blender is busy"
from "the bridge is gone". Every other request is queued first-in-first-out and
run on the main thread by drain(), one reply per request, in order. While a
render is running, drain() leaves the queue alone instead of starting a command
beside it.

Every request must carry the bridge token. Docker and Lima forward a container's
host gateway to this machine's loopback, so "bound to 127.0.0.1" does not mean
"only local processes": a request without the token gets one "unauthorized"
reply and the connection is closed. The token is BLENDER_BRIDGE_TOKEN in
Blender's environment, or else the 0600 file mcp_bridge_token in Blender's
config folder, created on first start (its path is printed, never the token).

Install: Edit > Preferences > Add-ons > Install from Disk, pick this file, and
enable "MCP Bridge" (disable the old "Blender MCP" add-on first: both want port
9876). Start and stop it from the 3D viewport sidebar (N) > MCP. It never starts
on its own; stopped is the safe state while no agent is working.
"""

import hmac
import io
import json
import os
import queue
import secrets
import socket
import threading
import traceback
from contextlib import redirect_stdout
from typing import TYPE_CHECKING, Any, Literal, TypedDict

import bpy
from bpy.app.handlers import persistent

if TYPE_CHECKING:
    from bpy.types import Context

# No `from __future__ import annotations` here: Blender reads the bpy.props
# annotations on registered classes at runtime, and string annotations break it.

bl_info = {
    "name": "MCP Bridge",
    "author": "mcp_true_test",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > MCP",
    "description": "Token-guarded socket that lets the blender.rmcp.rb MCP server run its scripts here",
    "category": "Interface",
}

HOST = "127.0.0.1"
DEFAULT_PORT = 9876
TOKEN_FILE = "mcp_bridge_token"
# Bytes a connection may send before its first request proves the token, and
# after: a stranger cannot make Blender buffer much, while the server's own
# requests (a whole script module on first install) fit with room to spare.
MAX_UNAUTHENTICATED = 1024 * 1024
MAX_REQUEST = 64 * 1024 * 1024
# How often the main-thread timer looks at the queue. ~10 ms keeps Blender's UI
# responsive between commands; drain() returns this while requests still wait.
POLL_SECONDS = 0.01


class Success(TypedDict):
    status: Literal["success"]
    result: Any


class Failure(TypedDict):
    status: Literal["error"]
    message: str


Reply = Success | Failure


class CodeOutput(TypedDict):
    """execute_code's result: what the code printed. run_module in
    blender.rmcp.rb reads it at /result/result."""
    executed: bool
    result: str


def failure(message: str) -> Failure:
    return {"status": "error", "message": message}


def ping_reply() -> Success:
    """The one ping answer, built here so the reader thread's immediate reply
    and handle()'s cannot drift apart."""
    return {"status": "success", "result": {"pong": True}}


def token_path() -> str:
    return os.path.join(bpy.utils.user_resource("CONFIG"), TOKEN_FILE)


def load_token() -> str:
    """BLENDER_BRIDGE_TOKEN wins; otherwise the token file, created with a fresh
    random token the first time. An existing empty file is replaced."""
    env = os.environ.get("BLENDER_BRIDGE_TOKEN", "").strip()
    if env:
        return env
    path = token_path()
    try:
        with open(path, encoding="utf-8") as f:
            token = f.read().strip()
        if token:
            return token
        os.remove(path)
    except FileNotFoundError:
        pass
    token = secrets.token_hex(32)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    print('MCP Bridge: created a bridge token at %s\nMCP Bridge: start the server with BLENDER_BRIDGE_TOKEN="$(cat \'%s\')"' % (path, path))
    return token


def run_code(code: str) -> Reply:
    """Run Python on the main thread and return what it printed. The server
    sends only its own module installer and entry-point calls here; agent code
    reaches Blender through python/mcp_guard.py inside those."""
    out = io.StringIO()
    namespace: dict[str, Any] = {"bpy": bpy, "__name__": "__mcp_bridge__"}
    try:
        with redirect_stdout(out):
            exec(compile(code, "<mcp-bridge>", "exec"), namespace)
    except BaseException as exc:  # SystemExit included: it must not reach Blender
        return failure("%s: %s\n%s" % (type(exc).__name__, exc, traceback.format_exc()))
    output: CodeOutput = {"executed": True, "result": out.getvalue()}
    return {"status": "success", "result": output}


def handle(command: dict[str, Any]) -> Reply:
    kind = command.get("type")
    params = command.get("params") or {}
    if kind == "ping":
        return ping_reply()
    if kind == "execute_code":
        code = params.get("code") if isinstance(params, dict) else None
        if not isinstance(code, str):
            return failure("execute_code needs params.code as a string")
        return run_code(code)
    return failure("unknown command %r: this bridge runs ping and execute_code; the tools live in python/mcp_scripts.py" % (kind,))


# Render-state guarding and the ~10 ms main-thread timer are ported from the
# vendored blenderwright add-on (addon/render_guard.py, addon/thread_safety.py),
# MIT, copyright (c) 2026 jabberwock; see vendor/blenderwright/README.md.
def _render_started(scene: Any) -> None:
    """bpy.app.handlers.render_pre on the main thread: a render is running, so
    drain() must not start a command beside it."""
    BRIDGE.rendering.set()


def _render_finished(scene: Any) -> None:
    """bpy.app.handlers.render_complete / render_cancel: the render is over."""
    BRIDGE.rendering.clear()


@persistent
def _render_reset_on_load(_filepath: str) -> None:
    """bpy.app.handlers.load_post: a crashed or abandoned render can leave the
    flag set with no completion event still coming, so loading a .blend clears
    it (Stop then Start on the panel does too)."""
    BRIDGE.rendering.clear()


class Bridge:
    """The listener, its client threads, and the queue they hand requests to.
    bpy is only touched by drain(), on Blender's main thread."""

    def __init__(self) -> None:
        self.port = DEFAULT_PORT
        self.token = ""
        self.error = ""
        self.running = False
        self.listener: socket.socket | None = None
        self.thread: threading.Thread | None = None
        self.jobs: "queue.Queue[tuple[dict[str, Any], socket.socket]]" = queue.Queue()
        self.clients: set[socket.socket] = set()
        self.lock = threading.Lock()
        # Set while Blender is rendering (by bpy.app.handlers, on the main
        # thread); drain() reads it before starting a command.
        self.rendering = threading.Event()

    def start(self, port: int) -> str:
        """Start listening; the empty string on success, else why not."""
        if self.running:
            return ""
        if bpy.app.background:
            return "the bridge needs Blender's UI: in background mode (blender -b) no command would ever run"
        try:
            self.token = load_token()
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((HOST, port))
            listener.listen(5)
            listener.settimeout(1.0)
        except OSError as exc:
            self.error = "could not start: %s" % exc
            return self.error
        self.listener, self.port, self.error, self.running = listener, port, "", True
        self.thread = threading.Thread(target=self._accept, name="mcp-bridge", daemon=True)
        self.thread.start()
        self._watch_renders(True)
        if not bpy.app.timers.is_registered(_drain):
            bpy.app.timers.register(_drain, persistent=True)
        print("MCP Bridge: listening on %s:%d (token from %s)"
              % (HOST, port, "BLENDER_BRIDGE_TOKEN" if os.environ.get("BLENDER_BRIDGE_TOKEN", "").strip() else token_path()))
        return ""

    def stop(self) -> None:
        self.running = False
        if bpy.app.timers.is_registered(_drain):
            bpy.app.timers.unregister(_drain)
        if self.listener is not None:
            try:
                self.listener.close()
            except OSError:
                pass
            self.listener = None
        with self.lock:
            clients = list(self.clients)
            self.clients.clear()
        for client in clients:
            for close in (lambda: client.shutdown(socket.SHUT_RDWR), client.close):
                try:
                    close()
                except OSError:
                    pass
        while True:
            try:
                self.jobs.get_nowait()
            except queue.Empty:
                break
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self.thread = None
        self._watch_renders(False)
        print("MCP Bridge: stopped")

    def _watch_renders(self, on: bool) -> None:
        """Register or remove the render-state handlers. While a render runs,
        drain() leaves the queue alone rather than starting a command beside it;
        stopping the bridge clears the flag, so Stop then Start is the escape
        from a flag a crashed render left set."""
        for handler, handlers in (
            (_render_started, bpy.app.handlers.render_pre),
            (_render_finished, bpy.app.handlers.render_complete),
            (_render_finished, bpy.app.handlers.render_cancel),
            (_render_reset_on_load, bpy.app.handlers.load_post),
        ):
            if on:
                if handler not in handlers:
                    handlers.append(handler)
            elif handler in handlers:
                handlers.remove(handler)
        if not on:
            self.rendering.clear()

    def _accept(self) -> None:
        while self.running and self.listener is not None:
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve, args=(client,), name="mcp-bridge-client", daemon=True).start()

    def _authorised(self, command: object) -> bool:
        if not isinstance(command, dict):
            return False
        supplied = command.pop("token", None)
        return isinstance(supplied, str) and self.token != "" and hmac.compare_digest(supplied.encode(), self.token.encode())

    def _serve(self, client: socket.socket) -> None:
        """Read requests off one connection and queue them for the main thread.
        A request without the token ends the connection after one refusal."""
        client.settimeout(1.0)
        with self.lock:
            self.clients.add(client)
        decoder = json.JSONDecoder()
        buffer = b""
        authenticated = False
        try:
            while self.running:
                try:
                    chunk = client.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                buffer += chunk
                if len(buffer) > (MAX_REQUEST if authenticated else MAX_UNAUTHENTICATED):
                    break
                while buffer:
                    try:
                        text = buffer.decode("utf-8")
                    except UnicodeDecodeError:
                        break  # a character split across chunks: wait for the rest
                    start = len(text) - len(text.lstrip())
                    if start == len(text):
                        buffer = b""
                        break
                    try:
                        command, end = decoder.raw_decode(text, start)
                    except json.JSONDecodeError:
                        break  # incomplete: wait for more
                    buffer = text[end:].encode("utf-8")
                    if not self._authorised(command):
                        print("MCP Bridge: refused a request without a valid bridge token")
                        try:
                            client.sendall(json.dumps(failure("unauthorized")).encode("utf-8"))
                        except OSError:
                            pass
                        return
                    authenticated = True
                    if command.get("type") == "ping":
                        # Answered here, on the reader thread, and never queued:
                        # a ping must reach the client even while a long command
                        # holds the main thread, or the timeout-then-ping check
                        # cannot tell "busy" from "gone".
                        try:
                            client.sendall(json.dumps(ping_reply()).encode("utf-8"))
                        except OSError:
                            break
                        continue
                    self.jobs.put((command, client))
        finally:
            with self.lock:
                self.clients.discard(client)
            try:
                client.close()
            except OSError:
                pass

    def drain(self) -> float | None:
        """Run the queued requests on the main thread and send each reply. The
        loop stops early while a render is running, so the queue waits rather
        than a second command starting beside the render."""
        if not self.running:
            return None
        while not self.rendering.is_set():
            try:
                command, client = self.jobs.get_nowait()
            except queue.Empty:
                break
            reply = handle(command)
            try:
                data = json.dumps(reply)
            except (TypeError, ValueError) as exc:
                data = json.dumps(failure("the reply could not be encoded as JSON: %s" % exc))
            try:
                client.sendall(data.encode("utf-8"))
            except OSError:
                pass  # the client went away; its next request opens a new connection
        return POLL_SECONDS


BRIDGE = Bridge()


def _drain() -> float | None:
    """The timer Blender calls on its main thread; a module-level function, so
    the registration survives and can be found again to unregister."""
    return BRIDGE.drain()


class MCPBridgePreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    port: bpy.props.IntProperty(  # type: ignore[valid-type]
        name="Port", description="Loopback port the MCP server connects to (its BLENDER_PORT)",
        default=DEFAULT_PORT, min=1024, max=65535)

    def draw(self, context: "Context") -> None:
        self.layout.prop(self, "port")


class MCP_OT_bridge_start(bpy.types.Operator):
    bl_idname = "mcp.bridge_start"
    bl_label = "Start"
    bl_description = "Listen for the MCP server on the loopback port, token required"

    def execute(self, context: "Context") -> set[str]:
        prefs = context.preferences.addons[__name__].preferences
        problem = BRIDGE.start(int(getattr(prefs, "port", DEFAULT_PORT)))
        if problem != "":
            self.report({"ERROR"}, problem)
            return {"CANCELLED"}
        return {"FINISHED"}


class MCP_OT_bridge_stop(bpy.types.Operator):
    bl_idname = "mcp.bridge_stop"
    bl_label = "Stop"
    bl_description = "Stop listening and drop every connection"

    def execute(self, context: "Context") -> set[str]:
        BRIDGE.stop()
        return {"FINISHED"}


class MCP_PT_bridge(bpy.types.Panel):
    bl_label = "MCP Bridge"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MCP"

    def draw(self, context: "Context") -> None:
        layout = self.layout
        if BRIDGE.running:
            layout.label(text="Listening on %s:%d" % (HOST, BRIDGE.port), icon="LINKED")
            layout.operator(MCP_OT_bridge_stop.bl_idname, icon="CANCEL")
        else:
            layout.label(text="Stopped", icon="UNLINKED")
            layout.operator(MCP_OT_bridge_start.bl_idname, icon="PLAY")
        if BRIDGE.error != "":
            layout.label(text=BRIDGE.error, icon="ERROR")


CLASSES = (MCPBridgePreferences, MCP_OT_bridge_start, MCP_OT_bridge_stop, MCP_PT_bridge)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    BRIDGE.stop()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
