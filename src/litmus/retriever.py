"""The Litmus retrieval pipeline.

    query --> analyse (category, language, executable examples)
          --> pass 1: dense retrieval over the candidate view   (F2LLM-v2-0.6B, cosine)
          --> pass 2: execute the top-K candidates on the query's examples (sandbox)
          --> pass 3: adaptive expansion - if nothing in the top-K reproduces the
                      examples, verify the next K' candidates as well
          --> evidence fusion: cos/T + LLR[verification tier]  -> final ranking

Queries without executable examples skip passes 2-3 and are ranked by the dense score.
Everything is cached by content hash (vectors and execution results), so repeated
queries, new code-base versions and all-version retrieval reuse earlier work.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .embedder import DEFAULT_INSTRUCTION, Embedder
from .query_analysis import QueryProfile, analyze_query
from .sandbox import Sandbox
from .store import content_sha
from .verify import Verification, fused_score, judge, load_params


@dataclass
class CandidateView:
    """A searchable set of snippets: parallel arrays + an embedding matrix."""

    ids: list[str]
    shas: list[str]
    matrix: np.ndarray
    get_text: Callable[[int], str]
    meta: list[dict] = field(default_factory=list)
    name: str = ""

    def __len__(self) -> int:
        return len(self.ids)


@dataclass
class Hit:
    rank: int
    id: str
    sha: str
    dense: float
    dense_rank: int
    score: float
    verification: Verification | None = None
    meta: dict = field(default_factory=dict)
    text: str = ""

    def to_dict(self, with_text: bool = True) -> dict:
        d = {
            "rank": self.rank, "id": self.id, "sha": self.sha, "dense": round(self.dense, 5),
            "dense_rank": self.dense_rank, "score": round(self.score, 4), "meta": self.meta,
            "verification": self.verification.to_dict() if self.verification else None,
        }
        if with_text:
            d["text"] = self.text
        return d


@dataclass
class SearchResponse:
    query: str
    profile: QueryProfile
    hits: list[Hit]
    timings_ms: dict
    stats: dict

    def to_dict(self) -> dict:
        return {
            "profile": self.profile.to_dict(),
            "examples": [{"input": e.input, "output": e.output} for e in self.profile.examples],
            "hits": [h.to_dict() for h in self.hits], "timings_ms": self.timings_ms, "stats": self.stats,
        }


class Litmus:
    def __init__(
        self,
        embedder: Embedder,
        sandbox: Sandbox | None,
        params: dict | None = None,
        k_verify: int = 20,
        k_expand: int = 30,
        instruction: str = DEFAULT_INSTRUCTION,
        verify: bool = True,
    ):
        self.embedder = embedder
        self.sandbox = sandbox
        self.params = params or load_params()
        self.k_verify = k_verify
        self.k_expand = k_expand
        self.instruction = instruction
        self.verify_enabled = verify and sandbox is not None

    # ------------------------------------------------------------------ views
    def view_from_corpus(self, corpus: dict[str, str], name: str = "corpus", progress: bool = False) -> CandidateView:
        ids = list(corpus)
        texts = [corpus[i] for i in ids]
        mat = self.embedder.encode_documents(texts, progress=progress)
        return CandidateView(ids, [content_sha(t) for t in texts], mat, texts.__getitem__, [{} for _ in ids], name)

    # ------------------------------------------------------------------ dense
    @staticmethod
    def _topn(scores: np.ndarray, n: int) -> np.ndarray:
        n = min(n, scores.shape[-1])
        part = np.argpartition(-scores, n - 1)[:n]
        return part[np.argsort(-scores[part], kind="stable")]

    # ------------------------------------------------------------------ verify
    def _verify(self, view: CandidateView, idxs: list[int], profile: QueryProfile) -> list[Verification]:
        inputs = [e.input for e in profile.examples]
        results = self.sandbox.run_many([(view.get_text(i), inputs) for i in idxs])
        return [judge(r, profile.examples) for r in results]

    def _rank(self, view, order, dense, verifs: dict[int, Verification], k: int, tie_break=None) -> list[Hit]:
        scored = []
        for r, i in enumerate(order):
            v = verifs.get(int(i))
            s = fused_score(float(dense[i]), v.tier if v else None, self.params)
            if tie_break is not None:
                s += tie_break(int(i))
            scored.append((s, -r, int(i), r, v))
        scored.sort(reverse=True)
        hits = []
        for rank, (s, _, i, r, v) in enumerate(scored[:k], start=1):
            hits.append(Hit(rank, view.ids[i], view.shas[i], float(dense[i]), r + 1, s, v,
                            dict(view.meta[i]) if view.meta else {}, view.get_text(i)))
        return hits

    def search(self, query: str, view: CandidateView, k: int = 10, verify: bool | None = None,
               tie_break=None, depth: int = 100) -> SearchResponse:
        """Single-query search with per-stage timings (used by the CLI, API and demo)."""
        verify = self.verify_enabled if verify is None else (verify and self.sandbox is not None)
        getattr(self.embedder, "model", None)  # one-off model load is not query latency
        t0 = time.perf_counter()
        profile = analyze_query(query)
        t1 = time.perf_counter()
        before = self.embedder.stats["encoded"]
        q = self.embedder.encode_queries([query], instruction=self.instruction)[0]
        cached = self.embedder.stats["encoded"] == before
        t2 = time.perf_counter()
        dense = view.matrix @ q
        order = self._topn(dense, max(depth, k, self.k_verify + self.k_expand))
        t3 = time.perf_counter()
        verifs: dict[int, Verification] = {}
        expanded = False
        if verify and profile.examples:
            first = [int(i) for i in order[: self.k_verify]]
            verifs.update(zip(first, self._verify(view, first, profile)))
            if not any(v.tier == "pass_all" for v in verifs.values()) and self.k_expand > 0:
                more = [int(i) for i in order[self.k_verify : self.k_verify + self.k_expand]]
                verifs.update(zip(more, self._verify(view, more, profile)))
                expanded = True
        t4 = time.perf_counter()
        hits = self._rank(view, order, dense, verifs, k, tie_break)
        t5 = time.perf_counter()
        timings = {
            "analyse": (t1 - t0) * 1e3, "embed_query": (t2 - t1) * 1e3, "dense_search": (t3 - t2) * 1e3,
            "verify": (t4 - t3) * 1e3, "fuse": (t5 - t4) * 1e3, "total": (t5 - t0) * 1e3,
        }
        stats = {
            "candidates": len(view), "verified": len(verifs), "expanded": expanded,
            "query_embedding_cached": cached,
            "tiers": {t: sum(1 for v in verifs.values() if v.tier == t) for t in
                      ("pass_all", "pass_partial", "unverified", "wrong_answer", "error")},
        }
        return SearchResponse(query, profile, hits, {k_: round(v, 1) for k_, v in timings.items()}, stats)

    # ------------------------------------------------------------------ batch
    def search_batch(self, queries: dict[str, str], view: CandidateView, top_k: int = 100,
                     verify: bool | None = None, progress: bool = False, tie_break=None) -> tuple[dict, dict]:
        """Batch search for evaluation.  Returns ({qid: {doc_id: score}}, diagnostics)."""
        verify = self.verify_enabled if verify is None else (verify and self.sandbox is not None)
        qids = list(queries)
        t0 = time.perf_counter()
        profiles = {q: analyze_query(queries[q]) for q in qids}
        qmat = self.embedder.encode_queries([queries[q] for q in qids], instruction=self.instruction, progress=progress)
        t1 = time.perf_counter()
        depth = max(top_k, self.k_verify + self.k_expand)
        orders, denses = {}, {}
        for s in range(0, len(qids), 256):
            block = qmat[s : s + 256] @ view.matrix.T
            for j, q in enumerate(qids[s : s + 256]):
                denses[q] = block[j]
                orders[q] = self._topn(block[j], depth)
        t2 = time.perf_counter()
        verifs: dict[str, dict[int, Verification]] = {q: {} for q in qids}
        n_exec = 0
        if verify:
            for rnd in ("first", "expand"):
                jobs, keys = [], []
                for q in qids:
                    p = profiles[q]
                    if not p.examples:
                        continue
                    if rnd == "first":
                        idxs = [int(i) for i in orders[q][: self.k_verify]]
                    else:
                        if any(v.tier == "pass_all" for v in verifs[q].values()) or self.k_expand <= 0:
                            continue
                        idxs = [int(i) for i in orders[q][self.k_verify : self.k_verify + self.k_expand]]
                    inputs = [e.input for e in p.examples]
                    for i in idxs:
                        jobs.append((view.get_text(i), inputs))
                        keys.append((q, i))
                if progress:
                    print("  [verify:%s] %d executions" % (rnd, len(jobs)), flush=True)
                res = self.sandbox.run_many(jobs)
                n_exec += len(jobs)
                for (q, i), r in zip(keys, res):
                    verifs[q][i] = judge(r, profiles[q].examples)
                self.sandbox.flush()
        t3 = time.perf_counter()
        out = {}
        for q in qids:
            hits = self._rank(view, orders[q], denses[q], verifs[q], top_k, tie_break)
            out[q] = {h.id: h.score for h in hits}
        t4 = time.perf_counter()
        diag = {
            "profiles": {q: p.to_dict() for q, p in profiles.items()},
            "verifications": {q: {view.ids[i]: v.tier for i, v in vs.items()} for q, vs in verifs.items()},
            "dense_top": {q: [view.ids[int(i)] for i in orders[q][:depth]] for q in qids},
            "timings_s": {"analyse+embed": t1 - t0, "dense": t2 - t1, "verify": t3 - t2, "fuse": t4 - t3},
            "executions": n_exec,
        }
        return out, diag
