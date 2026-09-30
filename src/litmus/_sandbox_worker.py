"""Persistent sandbox worker (one OS process, many jobs).

Started by :class:`litmus.sandbox.Sandbox` as ``python -I -X utf8 _sandbox_worker.py WORKDIR``.
Protocol on the original stdin/stdout pipes: 4-byte big-endian length + UTF-8 JSON.

    parent -> worker : {"code": str, "inputs": [str, ...], "timeout": float}
    worker -> parent : one {"status": ...} message per case, then {"done": true, ...}

Every case runs in a fresh globals dict with file-descriptor level stdin/stdout
redirection (so ``input()``, ``sys.stdin.buffer``, ``open(0)`` and ``os.write(1, ..)``
all behave as under a real judge).  A PEP 578 audit hook, armed once at start-up and
impossible to remove, blocks process creation, networking, ctypes, registry access and
filesystem mutation outside WORKDIR.  A watchdog thread enforces the per-case time
limit by reporting a timeout and terminating the process; the parent additionally
enforces a hard deadline and a memory cap, and respawns the worker.
"""

import json
import os
import struct
import sys
import threading
import time
import warnings

if os.name != "nt":  # POSIX memory cap (Windows uses a Job Object set by the parent)
    try:
        import resource

        _cap = int(os.environ.get("LITMUS_SANDBOX_MEM_BYTES", "0"))
        if _cap > 0:
            resource.setrlimit(resource.RLIMIT_AS, (_cap, _cap))
    except (ImportError, ValueError, OSError):
        pass

_CH_IN = os.dup(0)
_CH_OUT = os.dup(1)
_WORKDIR = os.path.realpath(sys.argv[1])
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_SRC_DIR))
os.chdir(_WORKDIR)
sys.dont_write_bytecode = True
warnings.simplefilter("ignore")

from litmus import compat  # noqa: E402

_DEVNULL = os.open(os.devnull, os.O_RDWR)
os.dup2(_DEVNULL, 0)
os.dup2(_DEVNULL, 1)
os.dup2(_DEVNULL, 2)
_send_lock = threading.Lock()


def _send(obj):
    data = json.dumps(obj).encode("utf-8")
    with _send_lock:
        os.write(_CH_OUT, struct.pack(">I", len(data)) + data)


