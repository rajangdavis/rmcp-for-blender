"""execute_code under the server's file roots.

An agent's Python runs inside the user's Blender, as the user. This module keeps
it to the roots the server was started with (BLENDER_WRITE_ROOTS,
BLENDER_READ_ROOTS) and away from the process, network and native-code escapes.
The server installs it into Blender the way it installs python/mcp_scripts.py,
and calls run(). Three layers, each covering what the one before cannot see:

1. Upstream's validator (python/safe_mode.py, copied unmodified from
   mcp-for-blender), which the server runs first, rejects the raw escapes: os,
   open, subprocess, sockets, ctypes, eval/exec, the dunder ladder, handlers,
   timers and the rest of persistence.
2. _Paths covers what that validator allows on purpose: Blender's own file I/O,
   which runs in C and raises no audit event. Every path handed to a bpy call
   (a filepath/directory/filename keyword, or the first argument of load, save,
   save_render or save_as) and every value assigned to a path property is
   wrapped in a runtime check against the roots. A save that names no path, and
   so writes over a file the agent never chose, is refused; a render is checked
   against the output paths it will write before it starts.
3. An audit hook (PEP 578) refuses, whenever agent code is on the stack, any
   Python-level file event outside the roots (open, listdir, scandir, remove,
   rename, mkdir and the rest) and every process, network, ctypes, thread and gc
   event. It sees the Python inside bpy too: bpy.path.module_names lists a
   directory through os.listdir, and the glTF and FBX add-ons write through
   open.

This is a guardrail, not a sandbox. Blender's C code reads and writes without
audit events, so layer 2 is static analysis, and static analysis can miss a
route. The kernel-enforced boundary is the OS sandbox in docs/blender-sec.md
(L3).
"""

import ast
import contextlib
import io
import os
import sys
import traceback
import types
from typing import Any, Final, Literal, NoReturn, TypedDict, cast

Mode = Literal["read", "write"]
Roots = tuple[str, ...]
# What agent code may hand Blender as a path; anything else is refused at runtime.
PathValue = str | bytes | os.PathLike[str] | os.PathLike[bytes]
# A path-carrying audit event: (argument index, direction) pairs, then the
# indices of its dir_fd arguments.
PathEvent = tuple[tuple[tuple[int, Mode], ...], tuple[int, ...]]

AGENT: Final = "<mcp-agent>"  # the filename agent code is compiled under; the hook looks for it
STATE: Final = "_mcp_guard_state"
CHECK: Final = "_mcp_path"
RENDER_CHECK: Final = "_mcp_render_outputs"

# Keyword arguments that name a file or folder, on any call.
_PATH_KEYWORDS: Final = ("filepath", "directory", "filename")
# Methods whose first positional argument is a path, and which way it goes.
_POSITIONAL_PATH: Final[dict[str, Mode]] = {"load": "read", "save": "write", "save_render": "write", "save_as": "write"}
# Calls that write to a file the agent did not name unless they are given one.
_SAVES: Final = ("save", "save_as", "save_render", "save_sequence", "save_mainfile", "save_as_mainfile")
# Any of these in a call's dotted name makes its path keywords writes.
_WRITE_WORDS: Final = ("export", "save", "write", "bake", "unpack")
# Properties Blender later reads or writes through, so an assignment is a path.
_PATH_PROPERTIES: Final = ("filepath", "filepath_raw", "base_path", "directory", "cache_directory")
# Names refused wherever they appear.
_REFUSED: Final[dict[str, str]] = {
    "unpack_all": "unpacking writes packed files beside the .blend, outside the roots",
    "unpack_item": "unpacking writes packed files beside the .blend, outside the roots",
    "unpack": "unpacking writes packed files beside the .blend, outside the roots",
    "save_all_modified": "it saves every modified image over its own file",
    "save_userpref": "it overwrites the user's Blender preferences",
    "draw_handler_add": "a draw handler keeps agent code running after the script ends",
    "msgbus": "a msgbus subscription keeps agent code running after the script ends",
}
_CALL_ONLY: Final = frozenset(_POSITIONAL_PATH) | frozenset(_SAVES)

