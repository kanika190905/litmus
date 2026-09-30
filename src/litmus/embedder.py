"""Dense embedding with a content-addressed vector cache.

Every vector is stored under ``sha1(model | role | instruction | max_len | text)``.
Consequences:

* re-indexing a new code-base version only embeds snippets whose *content* changed
  (P1: incremental rebuilds in seconds instead of hours);
* identical snippets shared by many versions are embedded once (Bonus: all-version
  retrieval costs little more than single-version retrieval);
* evaluation runs are resumable - an interrupted run continues where it stopped.

CPU notes (measured on an i5-13500H, F2LLM-v2-0.6B, fp32): batch size 1 is ~2.7x
faster than batch 16 because padded, masked attention dominates on CPU, so the
default is to encode one sequence at a time, longest-first.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
import threading
import time

import numpy as np

DEFAULT_MODEL = "codefuse-ai/F2LLM-v2-0.6B"
DEFAULT_REVISION = "8786315a8711c242ee03ec67c74dd9ad0a61e2cf"
DEFAULT_INSTRUCTION = "Retrieve the most relevant code snippet for the given query."


class VectorCache:
    """Tiny persistent key -> float32 vector store (SQLite, safe to share across runs)."""

    def __init__(self, path: str | None):
        self._mem: dict[str, np.ndarray] = {}
        self._lock = threading.Lock()
        self._db = None
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self._db = sqlite3.connect(path, check_same_thread=False, timeout=120, isolation_level=None)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.execute("CREATE TABLE IF NOT EXISTS vec (k TEXT PRIMARY KEY, v BLOB)")
            self._db.commit()

    def get_many(self, keys: list[str]) -> dict[str, np.ndarray]:
        out: dict[str, np.ndarray] = {}
        missing = []
        with self._lock:
            for k in keys:
                if k in self._mem:
                    out[k] = self._mem[k]
                else:
                    missing.append(k)
            if self._db is not None and missing:
                for i in range(0, len(missing), 900):
                    chunk = missing[i : i + 900]
                    q = "SELECT k, v FROM vec WHERE k IN (%s)" % ",".join("?" * len(chunk))
                    for k, v in self._db.execute(q, chunk):
                        arr = np.frombuffer(v, dtype=np.float32).copy()
                        self._mem[k] = arr
                        out[k] = arr
        return out

    def put(self, key: str, vec: np.ndarray, commit: bool = False) -> None:
        vec = np.asarray(vec, dtype=np.float32)
        with self._lock:
            self._mem[key] = vec
            if self._db is not None:
                self._db.execute("INSERT OR REPLACE INTO vec VALUES (?, ?)", (key, vec.tobytes()))
                if commit:
                    self._db.commit()

    def commit(self) -> None:
        if self._db is not None:
            with self._lock:
                self._db.commit()

    def __len__(self) -> int:
        if self._db is None:
            return len(self._mem)
        return self._db.execute("SELECT COUNT(*) FROM vec").fetchone()[0]


class Embedder:
    """Wraps a sentence-transformers model; asymmetric query/document encoding."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        revision: str | None = DEFAULT_REVISION,
        cache_path: str | None = None,
        max_length: int = 1024,
        batch_size: int = 1,
        backend: str = "torch",
        threads: int | None = None,
    ):
        self.model_name = model_name
        self.revision = revision if model_name == DEFAULT_MODEL else None
        self.max_length = max_length
        self.batch_size = batch_size
        self.backend = backend
        self.threads = threads
        self.cache = VectorCache(cache_path)
        self._model = None
        self._load_lock = threading.Lock()
        self.stats = {"encoded": 0, "cache_hits": 0, "encode_seconds": 0.0}

    # ------------------------------------------------------------------ model
    @property
    def model(self):
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    import torch
                    from sentence_transformers import SentenceTransformer

                    if self.threads:
                        torch.set_num_threads(self.threads)
                    kwargs = {}
                    if self.backend == "torch":
                        kwargs["model_kwargs"] = {"dtype": torch.float32}  # bf16 is emulated on most CPUs
                    m = SentenceTransformer(
                        self.model_name, device="cpu", backend=self.backend,
                        revision=self.revision, trust_remote_code=False, **kwargs)
                    m.max_seq_length = self.max_length
                    self._model = m
        return self._model

    def _key(self, role: str, instruction: str, text: str) -> str:
        h = hashlib.sha1()
        for part in (self.model_name, role, instruction, str(self.max_length), text):
            h.update(part.encode("utf-8", "surrogatepass"))
            h.update(b"\x00")
        return h.hexdigest()

    @staticmethod
    def query_prefix(instruction: str) -> str:
        return "Instruct: %s\nQuery: " % instruction if instruction else ""

    # ------------------------------------------------------------------ encode
    def encode(
        self,
        texts: list[str],
        role: str = "document",
        instruction: str = "",
        progress: bool = False,
        commit_every: int = 32,
    ) -> np.ndarray:
        """Return L2-normalised float32 embeddings, shape (len(texts), dim)."""
        if role not in ("query", "document"):
            raise ValueError(role)
        instr = instruction if role == "query" else ""
        keys = [self._key(role, instr, t) for t in texts]
        found = self.cache.get_many(list(dict.fromkeys(keys)))
        todo = [i for i, k in enumerate(keys) if k not in found]
        # de-duplicate identical texts
        uniq: dict[str, int] = {}
        for i in todo:
            uniq.setdefault(keys[i], i)
        order = sorted(uniq.values(), key=lambda i: -len(texts[i]))
        self.stats["cache_hits"] += len(keys) - len(todo)
        if order:
            prefix = self.query_prefix(instr) if role == "query" else ""
            t_start = time.time()
            for n, start in enumerate(range(0, len(order), self.batch_size)):
                idx = order[start : start + self.batch_size]
                vecs = self.model.encode(
                    [texts[i] for i in idx], prompt=prefix or None, batch_size=self.batch_size,
                    normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
                for i, v in zip(idx, vecs):
                    found[keys[i]] = v.astype(np.float32)
                    self.cache.put(keys[i], v)
                if (n + 1) % commit_every == 0:
                    self.cache.commit()
                    if progress:
                        done = start + len(idx)
                        el = time.time() - t_start
                        eta = el / done * (len(order) - done)
                        print("  [embed:%s] %d/%d  %.1f/s  eta %.0f min" % (
                            role, done, len(order), done / el, eta / 60), file=sys.stderr, flush=True)
            self.cache.commit()
            self.stats["encoded"] += len(order)
            self.stats["encode_seconds"] += time.time() - t_start
        return np.stack([found[k] for k in keys]) if keys else np.zeros((0, 1), np.float32)

    def encode_queries(self, texts: list[str], instruction: str = DEFAULT_INSTRUCTION, **kw) -> np.ndarray:
        return self.encode(texts, role="query", instruction=instruction, **kw)

    def encode_documents(self, texts: list[str], **kw) -> np.ndarray:
        return self.encode(texts, role="document", **kw)
