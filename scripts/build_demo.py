"""Build the demo store ``apps-demo`` with three versions and record rebuild timings.

v1  the representative APPS corpus (1,000 real snippets)
v2  a "regression" commit: 12 solutions get a single-point bug, 40 others are
    refactored (renamed + reformatted), 5 are deleted
v3  a "fix" commit: 8 of the 12 bugs are reverted (identical content to v1, so their
    vectors and execution results are reused from the cache)

Writes results/versioning.json and demo/sample_queries.json.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import time

from litmus.benchmark import apps_subset
from litmus.engine import Engine
from litmus.evolve import mutate, refactor
from litmus.query_analysis import analyze_query
from litmus.verify import judge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    sub = apps_subset()
    eng = Engine()
    store_dir = os.path.join(eng.settings.stores_dir, "apps-demo")
    shutil.rmtree(store_dir, ignore_errors=True)
    rng = random.Random(11)
    report = {}

    t0 = time.perf_counter()
    report["v1"] = eng.add_version("apps-demo", "v1", dict(sub.corpus), parent=None, source="CoIR-apps subset")
    report["v1"]["wall_s"] = round(time.perf_counter() - t0, 2)

    # Queries whose gold snippet will evolve: short-ish statements with examples.
    cands = [q for q in sub.queries if analyze_query(sub.queries[q]).examples and len(sub.queries[q]) < 1400]
    evolving = sorted(rng.sample(cands, 12), key=lambda q: int(q[1:]))
    change: dict[str, str | None] = {}
    bugs = {}
    for q in evolving:
        gold = next(iter(sub.qrels[q]))
        prof = analyze_query(sub.queries[q])
        for seed in range(12):  # pick a mutant that visibly breaks the sample tests
            m = mutate(sub.corpus[gold], seed)
            if not m:
                break
            res = eng.sandbox.run(m[0], [e.input for e in prof.examples])
            if judge(res, prof.examples).tier != "pass_all":
                change[gold] = m[0]
                bugs[gold] = {"query": q, "mutation": m[1]}
                break
    golds = {next(iter(sub.qrels[q])) for q in sub.qrels}
    others = sorted(set(sub.corpus) - golds - set(change), key=lambda d: int(d[1:]))
    for d in rng.sample(others, 40):
        r = refactor(sub.corpus[d], seed=1)
        if r:
            change[d] = r
    for d in rng.sample(sorted(set(others) - set(change)), 5):
        change[d] = None
    t0 = time.perf_counter()
    report["v2"] = eng.add_version("apps-demo", "v2", change, source="regression commit (synthetic)", partial=True)
    report["v2"]["wall_s"] = round(time.perf_counter() - t0, 2)

    fixed = sorted(bugs, key=lambda d: int(d[1:]))[:8]
    t0 = time.perf_counter()
    report["v3"] = eng.add_version("apps-demo", "v3", {d: sub.corpus[d] for d in fixed},
                                   source="fix commit (synthetic)", partial=True)
    report["v3"]["wall_s"] = round(time.perf_counter() - t0, 2)
    t0 = time.perf_counter()
    eng.view("apps-demo", "all")
    report["all_versions_view_s"] = round(time.perf_counter() - t0, 2)
    report["bugs"] = bugs
    report["fixed_in_v3"] = fixed

    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    with open(os.path.join(ROOT, "results", "versioning.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)

    # Sample queries for the demo UI (all real CoIR-apps test queries).
    samples = []
    for q in sorted(sub.queries, key=lambda q: int(q[1:])):
        gold = next(iter(sub.qrels[q]))
        samples.append({"id": q, "gold": gold, "text": sub.queries[q],
                        "evolving": gold in bugs, "title": sub.queries[q].strip().split("\n")[0][:90]})
    os.makedirs(os.path.join(ROOT, "demo", "queries"), exist_ok=True)
    with open(os.path.join(ROOT, "demo", "sample_queries.json"), "w", encoding="utf-8") as f:
        json.dump(samples, f, indent=1, ensure_ascii=False)
    for s in samples:
        if s["evolving"] or len(s["text"]) < 900:
            with open(os.path.join(ROOT, "demo", "queries", s["id"] + ".txt"), "w", encoding="utf-8") as f:
                f.write(s["text"])
    print(json.dumps({k: v for k, v in report.items() if k != "bugs"}, indent=1))
    eng.close()


if __name__ == "__main__":
    main()
