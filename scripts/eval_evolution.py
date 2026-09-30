"""Evolutionary-retrieval benchmark (Bonus goal): retrieve across ALL versions.

Built from the representative CoIR-apps subset:

  v1  original corpus
  v2  for N queries, the gold solution receives a random single-point mutation
      (a regression; chosen by random seed, NOT selected using the sample tests)
  v3  the same solutions are replaced by a behaviour-preserving refactor of v1
      (variables renamed, code re-formatted)

Searching across all versions, each evolving lineage contributes three near-identical
items.  Relevance is defined by construction: original (v1) and refactor (v3) are
correct (rel=1), the mutant (v2) is a regression (rel=0).  Unchanged snippets appear
once (content-deduplicated).

Writes results/evolution_eval.json.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time

from litmus.benchmark import apps_subset, evaluate_rankings
from litmus.engine import Engine
from litmus.evolve import mutate, refactor
from litmus.query_analysis import analyze_query
from litmus.store import content_sha

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100, help="number of evolving lineages / queries")
    args = ap.parse_args()
    sub = apps_subset()
    eng = Engine()
    name = "apps-evo-bench"
    shutil.rmtree(os.path.join(eng.settings.stores_dir, name), ignore_errors=True)
    eng.add_version(name, "v1", dict(sub.corpus), parent=None, source="subset", build=False)

    chosen, mutants, refactors, mdesc = [], {}, {}, {}
    for q in sorted(sub.queries, key=lambda q: int(q[1:])):
        if len(chosen) >= args.n:
            break
        if not analyze_query(sub.queries[q]).examples:
            continue
        gold = next(iter(sub.qrels[q]))
        m = mutate(sub.corpus[gold], seed=int(q[1:]))
        r = refactor(sub.corpus[gold], seed=int(q[1:]))
        if not m or not r or m[0] == sub.corpus[gold] or r == sub.corpus[gold] or r == m[0]:
            continue
        chosen.append(q)
        mutants[gold], refactors[gold], mdesc[gold] = m[0], r, m[1]
    eng.add_version(name, "v2", mutants, source="random regressions", partial=True, build=False)
    eng.add_version(name, "v3", refactors, source="refactor of v1", partial=True, build=False)
    t0 = time.perf_counter()
    view = eng.view(name, "all", progress=True)
    build_s = time.perf_counter() - t0

    qrels, queries = {}, {}
    for q in chosen:
        gold = next(iter(sub.qrels[q]))
        rel = {"%s@%s" % (gold, content_sha(sub.corpus[gold])[:8]): 1,
               "%s@%s" % (gold, content_sha(refactors[gold])[:8]): 1}
        qrels[q], queries[q] = rel, sub.queries[q]
    mutant_ids = {q: "%s@%s" % (next(iter(sub.qrels[q])), content_sha(mutants[next(iter(sub.qrels[q]))])[:8])
                  for q in chosen}

    def tie(i: int) -> float:
        m = view.meta[i]
        return 1e-3 * (m["latest_index"] + 1) / m["n_versions"]

    report = {"setup": {"lineages": len(chosen), "items_in_all_versions_view": len(view),
                        "all_versions_view_build_s": round(build_s, 2),
                        "relevance": "original(v1)=1, refactor(v3)=1, regression mutant(v2)=0"},
              "runs": {}}
    for label, verify in (("dense_only", False), ("litmus_exec_verified", True)):
        eng.litmus.k_verify, eng.litmus.k_expand = 20, 30
        t0 = time.perf_counter()
        res, diag = eng.litmus.search_batch(queries, view, top_k=100, verify=verify, tie_break=tie)
        m = evaluate_rankings(res, qrels)
        top1_correct = mutant_above = killed = 0
        for q in chosen:
            ranked = [d for d, _ in sorted(res[q].items(), key=lambda x: -x[1])]
            top1_correct += ranked[0] in qrels[q]
            pos_m = ranked.index(mutant_ids[q]) if mutant_ids[q] in ranked else 10**6
            best_c = min((ranked.index(d) for d in qrels[q] if d in ranked), default=10**6)
            mutant_above += pos_m < best_c
            if verify:
                killed += diag["verifications"][q].get(mutant_ids[q]) not in ("pass_all", None)
        m.update({"correct_version_at_1": round(top1_correct / len(chosen), 4),
                  "regression_ranked_above_correct": round(mutant_above / len(chosen), 4),
                  "seconds": round(time.perf_counter() - t0, 2)})
        if verify:
            m["mutants_failing_sample_tests"] = round(killed / len(chosen), 4)
        report["runs"][label] = m
        print(label, json.dumps(m), flush=True)
    report["mutations"] = {g: mdesc[g] for g in list(mdesc)[:20]}
    with open(os.path.join(ROOT, "results", "evolution_eval.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    eng.close()


if __name__ == "__main__":
    main()