# Audit events refused outright while agent code is on the stack.
_DENY: Final = (
    "subprocess.", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork",
    "os.forkpty", "os.startfile", "os.kill", "os.killpg", "os.putenv", "os.unsetenv",
    "os.chdir", "os.add_dll_directory", "pty.", "socket.", "urllib.", "http.client.",
    "webbrowser.", "ftplib.", "smtplib.", "poplib.", "imaplib.", "nntplib.", "telnetlib.",
    "ctypes.", "_thread.start_new_thread", "sys.addaudithook", "sys.settrace",
    "sys.setprofile", "sys._current_frames", "sys.monitoring.", "gc.", "mmap.",
    "marshal.", "pickle.find_class", "winreg.", "msvcrt.", "sqlite3.",
    "builtins.input", "builtins.breakpoint", "pdb.", "resource.", "signal.",
)
# Audit events that carry paths. A dir_fd makes a path relative to a descriptor
# the hook cannot resolve, so one that is set is refused.
_PATH_EVENTS: Final[dict[str, PathEvent]] = {
    "os.listdir": (((0, "read"),), ()),
    "os.scandir": (((0, "read"),), ()),
    "os.listxattr": (((0, "read"),), ()),
    "os.getxattr": (((0, "read"),), ()),
    "os.remove": (((0, "write"),), (1,)),
    "os.rmdir": (((0, "write"),), (1,)),
    "os.mkdir": (((0, "write"),), (2,)),
    "os.truncate": (((0, "write"),), ()),
    "os.chmod": (((0, "write"),), (2,)),
    "os.chown": (((0, "write"),), (3,)),
    "os.chflags": (((0, "write"),), ()),
    "os.utime": (((0, "write"),), (3,)),
    "os.setxattr": (((0, "write"),), ()),
    "os.removexattr": (((0, "write"),), ()),
    "os.rename": (((0, "write"), (1, "write")), (2, 3)),
    "os.link": (((0, "read"), (1, "write")), (2, 3)),
    "os.symlink": (((0, "read"), (1, "write")), (2,)),
}
_WRITE_FLAGS: Final = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC


class RunArgs(TypedDict, total=False):
    """What the server sends run(): the code, and the roots it resolved."""
    code: str
    write: list[str]
    read: list[str]


class RunResult(TypedDict):
    """What run() answers: everything printed, and an error line or ""."""
    output: str
    error: str


class _State(types.ModuleType):
    """The roots, in a module of their own (see _state)."""
    write: Roots
    read: Roots
    system: Roots
    temp: Roots
    hooked: bool


class Refused(Exception):
    """A construct the guard will not run; the message names the line."""


def _state() -> _State:
    """The roots, in a module of their own. The hook is installed once per
    Blender process and cannot be removed, so a reinstalled guard (a new hash
    of this file) must feed the hook the first one installed: both read here.
    A change to _hook itself takes effect after Blender restarts."""
    state = sys.modules.get(STATE)
    if state is None:
        fresh = _State(STATE)
        fresh.write = fresh.read = fresh.system = fresh.temp = ()
        fresh.hooked = False
        sys.modules[STATE] = fresh
        return fresh
    # A guard installed before this one made it; it carries the same attributes.
    return cast(_State, state)


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _under(path: str, roots: Roots) -> bool:
    for root in roots:
        try:
            if os.path.commonpath([path, root]) == root:
                return True
        except ValueError:  # another drive, on Windows
            pass
    return False


def _allowed(state: _State, mode: Mode) -> Roots:
    if mode == "write":
        return state.write + state.temp
    return state.write + state.read + state.system + state.temp


def _roots_text(state: _State, mode: Mode) -> str:
    if mode == "write":
        return "write roots: %s" % (", ".join(state.write) or "none")
    return "write roots: %s; read roots: %s" % (", ".join(state.write) or "none", ", ".join(state.read) or "none")


def _system_dirs() -> Roots:
    """Where Blender's own Python and data live: agent code reads these whenever
    it imports a module or Blender loads a bundled font. Blender's user config
    folder stays out, since the addon keeps the bridge token there; so do the
    home folder and the filesystem root, should sys.path name them."""
    import bpy
    found: list[str] = [sys.prefix, sys.base_prefix, sys.exec_prefix, os.path.dirname(os.__file__)]
    for kind in ("LOCAL", "SYSTEM"):
        try:
            found.append(bpy.utils.resource_path(kind))
        except Exception:
            pass
    found.extend(sys.path)
    never = (_norm(os.path.expanduser("~")), _norm(os.path.abspath(os.sep)))
    out: list[str] = []
    for path in found:
        if path and os.path.isdir(path):
            norm = _norm(path)
            if norm not in never and norm not in out:
                out.append(norm)
    return tuple(out)


