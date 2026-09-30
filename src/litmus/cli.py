"""Command-line interface.

    litmus search "QUERY or @file.txt" --store apps-demo [--version v2 | --version all] [-k 5]
    litmus add-version STORE VERSION SOURCE [--chunk function] [--partial]
    litmus versions STORE
    litmus diff STORE OLD NEW
    litmus serve [--port 8000]
"""

from __future__ import annotations

import argparse
import json
import sys


def _read_query(q: str) -> str:
    if q.startswith("@"):
        with open(q[1:], encoding="utf-8") as f:
            return f.read()
    if q == "-":
        return sys.stdin.read()
    return q


def _print_response(resp, show_code: int) -> None:
    p = resp.profile
    print("query: kind=%s lang=%s platform=%s examples=%d" % (p.kind, p.language, p.platform, len(p.examples)))
    t = resp.timings_ms
    print("timings(ms): embed=%.0f dense=%.1f verify=%.0f total=%.0f | verified=%d expanded=%s view=%s" % (
        t["embed_query"], t["dense_search"], t["verify"], t["total"], resp.stats["verified"],
        resp.stats["expanded"], resp.stats.get("view")))
    for h in resp.hits:
        v = h.verification
        badge = "%s %d/%d" % (v.tier, v.passed, v.total) if v else "not-run"
        vers = ",".join(h.meta.get("versions", [])) if h.meta else ""
        print("#%-2d %-32s score=%7.3f cos=%.4f dense_rank=%-3d [%s] %s" % (
            h.rank, h.id[:32], h.score, h.dense, h.dense_rank, badge, ("versions=" + vers) if vers else ""))
        if show_code:
            for ln in h.text.splitlines()[:show_code]:
                print("      | " + ln)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="litmus", description="Execution-verified, version-aware code retrieval")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="search a store")
    s.add_argument("query", help="query text, @file, or - for stdin")
    s.add_argument("--store", default="apps-demo")
    s.add_argument("--version", default="latest", help="version name, 'latest' or 'all'")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--no-verify", action="store_true")
    s.add_argument("--code", type=int, default=0, help="print first N lines of each hit")
    s.add_argument("--json", action="store_true")

    a = sub.add_parser("add-version", help="add a version to a store (incremental index build)")
    a.add_argument("store")
    a.add_argument("version")
    a.add_argument("source", help="apps | dir | file.jsonl | git:REPO@REF")
    a.add_argument("--chunk", default="file", choices=["file", "function"])
    a.add_argument("--partial", action="store_true", help="source is a change set on top of the latest version")
    a.add_argument("--parent", default="latest")

    v = sub.add_parser("versions", help="list versions of a store")
    v.add_argument("store")

    d = sub.add_parser("diff", help="diff two versions")
    d.add_argument("store")
    d.add_argument("old")
    d.add_argument("new")

    sv = sub.add_parser("serve", help="run the web demo")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)

    args = ap.parse_args(argv)
    from .engine import Engine

    if args.cmd == "serve":
        import uvicorn

        from .server import create_app
        uvicorn.run(create_app(), host=args.host, port=args.port)
        return

    eng = Engine(verify=getattr(args, "no_verify", False) is False)
    try:
        if args.cmd == "search":
            resp = eng.search(_read_query(args.query), args.store, args.version, k=args.k, verify=not args.no_verify)
            if args.json:
                print(json.dumps(resp.to_dict(), indent=1))
            else:
                _print_response(resp, args.code)
        elif args.cmd == "add-version":
            from .ingest import load_source
            snippets = load_source(args.source, chunk=args.chunk)
            info = eng.add_version(args.store, args.version, snippets, parent=args.parent,
                                   source=args.source, partial=args.partial)
            print(json.dumps(info, indent=1))
        elif args.cmd == "versions":
            st = eng.store(args.store)
            for name in st.versions():
                m = st.manifest(name)
                print("%-12s parent=%-10s snippets=%-6d diff=%s" % (name, m["parent"], len(m["entries"]), m["diff"]))
        elif args.cmd == "diff":
            print(json.dumps(eng.store(args.store).diff(args.old, args.new).to_dict(), indent=1))
    finally:
        eng.close()


if __name__ == "__main__":
    main()
