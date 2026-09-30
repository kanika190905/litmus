"""Benchmark helpers: the representative APPS subset and IR metrics.

``apps_subset`` draws real queries from the CoIR-apps *test* split and builds a smaller
corpus from their gold solutions plus random real distractors (train- and test-split
solutions alike).  It exists so the whole pipeline can be exercised end-to-end on a
laptop CPU in minutes; the official AppsRetrieval number requires the full corpus
(``scripts/run_mteb_eval.py``).
"""

from __future__ import annotations

import math
import random

from .data import RetrievalSplit, load_apps


def apps_subset(n_queries: int = 200, n_docs: int = 1000, seed: int = 7) -> RetrievalSplit:
    full = load_apps("test")
    rng = random.Random(seed)
    qids = sorted(rng.sample(sorted(full.queries), n_queries), key=lambda q: int(q[1:]))
    gold = {d for q in qids for d in full.qrels[q]}
    others = sorted(set(full.corpus) - gold, key=lambda d: int(d[1:]))
    docs = sorted(gold | set(rng.sample(others, max(0, n_docs - len(gold)))), key=lambda d: int(d[1:]))
    return RetrievalSplit(
        corpus={d: full.corpus[d] for d in docs},
        queries={q: full.queries[q] for q in qids},
        qrels={q: full.qrels[q] for q in qids},
    )


def ndcg_at_k(ranked: list[str], rel: dict[str, int], k: int = 10) -> float:
    dcg = sum(rel.get(d, 0) / math.log2(i + 2) for i, d in enumerate(ranked[:k]))
    ideal = sorted(rel.values(), reverse=True)[:k]
    idcg = sum(r / math.log2(i + 2) for i, r in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def mrr_at_k(ranked: list[str], rel: dict[str, int], k: int = 10) -> float:
    for i, d in enumerate(ranked[:k]):
        if rel.get(d, 0) > 0:
            return 1.0 / (i + 1)
    return 0.0


def recall_at_k(ranked: list[str], rel: dict[str, int], k: int) -> float:
    pos = [d for d, r in rel.items() if r > 0]
    return sum(1 for d in ranked[:k] if rel.get(d, 0) > 0) / len(pos) if pos else 0.0


def evaluate_rankings(results: dict[str, dict[str, float]], qrels: dict[str, dict[str, int]]) -> dict:
    """results: qid -> {doc_id: score}.  Returns mean metrics (MTEB definitions)."""
    agg = {"ndcg_at_10": 0.0, "mrr_at_10": 0.0, "recall_at_1": 0.0, "recall_at_10": 0.0, "recall_at_50": 0.0}
    n = 0
    for q, rel in qrels.items():
        ranked = [d for d, _ in sorted(results.get(q, {}).items(), key=lambda x: -x[1])]
        agg["ndcg_at_10"] += ndcg_at_k(ranked, rel, 10)
        agg["mrr_at_10"] += mrr_at_k(ranked, rel, 10)
        for k in (1, 10, 50):
            agg["recall_at_%d" % k] += recall_at_k(ranked, rel, k)
        n += 1
    return {k: round(v / max(n, 1), 5) for k, v in agg.items()} | {"n_queries": n}