def _check_path(value: PathValue, mode: Mode) -> str:
    """What the rewritten agent code calls on every path it hands Blender: the
    path comes back resolved, or PermissionError says why not."""
    import bpy
    state = _state()
    try:
        text = os.fsdecode(os.fspath(value))
    except TypeError:
        raise PermissionError("a file path must be a string, not %s" % type(value).__name__) from None
    if text.strip() == "":
        raise PermissionError("an empty path means Blender's default location; name one under the %s" % _roots_text(state, mode))
    full: str = bpy.path.abspath(text)
    real = os.path.realpath(full)
    if not _under(os.path.normcase(real), _allowed(state, mode)):
        raise PermissionError("%s is outside the %s" % (real, _roots_text(state, mode)))
    # A trailing separator is meaningful to Blender (render.filepath "out/"
    # writes out/0001.png, "out" writes 0001.png beside it); realpath drops it.
    return real + os.sep if full.endswith(("/", os.sep)) else real


def _render_outputs(writes: bool, scene_name: str | None) -> None:
    """Run before every render agent code starts. With write_still or animation
    the render writes to scene.render.filepath, and a compositor's File Output
    nodes write on every render, so each of those paths must sit under the write
    roots before Blender begins. The render follows."""
    import bpy
    scene = bpy.data.scenes.get(scene_name) if scene_name else bpy.context.scene
    if scene is None:
        return
    if writes:
        _check_path(scene.render.filepath, "write")
    if getattr(scene, "use_nodes", True) and scene.render.use_compositing:
        for tree in (getattr(scene, "node_tree", None), getattr(scene, "compositing_node_group", None)):
            for node in (tree.nodes if tree is not None else ()):
                if node.type == "OUTPUT_FILE":
                    base = getattr(node, "base_path", None) or getattr(node, "directory", None)
                    if base is not None:
                        _check_path(base, "write")


def _hook(event: str, args: tuple[Any, ...]) -> None:
    spec = _PATH_EVENTS.get(event)
    if spec is None and event != "open" and not event.startswith(_DENY):
        return
    frame = sys._getframe(1)
    while frame is not None and frame.f_code.co_filename != AGENT:
        frame = frame.f_back
    if frame is None:
        return  # Blender or an add-on, not agent code
    if event.startswith(_DENY):
        raise PermissionError("execute_code may not use %s: no processes, network, native code, threads or interpreter internals" % event)
    state = cast(_State, sys.modules[STATE])
    if spec is None:  # "open": (path, mode, flags)
        path, mode, flags = (tuple(args) + (None, None, 0))[:3]
        if isinstance(path, int):
            return  # a descriptor some file object already holds
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool((flags or 0) & _WRITE_FLAGS)
        _check_event(state, event, path, "write" if writing else "read")
        return
    paths, dir_fds = spec
    for index in dir_fds:
        if len(args) > index and args[index] is not None:
            raise PermissionError("%s relative to a directory descriptor is not allowed in execute_code" % event)
    for index, direction in paths:
        target = args[index] if len(args) > index else None
        if isinstance(target, int):
            raise PermissionError("%s on a file descriptor is not allowed in execute_code" % event)
        _check_event(state, event, "." if target is None else target, direction)


def _check_event(state: _State, event: str, path: PathValue, mode: Mode) -> None:
    real = _norm(os.fsdecode(os.fspath(path)))
    if not _under(real, _allowed(state, mode)):
        raise PermissionError("%s %s: outside the %s" % (event, real, _roots_text(state, mode)))


def _refuse(node: ast.AST, why: str) -> NoReturn:
    raise Refused("line %s: %s" % (getattr(node, "lineno", "?"), why))


def _wrap(expr: ast.expr, mode: Mode) -> ast.Call:
    return ast.Call(func=ast.Name(id=CHECK, ctx=ast.Load()), args=[expr, ast.Constant(mode)], keywords=[])