def _read_exact(n):
    buf = b""
    while len(buf) < n:
        chunk = os.read(_CH_IN, n - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return buf


def _recv():
    (n,) = struct.unpack(">I", _read_exact(4))
    return json.loads(_read_exact(n).decode("utf-8"))


# ---------------------------------------------------------------- warm imports
import array, bisect, collections, copy, decimal, fractions, functools, heapq, itertools, math, operator, random, re, statistics, string, builtins  # noqa: E401,E402,F401

fractions.gcd = math.gcd  # removed in Python 3.9, common in old solutions
try:  # numpy loads native code via ctypes: import it while still trusted
    import numpy as _np

    for _alias, _t in (("float", float), ("int", int), ("bool", bool), ("object", object), ("complex", complex), ("str", str)):
        if not hasattr(_np, _alias):
            setattr(_np, _alias, _t)
except Exception:  # pragma: no cover - numpy is optional
    pass

# ---------------------------------------------------------------- audit policy
_BLOCKED_PREFIXES = (
    "subprocess.", "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.fork",
    "os.forkpty", "os.kill", "os.killpg", "os.startfile", "socket.", "winreg.", "ctypes.",
    "webbrowser.", "urllib.", "http.", "ftplib.", "smtplib.", "_winapi.CreateProcess",
    "shutil.", "os.chmod", "os.chown", "os.link", "os.symlink", "os.truncate", "os.chdir",
)
_PATH_EVENTS = {"os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.replace", "os.unlink"}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def _inside(path):
    try:
        p = os.path.realpath(os.fspath(path))
    except Exception:
        return False
    return p == _WORKDIR or p.startswith(_WORKDIR + os.sep)


def _audit(event, args):
    if event == "open":
        path, mode, flags = args
        if path is None or isinstance(path, int):
            return
        writing = (mode is not None and any(c in str(mode) for c in "wax+")) or (
            isinstance(flags, int) and flags & _WRITE_FLAGS)
        if writing and not _inside(path):
            raise PermissionError("sandbox: write outside workdir blocked")
        return
    if event in _PATH_EVENTS:
        if not _inside(args[0]):
            raise PermissionError("sandbox: filesystem mutation blocked")
        return
    if event.startswith(_BLOCKED_PREFIXES):
        raise PermissionError("sandbox: %s blocked" % event)


sys.addaudithook(_audit)

# ---------------------------------------------------------------- watchdog
_deadline = [None]


def _watchdog():
    while True:
        time.sleep(0.005)
        dl = _deadline[0]
        if dl is not None and time.perf_counter() > dl:
            try:
                _send({"status": "timeout"})
            finally:
                os._exit(3)


threading.Thread(target=_watchdog, daemon=True, name="litmus-watchdog").start()

_ORIG = {
    "input": builtins.input, "print": builtins.print, "recursion": sys.getrecursionlimit(),
}
_BASE_THREADS = set(threading.enumerate())


def _run_case(code_obj, stdin_text, timeout, idx, max_out):
    in_path = os.path.join(_WORKDIR, "in%d.txt" % idx)
    out_path = os.path.join(_WORKDIR, "out%d.txt" % idx)
    with open(in_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(stdin_text)
    in_fd = os.open(in_path, os.O_RDONLY)
    out_fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    os.dup2(in_fd, 0)
    os.dup2(out_fd, 1)
    sys.stdin = sys.__stdin__ = open(0, "r", encoding="utf-8", closefd=False)
    sys.stdout = sys.__stdout__ = open(1, "w", encoding="utf-8", closefd=False)
    sys.stderr = sys.__stderr__ = open(2, "w", encoding="utf-8", closefd=False)
    glb = {"__name__": "__main__", "__builtins__": builtins, "exit": sys.exit, "quit": sys.exit}
    status, err = "ok", ""
    t0 = time.perf_counter()
    _deadline[0] = t0 + timeout
    try:
        exec(code_obj, glb)
        for t in list(threading.enumerate()):
            if t not in _BASE_THREADS and not t.daemon:
                t.join(max(0.0, _deadline[0] - time.perf_counter()))
    except SystemExit:
        pass
    except (ImportError, ModuleNotFoundError) as exc:
        status, err = "import_error", "%s: %s" % (type(exc).__name__, str(exc)[:160])
    except PermissionError as exc:
        status = "blocked" if "sandbox:" in str(exc) else "runtime_error"
        err = "%s: %s" % (type(exc).__name__, str(exc)[:160])
    except BaseException as exc:  # noqa: BLE001 - every failure mode is data
        status, err = "runtime_error", "%s: %s" % (type(exc).__name__, str(exc)[:160])
    _deadline[0] = None
    elapsed = time.perf_counter() - t0
    try:
        sys.stdout.flush()
    except Exception:
        pass
    os.dup2(_DEVNULL, 0)
    os.dup2(_DEVNULL, 1)
    os.close(in_fd)
    os.close(out_fd)
    with open(out_path, "rb") as f:
        out = f.read(max_out + 1)
    builtins.input, builtins.print = _ORIG["input"], _ORIG["print"]
    sys.setrecursionlimit(_ORIG["recursion"])
    try:
        threading.stack_size(0)
    except Exception:
        pass
    return {
        "status": status, "stdout": out[:max_out].decode("utf-8", "replace"),
        "error": err, "seconds": round(elapsed, 5),
    }


def main():
    _send({"ready": True})
    while True:
        try:
            job = _recv()
        except EOFError:
            os._exit(0)
        code_obj, variant = compat.prepare(job["code"])
        inputs = job["inputs"]
        if code_obj is None:
            for _ in inputs:
                _send({"status": "syntax_error", "error": variant})
            _send({"done": True, "variant": "none", "dirty": False})
            continue
        for i, stdin_text in enumerate(inputs):
            res = _run_case(code_obj, stdin_text, float(job.get("timeout", 2.0)), i, int(job.get("max_output", 1 << 16)))
            res["variant"] = variant
            _send(res)
        dirty = any(t not in _BASE_THREADS for t in threading.enumerate())
        _send({"done": True, "variant": variant, "dirty": dirty})


if __name__ == "__main__":
    main()
