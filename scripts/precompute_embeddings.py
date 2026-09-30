"""Pre-compute (and cache) embeddings for the CoIR-apps corpus and queries.

This is optional - every other entry point embeds lazily through the same cache - but
it lets the expensive, one-off CPU work run unattended and resumably:

    python scripts/precompute_embeddings.py --what corpus test train:800
"""

from __future__ import annotations

import argparse
import random
import sys
import time

from litmus.config import Settings
from litmus.data import load_apps
from litmus.embedder import DEFAULT_INSTRUCTION, Embedder


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", nargs="+", default=["corpus", "test"],
                    help="corpus | test | train[:N] (random subset of N train queries, seed 0)")
    ap.add_argument("--instruction", default=DEFAULT_INSTRUCTION)
    ap.add_argument("--shard", default="0/1", help="i/n: process every n-th item starting at i "
                    "(run n processes with --threads 4 each; ~25%% faster on hybrid laptop CPUs)")
    ap.add_argument("--threads", type=int, default=None)
    args = ap.parse_args()
    si, sn = (int(x) for x in args.shard.split("/"))

    def shard(ids):
        return [x for j, x in enumerate(ids) if j % sn == si]

    s = Settings()
    emb = Embedder(cache_path=s.embedding_cache, threads=args.threads)
    test = load_apps("test")
    for what in args.what:
        t0 = time.time()
        if what == "corpus":
            ids = shard(sorted(test.corpus, key=lambda d: int(d[1:])))
            emb.encode_documents([test.corpus[i] for i in ids], progress=True)
            n = len(ids)
        elif what == "test":
            ids = shard(sorted(test.queries, key=lambda q: int(q[1:])))
            emb.encode_queries([test.queries[i] for i in ids], instruction=args.instruction, progress=True)
            n = len(ids)
        elif what.startswith("train"):
            train = load_apps("train")
            ids = sorted(train.queries, key=lambda q: int(q[1:]))
            if ":" in what:
                ids = sorted(random.Random(0).sample(ids, int(what.split(":")[1])), key=lambda q: int(q[1:]))
            ids = shard(ids)
            emb.encode_queries([train.queries[i] for i in ids], instruction=args.instruction, progress=True)
            n = len(ids)
        else:
            sys.exit("unknown --what %r" % what)
        print("%s: %d texts in %.1f min (%s)" % (what, n, (time.time() - t0) / 60, emb.stats), flush=True)


if __name__ == "__main__":
    main()