def _dotted(func: ast.expr) -> list[str]:
    """The names along a call's dotted target, outermost last: bpy.ops.export_scene.gltf
    gives [bpy, ops, export_scene, gltf]. A target that is not a plain chain gives []."""
    names: list[str] = []
    while isinstance(func, ast.Attribute):
        names.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        names.append(func.id)
    return list(reversed(names))


def _refuse_reserved(tree: ast.AST) -> None:
    """Agent code may not name the guard's own functions, so it can neither call
    nor replace the checks the rewrite inserts."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names = [node.id]
        elif isinstance(node, ast.arg):
            names = [node.arg]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.alias):
            names = [node.asname or node.name]
        else:
            continue
        for name in names:
            if name.startswith("_mcp"):
                _refuse(node, "names starting with _mcp belong to the guard")


class _Paths(ast.NodeTransformer):
    """Wraps every path agent code gives Blender in _check_path, and refuses the
    shapes that would hide one: aliases of the path-taking calls, *args and
    **kwargs, files=, and assignments to a path property inside a tuple."""

    def __init__(self) -> None:
        self.called: set[int] = set()

    def visit_Call(self, node: ast.Call) -> ast.expr:
        func = node.func
        # getattr(x, "name") is x.name to every rule here: the validator lets
        # getattr and setattr take only a literal name.
        if (isinstance(func, ast.Name) and func.id in ("getattr", "setattr", "delattr", "hasattr")
                and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
            literal = node.args[1].value
            if func.id == "getattr" and len(node.args) == 2 and not node.keywords:
                attribute = ast.copy_location(ast.Attribute(value=node.args[0], attr=literal, ctx=ast.Load()), node)
                return cast(ast.expr, self.visit(attribute))
            if func.id == "setattr" and literal in _PATH_PROPERTIES and len(node.args) == 3:
                node.args[2] = _wrap(node.args[2], "write")
            elif literal in _CALL_ONLY or literal in _REFUSED:
                _refuse(node, "%s(..., %r) hides a call the guard has to see; call it directly" % (func.id, literal))
        for arg in node.args:
            if isinstance(arg, ast.Starred):
                _refuse(arg, "*args hides which argument is a path; pass arguments one by one")
        for keyword in node.keywords:
            if keyword.arg is None:
                _refuse(node, "**kwargs hides which argument is a path; spell keyword arguments out")
            if keyword.arg == "files":
                _refuse(node, "files= names files the guard cannot check; pass filepath= instead")

        dotted = _dotted(func)
        name = dotted[-1] if dotted else None
        if name is not None and name in _REFUSED:
            _refuse(node, "%s is not allowed: %s" % (name, _REFUSED[name]))
        self.called.add(id(func))
        # An unknown target (an alias, a call's result) counts as a write, the
        # stricter of the two.
        writing = name is None or len(dotted) == 1 or any(word in part for part in dotted for word in _WRITE_WORDS)
        named = False
        for keyword in node.keywords:
            if keyword.arg in _PATH_KEYWORDS:
                keyword.value = _wrap(keyword.value, "write" if writing else "read")
                named = True
        if name is not None and name in _POSITIONAL_PATH and node.args:
            node.args[0] = _wrap(node.args[0], _POSITIONAL_PATH[name])
            named = True
        if name in _SAVES and not named:
            _refuse(node, "%s() with no filepath writes over a file outside the roots (the image's own, or the open .blend); pass filepath= under the write roots" % name)

        self.generic_visit(node)
        if dotted[-2:] in (["render", "render"], ["render", "opengl"]):
            writes = any(k.arg in ("write_still", "animation") and not (isinstance(k.value, ast.Constant) and not k.value.value)
                         for k in node.keywords)
            scene: ast.expr = next((k.value for k in node.keywords if k.arg == "scene"), ast.Constant(None))
            check = ast.Call(func=ast.Name(id=RENDER_CHECK, ctx=ast.Load()), args=[ast.Constant(writes), scene], keywords=[])
            return ast.copy_location(ast.Subscript(value=ast.Tuple(elts=[check, node], ctx=ast.Load()), slice=ast.Constant(1), ctx=ast.Load()), node)
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        if isinstance(node.ctx, ast.Load):
            if node.attr in _REFUSED:
                _refuse(node, "%s is not allowed: %s" % (node.attr, _REFUSED[node.attr]))
            if id(node) not in self.called:
                render_op = node.attr in ("render", "opengl") and _dotted(node)[-2:-1] == ["render"]
                if node.attr in _CALL_ONLY or render_op:
                    _refuse(node, "%s may only be called directly, so the guard sees the path it is given" % node.attr)
        self.generic_visit(node)
        return node

    def _is_path_target(self, target: ast.expr, node: ast.stmt) -> bool:
        if isinstance(target, ast.Attribute) and target.attr in _PATH_PROPERTIES:
            return True
        if isinstance(target, ast.Starred):
            return self._is_path_target(target.value, node)
        if isinstance(target, (ast.Tuple, ast.List)) and any(self._is_path_target(e, node) for e in target.elts):
            _refuse(node, "assign a path property on its own, so the guard can check the path")
        return False

    def _check_flags(self, targets: list[ast.expr], value: ast.expr | None, node: ast.stmt) -> None:
        for target in targets:
            if isinstance(target, ast.Attribute) and target.attr == "use_disk_cache":
                if not (isinstance(value, ast.Constant) and not value.value):
                    _refuse(node, "a disk cache writes beside the .blend, outside the roots")

    def visit_Assign(self, node: ast.Assign) -> ast.Assign:
        if any(self._is_path_target(t, node) for t in node.targets):
            node.value = _wrap(node.value, "write")
        self._check_flags(node.targets, node.value, node)
        self.generic_visit(node)
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AnnAssign:
        if node.value is not None and self._is_path_target(node.target, node):
            node.value = _wrap(node.value, "write")
        self._check_flags([node.target], node.value, node)
        self.generic_visit(node)
        return node

    def visit_AugAssign(self, node: ast.AugAssign) -> ast.AugAssign:
        if self._is_path_target(node.target, node):
            _refuse(node, "build the path first and assign it whole, so the guard can check it")
        self.generic_visit(node)
        return node

    def visit_For(self, node: ast.For) -> ast.For:
        if self._is_path_target(node.target, node):
            _refuse(node, "a path property cannot be a loop target")
        self.generic_visit(node)
        return node


def _failure(exc: BaseException) -> str:
    """The error line for an exception out of agent code, naming the agent's
    own line rather than one inside Blender or this module."""
    line: int | None = None
    for frame in traceback.extract_tb(exc.__traceback__):
        if frame.filename == AGENT:
            line = frame.lineno
    where = "line %s: " % line if line is not None else ""
    return "%s%s: %s" % (where, type(exc).__name__, exc)


def run(args: RunArgs) -> RunResult:
    """The entry point the server calls with the agent's code, already past the
    validator, and the roots resolved on the server's side. Installs the hook
    once, sets the roots for this call, rewrites the code and runs it. Returns
    what it printed, and an error line when it was refused or raised."""
    import bpy
    state = _state()
    state.write = tuple(_norm(p) for p in args.get("write") or [] if p)
    state.read = tuple(_norm(p) for p in args.get("read") or [] if p)
    temp: str = bpy.app.tempdir or ""
    state.temp = (_norm(temp),) if temp and os.path.isdir(temp) else ()
    if not state.system:
        state.system = _system_dirs()
    if not state.hooked:
        sys.addaudithook(_hook)
        state.hooked = True

    code = args.get("code") or ""
    try:
        tree = ast.parse(code, AGENT)
        _refuse_reserved(tree)
        tree = ast.fix_missing_locations(_Paths().visit(tree))
        compiled = compile(tree, AGENT, "exec")
    except Refused as exc:
        return {"output": "", "error": "refused by the guard, %s" % exc}
    except SyntaxError as exc:
        return {"output": "", "error": "line %s: SyntaxError: %s" % (exc.lineno, exc.msg)}

    out = io.StringIO()
    namespace: dict[str, object] = {"__name__": "__mcp_agent__", CHECK: _check_path, RENDER_CHECK: _render_outputs}
    try:
        with contextlib.redirect_stdout(out):
            exec(compiled, namespace)
    except BaseException as exc:  # SystemExit included: it must not reach Blender
        return {"output": out.getvalue(), "error": _failure(exc)}
    return {"output": out.getvalue(), "error": ""}
