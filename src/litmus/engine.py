"""Engine: one object that owns the model, sandbox, stores and cached views.

Used by the CLI, the web demo and the evaluation scripts, so they all run the same
pipeline.  Views are cached in memory per (store, version-set, manifest content), and
every vector comes from the content-addressed cache, so switching versions or adding a
version only embeds snippets whose content is new.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time

from .config import Settings
from .embedder import Embedder
from .retriever import CandidateView, Litmus, SearchResponse
from .sandbox import Sandbox
from .store import SnippetStore


class Engine:
    def __init__(self, settings: Settings | None = None, verify: bool = True, workers: int | None = None,
                 k_verify: int = 20, k_expand: int = 30):
        self.settings = settings or Settings()
        self.embedder = Embedder(cache_path=self.settings.embedding_cache)
        self.sandbox = Sandbox(cache_path=self.settings.execution_cache, max_workers=workers) if verify else None
        self.litmus = Litmus(self.embedder, self.sandbox, k_verify=k_verify, k_expand=k_expand, verify=verify)
        self._stores: dict[str, SnippetStore] = {}
        self._views: dict[str, CandidateView] = {}
        self._lock = threading.Lock()
        self.last_build: dict = {}

    # ------------------------------------------------------------- stores
    def store(self, name: str) -> SnippetStore:
        if name not in self._stores:
            self._stores[name] = SnippetStore(os.path.join(self.settings.stores_dir, name))
        return self._stores[name]

    def stores(self) -> list[str]:
        d = self.settings.stores_dir
        return sorted(x for x in os.listdir(d) if os.path.isdir(os.path.join(d, x))) if os.path.isdir(d) else []

    def add_version(self, store: str, version: str, snippets: dict[str, str], parent="latest",
                    source: str = "", partial: bool = False, build: bool = True) -> dict:
        """Register a version and (by default) build its index; returns timing + diff."""
        st = self.store(store)
        t0 = time.perf_counter()
        diff = st.add_version(version, snippets, parent=parent, source=source, partial=partial)
        t1 = time.perf_counter()
        info = {"store": store, "version": version, "diff": diff.to_dict(), "register_s": round(t1 - t0, 3)}
        if build:
            before = self.embedder.stats["encoded"]
            self.view(store, version)
            info["newly_embedded"] = self.embedder.stats["encoded"] - before
            info["index_build_s"] = round(time.perf_counter() - t1, 3)
            info["snippets"] = len(st.entries(version))
        return info

    # ------------------------------------------------------------- views
    def view(self, store: str, version: str | None = "latest", progress: bool = False) -> CandidateView:
        """Searchable view of one version, or of *all* versions when version == 'all'."""
        st = self.store(store)
        if version == "all":
            return self._all_versions_view(st, store, progress)
        v = st.resolve(version)
        entries = st.entries(v)
        key = "%s|%s|%s" % (store, v, hashlib.sha1(json.dumps(entries, sort_keys=True).encode()).hexdigest())
        with self._lock:
            if key in self._views:
                return self._views[key]
        uids = list(entries)
        shas = [entries[u] for u in uids]
        texts = st.texts(shas)
        t0 = time.perf_counter()
        mat = self.embedder.encode_documents(texts, progress=progress)
        self.last_build = {"store": store, "version": v, "snippets": len(uids), "seconds": time.perf_counter() - t0}
        view = CandidateView(uids, shas, mat, texts.__getitem__,
                             [{"uid": u, "versions": [v]} for u in uids], name="%s@%s" % (store, v))
        with self._lock:
            self._views[key] = view
        return view

    def _all_versions_view(self, st: SnippetStore, store: str, progress: bool) -> CandidateView:
        versions = st.versions()
        key = "%s|ALL|%s" % (store, hashlib.sha1("|".join(
            "%s:%s" % (v, json.dumps(st.entries(v), sort_keys=True)) for v in versions).encode()).hexdigest())
        with self._lock:
            if key in self._views:
                return self._views[key]
        occ = st.occurrences(versions)  # sha -> [(version, uid)]
        shas = list(occ)
        texts = st.texts(shas)
        mat = self.embedder.encode_documents(texts, progress=progress)
        order = {v: i for i, v in enumerate(versions)}
        ids, meta = [], []
        for sha in shas:
            vs = sorted({v for v, _ in occ[sha]}, key=order.get)
            uid = occ[sha][0][1]
            ids.append("%s@%s" % (uid, sha[:8]))
            meta.append({"uid": uid, "versions": vs, "first": vs[0], "last": vs[-1],
                         "latest_index": order[vs[-1]], "n_versions": len(versions)})
        view = CandidateView(ids, shas, mat, texts.__getitem__, meta, name="%s@all" % store)
        with self._lock:
            self._views[key] = view
        return view

    # ------------------------------------------------------------- search
    def search(self, query: str, store: str, version: str = "latest", k: int = 10,
               verify: bool = True) -> SearchResponse:
        view = self.view(store, version)
        tie = None
        if version == "all":
            # Evolutionary retrieval: identical evidence -> prefer the most recent version.
            def tie(i: int) -> float:
                m = view.meta[i]
                return 1e-3 * (m["latest_index"] + 1) / m["n_versions"]
        resp = self.litmus.search(query, view, k=k, verify=verify, tie_break=tie)
        resp.stats["view"] = view.name
        return resp

    def close(self) -> None:
        if self.sandbox is not None:
            self.sandbox.close()
        for st in self._stores.values():
            st.close()
