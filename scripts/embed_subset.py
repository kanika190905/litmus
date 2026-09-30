"""Embed the representative APPS subset (docs + queries) into the shared cache."""

from __future__ import annotations

import argparse
import time

from litmus.benchmark import apps_subset
from litmus.config import Settings
from litmus.embedder import Embedder


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", type=int, default=200)
    ap.add_argument("--docs", type=int, default=1000)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--order", default="short", choices=["short", "long", "mid"])
    ap.add_argument("--helper", action="store_true",
                    help="work-steal: embed still-missing items shortest-first, re-checking the cache each time")
    args = ap.parse_args()
    si, sn = (int(x) for x in args.shard.split("/"))
    sub = apps_subset(args.queries, args.docs)
    emb = Embedder(cache_path=Settings().embedding_cache, threads=args.threads)
    t0 = time.time()
    if args.helper:
        from litmus.embedder import DEFAULT_INSTRUCTION
        items = [("document", t) for t in sub.corpus.values()] + [("query", t) for t in sub.queries.values()]
        items.sort(key=lambda x: len(x[1]), reverse=args.order == "long")
        if args.order == "mid":
            m = len(items) // 2
            items = [x for pair in zip(items[m:], reversed(items[:m])) for x in pair] + items[2 * m:]
        n = 0
        for role, text in items:
            key = emb._key(role, DEFAULT_INSTRUCTION if role == "query" else "", text)
            if emb.cache.get_many([key]):
                continue
            emb.encode([text], role=role, instruction=DEFAULT_INSTRUCTION if role == "query" else "")
            n += 1
        print("helper embedded %d items in %.1f min" % (n, (time.time() - t0) / 60), flush=True)
        return
    docs = [t for j, (_, t) in enumerate(sorted(sub.corpus.items())) if j % sn == si]
    emb.encode_documents(docs, progress=True)
    qs = [t for j, (_, t) in enumerate(sorted(sub.queries.items())) if j % sn == si]
    emb.encode_queries(qs, progress=True)
    print("done shard %s in %.1f min %s" % (args.shard, (time.time() - t0) / 60, emb.stats), flush=True)


if __name__ == "__main__":
    main()
