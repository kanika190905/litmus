"""Official MTEB AppsRetrieval evaluation (the PRISM screening procedure).

    python scripts/run_mteb_eval.py                 # full Litmus pipeline  -> appsretrieval_results.json
    python scripts/run_mteb_eval.py --dense-only    # AbsEncoder dense stage -> appsretrieval_results_dense.json

Follows the guideline template (mteb.get_task("AppsRetrieval") + mteb.evaluate +
task_result.to_dict()).  The full pipeline is passed to MTEB as a SearchProtocol model
(the same interface MTEB's own BM25 baseline uses), so MTEB computes every metric.

Runtime on a laptop CPU is dominated by embedding 8,765 snippets + 3,765 queries with
F2LLM-v2-0.6B (~3.3M tokens; ~6-7 h on an i5-13500H).  All vectors are cached, so the
run can be stopped and resumed; `scripts/precompute_embeddings.py --shard i/3` can be
used to pre-compute them in parallel processes first.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time

import mteb

from litmus.mteb_integration import LitmusSearch, PrePostPipelineEncoder

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dense-only", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    model = PrePostPipelineEncoder() if args.dense_only else LitmusSearch()
    task = mteb.get_task("AppsRetrieval")
    t0 = time.time()
    result = mteb.evaluate(model, [task], encode_kwargs={"batch_size": 64}, overwrite_strategy="always",
                           prediction_folder=os.path.join(ROOT, "results", "mteb_predictions"))
    task_result = list(result.task_results)[0]
    out = args.out or os.path.join(ROOT, "results", "appsretrieval_results%s.json" % ("_dense" if args.dense_only else ""))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(task_result.to_dict(), f, indent=2, default=str)  # to_dict() contains datetimes
    scores = task_result.to_dict()["scores"]["test"][0]
    print("NDCG@10 %.4f  MRR@10 %.4f  (%.1f min) -> %s" % (
        scores["ndcg_at_10"], scores["mrr_at_10"], (time.time() - t0) / 60, out))

    # Per-query top-10 as CSV (the guideline's "csv file with the responses").
    if not args.dense_only and getattr(model, "last_diagnostics", None):
        pred_dir = os.path.join(ROOT, "results", "mteb_predictions")
        for fn in os.listdir(pred_dir) if os.path.isdir(pred_dir) else []:
            if fn.startswith("AppsRetrieval") and fn.endswith(".json"):
                with open(os.path.join(pred_dir, fn), encoding="utf-8") as f:
                    preds = json.load(f)
                rows = preds.get("test", preds) if isinstance(preds, dict) else {}
                with open(os.path.join(ROOT, "results", "appsretrieval_responses.csv"), "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["query_id", "rank", "doc_id", "score"])
                    for q, docs in rows.items():
                        if isinstance(docs, dict):
                            for r, (d, s) in enumerate(sorted(docs.items(), key=lambda x: -x[1])[:10], start=1):
                                w.writerow([q, r, d, s])
    if hasattr(model, "close"):
        model.close()


if __name__ == "__main__":
    main()
