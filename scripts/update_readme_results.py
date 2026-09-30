"""Render results/*.json into the README results section (between RESULTS markers)."""

from __future__ import annotations

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    p = os.path.join(ROOT, "results", name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def main() -> None:
    out = []
    full = load("appsretrieval_results.json")
    out.append("### 1.1 Official screening metric (MTEB AppsRetrieval, full test split)\n")
    if full:
        s = full["scores"]["test"][0]
        out.append("| system | NDCG@10 | MRR@10 |\n|---|---|---|\n| Litmus (full pipeline) | **%.4f** | **%.4f** |\n"
                   % (s["ndcg_at_10"], s["mrr_at_10"]))
    else:
        out.append("**Pending, not executed yet.** The full run embeds 8,765 snippets plus 3,765 long queries "
                   "on CPU (~6-7 h on an i5-13500H laptop). Command: `python scripts/run_mteb_eval.py`. "
                   "It is resumable, and the output (`results/appsretrieval_results.json`) is attached to the "
                   "GitHub release when it finishes. For reference, the published score of the dense model we "
                   "build on (F2LLM-v2-0.6B) is NDCG@10 0.9045 / MRR@10 0.8840.\n")
    smoke = load("mteb_smoke_subset.json")
    if smoke:
        s = smoke["scores"]["test"][0]
        out.append("\nThe official MTEB code path was verified end-to-end on the subset below "
                   "(`scripts/smoke_mteb.py`, NDCG@10 %.4f, MRR@10 %.4f, produced by `mteb.evaluate`). "
                   "This is a smoke test, not the screening score.\n" % (s["ndcg_at_10"], s["mrr_at_10"]))

    sub = load("subset_eval.json")
    out.append("\n### 1.2 Representative subset: effect of each stage (P0)\n")
    if sub:
        st = sub["setup"]
        out.append("%d real CoIR-apps **test** queries (random, seed 7) against a %d-snippet corpus "
                   "(their gold solutions + random real distractors). Same queries, same model, only the "
                   "pipeline stage changes. A smaller corpus is easier than the official one, so compare "
                   "rows, not leaderboard numbers.\n\n" % (st["queries"], st["corpus"]))
        out.append("| pipeline | NDCG@10 | MRR@10 | Recall@1 | Recall@10 | executions | wall time |\n|---|---|---|---|---|---|---|\n")
        for name, m in sub["runs"].items():
            out.append("| %s | %.4f | %.4f | %.4f | %.4f | %d | %.0f s |\n" % (
                name, m["ndcg_at_10"], m["mrr_at_10"], m["recall_at_1"], m["recall_at_10"],
                m["executions"], m["seconds_total"]))
        out.append("\nThe runs execute in order and share the execution cache, so the last row only paid for "
                   "the expansion executions. Adaptive expansion changed nothing here because recall@20 is already "
                   "0.995 on this corpus; it matters when the gold snippet sits below rank 20.\n")
        mv = sub.get("movement")
        if mv:
            out.append("\nGround truth at rank 1: %d/200 (dense) -> %d/200 (Litmus). Verification moved the ground "
                       "truth **up in %d queries and down in %d**.\n" % (mv["gold_at_1_dense"], mv["gold_at_1_litmus"],
                                                                    mv["gold_moved_up"], mv["gold_moved_down"]))
        lit = sub["runs"].get("verify_top20_expand30 (Litmus)")
        if lit:
            out.append("\nVerification outcome of the *ground-truth* snippet (Litmus run): %s\n"
                       % ", ".join("%s: %d" % kv for kv in sorted(lit["gold_verification_tiers"].items())))
        out.append("\n<p align=\"center\"><img src=\"docs/figures/subset_results.png\" width=\"70%\"></p>\n")
    else:
        out.append("Pending.\n")

    ver = load("versioning.json")
    out.append("\n### 1.3 Retrieval across versions: incremental rebuilds (P1)\n")
    if ver:
        out.append("| version | change | snippets | newly embedded | index (re)build |\n|---|---|---|---|---|\n")
        for v in ("v1", "v2", "v3"):
            r = ver[v]
            out.append("| %s | %s | %d | %d | %.2f s |\n" % (v, ", ".join("%s %d" % kv for kv in r["diff"].items()),
                                                         r.get("snippets", 0), r.get("newly_embedded", 0), r.get("index_build_s", 0)))
        out.append("\nv1 was built from vectors already in the cache (the subset embedding step). Its cold "
                   "cost is the one-off embedding of 1,000 snippets. The v2 time was measured while three other "
                   "embedding processes were running, so it is pessimistic. The point is the *counts*: only the "
                   "50 changed snippets were embedded, and the v3 revert embedded none. The content-deduplicated "
                   "all-versions view builds in %.2f s.\n" % ver["all_versions_view_s"])
    else:
        out.append("Pending.\n")

    evo = load("evolution_eval.json")
    out.append("\n### 1.4 Retrieval across all versions: evolutionary benchmark (Bonus)\n")
    if evo:
        st = evo["setup"]
        out.append("%d gold solutions evolve through v1 (original, relevant), v2 (random single-point "
                   "regression, not relevant) and v3 (behaviour-preserving refactor, relevant). We search "
                   "the de-duplicated all-versions view (%d items).\n\n" % (st["lineages"], st["items_in_all_versions_view"]))
        out.append("| system | NDCG@10 | MRR@10 | correct version @1 | regression ranked above correct |\n|---|---|---|---|---|\n")
        for name, m in evo["runs"].items():
            out.append("| %s | %.4f | %.4f | %.3f | %.3f |\n" % (name, m["ndcg_at_10"], m["mrr_at_10"],
                                                              m["correct_version_at_1"], m["regression_ranked_above_correct"]))
        k = evo["runs"].get("litmus_exec_verified", {}).get("mutants_failing_sample_tests")
        if k is not None:
            out.append("\n%.1f%% of the random regressions fail the query's sample tests. The rest are "
                       "equivalent or untested mutations that no test-based method can separate.\n" % (100 * k))
        out.append("\n<p align=\"center\"><img src=\"docs/figures/evolution_results.png\" width=\"70%\"></p>\n")
    else:
        out.append("Pending.\n")

    p = os.path.join(ROOT, "README.md")
    txt = open(p, encoding="utf-8").read()
    new = re.sub(r"<!-- RESULTS:START -->.*<!-- RESULTS:END -->",
                 lambda _: "<!-- RESULTS:START -->\n" + "".join(out) + "<!-- RESULTS:END -->", txt, flags=re.S)
    open(p, "w", encoding="utf-8").write(new)
    print("README results section updated")


if __name__ == "__main__":
    main()
