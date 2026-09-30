"""Loading the CoIR ``apps`` benchmark (the corpus used by MTEB ``AppsRetrieval``).

The revision is pinned to the one MTEB uses, so our numbers are comparable with the
official evaluation.  The *train* split is used for tuning (the test split is only
used for final measurement).
"""

from __future__ import annotations

from dataclasses import dataclass

APPS_DATASET = "CoIR-Retrieval/apps"
APPS_REVISION = "f22508f96b7a36c2415181ed8bb76f76e04ae2d5"  # == mteb AppsRetrieval


@dataclass
class RetrievalSplit:
    corpus: dict[str, str]          # doc_id -> code
    queries: dict[str, str]         # query_id -> natural-language query
    qrels: dict[str, dict[str, int]]  # query_id -> {doc_id: relevance}


def load_apps(split: str = "test") -> RetrievalSplit:
    from datasets import load_dataset

    corpus_ds = load_dataset(APPS_DATASET, "corpus", revision=APPS_REVISION)["corpus"]
    query_ds = load_dataset(APPS_DATASET, "queries", revision=APPS_REVISION)["queries"]
    qrel_ds = load_dataset(APPS_DATASET, "default", revision=APPS_REVISION)[split]
    corpus = {r["_id"]: r["text"] for r in corpus_ds}
    qrels: dict[str, dict[str, int]] = {}
    for r in qrel_ds:
        qrels.setdefault(r["query-id"], {})[r["corpus-id"]] = int(r["score"])
    queries = {r["_id"]: r["text"] for r in query_ds if r["_id"] in qrels}
    return RetrievalSplit(corpus=corpus, queries=queries, qrels=qrels)
