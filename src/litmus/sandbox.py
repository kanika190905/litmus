"""Execution sandbox used for execution-verified re-ranking.

``Sandbox.run(code, inputs)`` executes a snippet once per stdin case and returns the
per-case outcomes.  Execution happens in a pool of persistent worker processes
(:mod:`litmus._sandbox_worker`), so a verification costs milliseconds instead of a
process start-up.  Results are cached on disk keyed by ``sha1(code) + sha1(inputs)``;
the cache is content-addressed and therefore version-safe: an edited snippet has a new
hash, an unchanged snippet in a new code-base version is never re-executed.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_sandbox_worker.py")


@dataclass
class CaseResult:
    status: str  # ok | runtime_error | timeout | syntax_error | import_error | blocked | crash
    stdout: str = ""
    error: str = ""
    seconds: float = 0.0
    variant: str = "as_is"  # as_is | wrapped | py2 | none


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", "surrogatepass")).hexdigest()


# --------------------------------------------------------------------------- #
# Output comparison
# --------------------------------------------------------------------------- #

def _as_float(tok: str):
    try:
        return float(tok)
    except ValueError:
        return None


def outputs_match(got: str, expected: str, float_tol: float = 1e-6) -> bool:
    """Judge-style comparison: whitespace-insensitive, case-insensitive words and
    absolute/relative tolerance for real numbers."""
    g, e = got.split(), expected.split()
    if len(g) != len(e):
        return False
    for a, b in zip(g, e):
        if a == b or a.lower() == b.lower():
            continue
        fa, fb = _as_float(a), _as_float(b)
        if fa is not None and fb is not None and abs(fa - fb) <= float_tol * max(1.0, abs(fb)):
            continue
        return False
    return True


# --------------------------------------------------------------------------- #
# OS-level resource limits
# --------------------------------------------------------------------------- #

def _windows_job(memory_bytes: int):
    """Job Object capping per-process memory; children die when the parent exits."""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:  # pragma: no cover
        return None
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BASIC(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD)]

    class EXTENDED(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32.CreateJobObjectW.restype = wintypes.HANDLE
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = EXTENDED()
    # PROCESS_MEMORY | KILL_ON_JOB_CLOSE | DIE_ON_UNHANDLED_EXCEPTION
    info.BasicLimitInformation.LimitFlags = 0x100 | 0x2000 | 0x400
    info.ProcessMemoryLimit = memory_bytes
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        return None

    def assign(proc: subprocess.Popen) -> None:
        k32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(int(proc._handle)))

    assign.job = job  # keep the handle alive as long as the sandbox lives
    return assign


# --------------------------------------------------------------------------- #
# Worker process handle
# --------------------------------------------------------------------------- #

class _Worker:
    def __init__(self, python: str, memory_bytes: int, assign):
        self.workdir = tempfile.mkdtemp(prefix="litmus_w_")
        env = {"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0",
               # single-threaded numeric libraries: no CPU oversubscription across workers and
               # small per-thread buffers (matters under the POSIX address-space cap)
               "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
               "LITMUS_SANDBOX_MEM_BYTES": str(memory_bytes)}
        for k in ("SYSTEMROOT", "TEMP", "TMP", "PATH", "HOME", "USERPROFILE"):
            if k in os.environ:
                env[k] = os.environ[k]
        kwargs = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                      cwd=self.workdir, env=env, bufsize=0)
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        else:  # pragma: no cover - POSIX: new session; the worker caps its own memory
            kwargs["start_new_session"] = True
        self.proc = subprocess.Popen([python, "-I", "-X", "utf8", _WORKER, self.workdir], **kwargs)
        if assign is not None:
            try:
                assign(self.proc)
            except Exception:
                pass
        self.jobs_done = 0
        self.msgs: queue.Queue = queue.Queue()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.proc.stdout.read(n - len(buf))
            if not chunk:
                raise EOFError
            buf += chunk
        return buf

    def _read_loop(self) -> None:
        try:
            while True:
                (n,) = struct.unpack(">I", self._read_exact(4))
                self.msgs.put(json.loads(self._read_exact(n).decode("utf-8")))
        except Exception:
            self.msgs.put(None)  # EOF / broken pipe

    def send(self, obj) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.proc.stdin.write(struct.pack(">I", len(data)) + data)
        self.proc.stdin.flush()

    def alive(self) -> bool:
        return self.proc.poll() is None

    def kill(self) -> None:
        try:
            self.proc.kill()
            self.proc.wait(timeout=5)
        except Exception:
            pass
        shutil.rmtree(self.workdir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Sandbox
# --------------------------------------------------------------------------- #

class Sandbox:
    def __init__(
        self,
        cache_path: str | None = None,
        case_timeout: float = 2.0,
        memory_mb: int = 1536,
        max_workers: int | None = None,
        python: str | None = None,
        max_jobs_per_worker: int = 400,
    ):
        self.case_timeout = case_timeout
        self.memory_bytes = memory_mb * 1024 * 1024
        self.python = python or sys.executable
        self.max_workers = max_workers or max(2, (os.cpu_count() or 4) - 2)
        self.max_jobs_per_worker = max_jobs_per_worker
        self._pool = ThreadPoolExecutor(self.max_workers, thread_name_prefix="sandbox")
        self._idle: queue.LifoQueue = queue.LifoQueue()
        self._lock = threading.Lock()
        self._mem: dict[str, list[CaseResult]] = {}
        self._assign = _windows_job(self.memory_bytes) if os.name == "nt" else None
        self._db = None
        self.stats = {"executed": 0, "cache_hits": 0, "respawns": 0}
        if cache_path:
            os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
            self._db = sqlite3.connect(cache_path, check_same_thread=False, timeout=120, isolation_level=None)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.execute("CREATE TABLE IF NOT EXISTS runs (k TEXT PRIMARY KEY, v TEXT)")
            self._db.commit()

    # -- cache ------------------------------------------------------------- #
    def _key(self, code: str, inputs: list[str]) -> str:
        return "%s:%s:%g" % (_sha1(code), _sha1(json.dumps(inputs)), self.case_timeout)

    def _cache_get(self, key: str):
        with self._lock:
            hit = self._mem.get(key)
            if hit is None and self._db is not None:
                row = self._db.execute("SELECT v FROM runs WHERE k=?", (key,)).fetchone()
                if row:
                    hit = [CaseResult(**r) for r in json.loads(row[0])]
                    self._mem[key] = hit
            if hit is not None:
                self.stats["cache_hits"] += 1
            return hit

    def _cache_put(self, key: str, res: list[CaseResult]) -> None:
        with self._lock:
            self._mem[key] = res
            self.stats["executed"] += 1
            if self._db is not None:
                self._db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?)",
                                 (key, json.dumps([asdict(r) for r in res])))

    def flush(self) -> None:
        if self._db is not None:
            with self._lock:
                self._db.commit()

    # -- workers ----------------------------------------------------------- #
    def _acquire(self) -> _Worker:
        while True:
            try:
                w = self._idle.get_nowait()
            except queue.Empty:
                w = self._spawn()
            if w.alive():
                return w
            w.kill()

    def _spawn(self) -> _Worker:
        w = _Worker(self.python, self.memory_bytes, self._assign)
        msg = w.msgs.get(timeout=60)
        if not msg or not msg.get("ready"):
            w.kill()
            raise RuntimeError("sandbox worker failed to start")
        return w

    def _release(self, w: _Worker, healthy: bool) -> None:
        w.jobs_done += 1
        if healthy and w.alive() and w.jobs_done < self.max_jobs_per_worker:
            self._idle.put(w)
        else:
            w.kill()
            with self._lock:
                self.stats["respawns"] += 1

    def _execute(self, code: str, inputs: list[str]) -> list[CaseResult]:
        w = self._acquire()
        results: list[CaseResult] = []
        healthy = True
        try:
            w.send({"code": code, "inputs": inputs, "timeout": self.case_timeout})
            hard = self.case_timeout + 3.0  # per message; covers GIL-holding C loops
            while True:
                try:
                    msg = w.msgs.get(timeout=hard)
                except queue.Empty:
                    msg = None
                    results.append(CaseResult("timeout", error="hard deadline"))
                if msg is None:
                    healthy = False
                    break
                if msg.get("done"):
                    healthy = not msg.get("dirty", False)
                    break
                results.append(CaseResult(
                    status=msg.get("status", "crash"), stdout=msg.get("stdout", ""),
                    error=msg.get("error", ""), seconds=float(msg.get("seconds", 0.0)),
                    variant=msg.get("variant", "as_is")))
                if msg.get("status") == "timeout":
                    healthy = False
                    break
        except (BrokenPipeError, OSError):
            healthy = False
        finally:
            self._release(w, healthy)
        tail = "timeout" if results and results[-1].status == "timeout" else "crash"
        while len(results) < len(inputs):
            results.append(CaseResult(tail))
        return results[: len(inputs)]

    # -- public API -------------------------------------------------------- #
    def run(self, code: str, inputs: list[str]) -> list[CaseResult]:
        key = self._key(code, inputs)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        res = self._execute(code, inputs)
        self._cache_put(key, res)
        return res

    def run_many(self, jobs: list[tuple[str, list[str]]]) -> list[list[CaseResult]]:
        """Run many (code, inputs) jobs in parallel, preserving order."""
        futures = [self._pool.submit(self.run, c, i) for c, i in jobs]
        return [f.result() for f in futures]

    def close(self) -> None:
        self.flush()
        self._pool.shutdown(wait=True)
        while True:
            try:
                self._idle.get_nowait().kill()
            except queue.Empty:
                break
        if self._db is not None:
            self._db.close()
            self._db = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
