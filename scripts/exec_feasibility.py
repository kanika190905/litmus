"""Execution-feasibility study: is "run the candidate on the query's sample tests" a useful signal?

For a random sample of test queries with extractable examples, execute (a) the gold
snippet and (b) five random corpus snippets on the query's sample inputs, and tabulate
the verification tiers.  Execution only - no retrieval, no rankings.
Writes results/exec_feasibility.json.
"""

from __future__ import annotations

import collections
import json
import os
import random
import time

from litmus.config import Settings
from litmus.data import load_apps
from litmus.query_analysis import analyze_query
from litmus.sandbox import Sandbox
from litmus.verify import judge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(n: int = 600, negatives: int = 5, seed: int = 0) -> None:
    d = load_apps("test")
    profiles = {q: analyze_query(t) for q, t in d.queries.items()}
    kinds = collections.Counter(p.kind for p in profiles.values())
    with_ex = [q for q, p in profiles.items() if p.examples]
    rng = random.Random(seed)
    sample = rng.sample(sorted(with_ex), n)
    doc_ids = sorted(d.corpus)
    jobs, meta = [], []
    for q in sample:
        ins = [e.input for e in profiles[q].examples]
        gold = next(iter(d.qrels[q]))
        jobs.append((d.corpus[gold], ins))
        meta.append((q, "gold"))
        for doc in rng.sample(doc_ids, negatives):
            if doc != gold:
                jobs.append((d.corpus[doc], ins))
                meta.append((q, "random"))
    sb = Sandbox(cache_path=Settings().execution_cache)
    t0 = time.time()
    res = sb.run_many(jobs)
    dt = time.time() - t0
    sb.close()
    tiers = {"gold": collections.Counter(), "random": collections.Counter()}
    for (q, kind), r in zip(meta, res):
        tiers[kind][judge(r, profiles[q].examples).tier] += 1
    out = {
        "queries_total": len(d.queries), "queries_with_examples": len(with_ex),
        "avg_examples": round(sum(len(profiles[q].examples) for q in with_ex) / len(with_ex), 3),
        "query_kinds": dict(kinds), "sampled_queries": n, "executions": len(jobs),
        "seconds": round(dt, 1),
        "tiers": {k: dict(v) for k, v in tiers.items()},
        "pass_all_rate": {k: round(v["pass_all"] / sum(v.values()), 4) for k, v in tiers.items()},
    }
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    with open(os.path.join(ROOT, "results", "exec_feasibility.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
