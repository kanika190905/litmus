"""Evaluate on the representative CoIR-apps subset (real test queries, sub-sampled corpus).

Runs the same queries through several pipeline configurations and writes
results/subset_eval.json plus per-query rankings (results/subset_rankings.csv).

NOTE: a 1,000-snippet corpus is easier than the official 8,765-snippet corpus, so the
absolute numbers are NOT comparable to the MTEB leaderboard; the *relative* effect of
each pipeline stage on identical queries is what this measures.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time

from litmus.benchmark import apps_subset, evaluate_rankings
from litmus.engine import Engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", type=int, default=200)
    ap.add_argument("--docs", type=int, default=1000)
    args = ap.parse_args()
    sub = apps_subset(args.queries, args.docs)
    eng = Engine()
    lit = eng.litmus
    view = lit.view_from_corpus(sub.corpus, name="apps-subset")
    configs = [
        ("dense_only", dict(verify=False)),
        ("verify_top20", dict(verify=True, k_verify=20, k_expand=0)),
        ("verify_top20_expand30 (Litmus)", dict(verify=True, k_verify=20, k_expand=30)),
    ]
    report = {"setup": {"queries": len(sub.queries), "corpus": len(sub.corpus),
                        "model": eng.embedder.model_name, "fusion_params": lit.params,
                        "note": "subset of CoIR-apps test split; not the official full-corpus score"},
              "runs": {}}
    final_results = None
    for name, cfg in configs:
        lit.k_verify, lit.k_expand = cfg.get("k_verify", 20), cfg.get("k_expand", 30)
        t0 = time.perf_counter()
        results, diag = lit.search_batch(sub.queries, view, top_k=100, verify=cfg["verify"], progress=True)
        dt = time.perf_counter() - t0
        m = evaluate_rankings(results, sub.qrels)
        gold_tiers = {}
        for q in sub.queries:
            g = next(iter(sub.qrels[q]))
            t = diag["verifications"][q].get(g, "not_verified")
            gold_tiers[t] = gold_tiers.get(t, 0) + 1
        m.update({"seconds_total": round(dt, 2), "executions": diag["executions"],
                  "gold_verification_tiers": gold_tiers,
                  "stage_seconds": {k: round(v, 2) for k, v in diag["timings_s"].items()}})
        report["runs"][name] = m
        print(name, json.dumps(m), flush=True)
        final_results = (results, diag)
    kinds = {}
    for p in final_results[1]["profiles"].values():
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    report["setup"]["query_kinds"] = kinds
    # Per-query movement of the ground-truth snippet: dense rank -> Litmus rank.
    per_query, up, down = {}, 0, 0
    res, diag = final_results
    for q in sub.queries:
        g = next(iter(sub.qrels[q]))
        dense_top = diag["dense_top"][q]
        dr = dense_top.index(g) + 1 if g in dense_top else None
        ranked = [d for d, _ in sorted(res[q].items(), key=lambda x: -x[1])]
        fr = ranked.index(g) + 1 if g in ranked else None
        per_query[q] = {"dense_rank": dr, "litmus_rank": fr, "gold_tier": diag["verifications"][q].get(g),
                        "query_chars": len(sub.queries[q])}
        if dr and fr:
            up += fr < dr
            down += fr > dr
    report["movement"] = {"gold_moved_up": up, "gold_moved_down": down,
                          "gold_at_1_dense": sum(1 for v in per_query.values() if v["dense_rank"] == 1),
                          "gold_at_1_litmus": sum(1 for v in per_query.values() if v["litmus_rank"] == 1)}
    report["per_query"] = per_query
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    with open(os.path.join(ROOT, "results", "subset_eval.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    with open(os.path.join(ROOT, "results", "subset_rankings.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["query_id", "rank", "doc_id", "score", "verification"])
        for q, res in final_results[0].items():
            for r, (d, s) in enumerate(sorted(res.items(), key=lambda x: -x[1])[:10], start=1):
                w.writerow([q, r, d, round(s, 4), final_results[1]["verifications"][q].get(d, "")])
    eng.close()


if __name__ == "__main__":
    main()
