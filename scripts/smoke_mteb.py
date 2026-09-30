"""Smoke-test the OFFICIAL MTEB path on the representative subset.

Loads the real ``AppsRetrieval`` task, restricts its test split in memory to the subset
(same queries / corpus as scripts/eval_subset.py) and runs ``mteb.evaluate`` with the
full Litmus pipeline.  Output: results/mteb_smoke_subset.json - proof that the
integration produces a valid MTEB result file.  It is NOT the screening score (that
needs the full corpus: scripts/run_mteb_eval.py).
"""

from __future__ import annotations

import json
import os

import mteb
from datasets import Dataset

from litmus.benchmark import apps_subset
from litmus.mteb_integration import LitmusSearch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    sub = apps_subset()
    task = mteb.get_task("AppsRetrieval")
    task.load_data()
    split = task.dataset["default"]["test"]
    split["corpus"] = split["corpus"].filter(lambda r: r["id"] in sub.corpus)
    split["queries"] = split["queries"].filter(lambda r: r["id"] in sub.queries)
    split["relevant_docs"] = {q: v for q, v in split["relevant_docs"].items() if q in sub.queries}
    assert isinstance(split["corpus"], Dataset) and len(split["corpus"]) == len(sub.corpus)
    model = LitmusSearch()
    res = mteb.evaluate(model, [task], cache=None, overwrite_strategy="always")
    tr = list(res.task_results)[0].to_dict()
    tr["_note"] = "SMOKE TEST on a %d-query / %d-doc subset - not the official AppsRetrieval score" % (
        len(sub.queries), len(sub.corpus))
    out = os.path.join(ROOT, "results", "mteb_smoke_subset.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(tr, f, indent=2, default=str)
    s = tr["scores"]["test"][0]
    print("MTEB smoke (subset): ndcg_at_10=%.4f mrr_at_10=%.4f -> %s" % (s["ndcg_at_10"], s["mrr_at_10"], out))
    model.close()


if __name__ == "__main__":
    main()
