"""FastAPI web demo: ``litmus serve`` then open http://127.0.0.1:8000"""

from __future__ import annotations

import json
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .engine import Engine

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


class SearchRequest(BaseModel):
    query: str
    store: str = "apps-demo"
    version: str = "latest"
    k: int = 10
    verify: bool = True


def create_app(engine: Engine | None = None) -> FastAPI:
    app = FastAPI(title="Litmus code retrieval")
    eng = engine or Engine()
    samples_path = os.path.join(_ROOT, "demo", "sample_queries.json")
    samples = []
    if os.path.exists(samples_path):
        with open(samples_path, encoding="utf-8") as f:
            samples = json.load(f)
    gold = {s["text"]: s["gold"] for s in samples}

    def _warm():
        # load the model and build every view once, so the first real query is fast
        try:
            getattr(eng.embedder, "model", None)  # load the model (encode() may hit the cache)
            if eng.sandbox is not None:  # spawn the sandbox worker pool (distinct jobs: no cache hits)
                import time as _t
                eng.sandbox.run_many([("print(%d)  # warm %f" % (i, _t.time()), ["\n"])
                                      for i in range(eng.sandbox.max_workers)])
            for name in eng.stores():
                eng.view(name, "latest")
                if len(eng.store(name).versions()) > 1:
                    eng.view(name, "all")
        except Exception:  # warm-up is best effort
            pass

    import threading
    threading.Thread(target=_warm, daemon=True).start()

    @app.get("/")
    def index():
        return FileResponse(os.path.join(_STATIC, "index.html"))

    @app.get("/api/info")
    def info():
        stores = {}
        for name in eng.stores():
            st = eng.store(name)
            stores[name] = [{"name": v, "snippets": len(st.entries(v)), "diff": st.manifest(v)["diff"],
                             "source": st.manifest(v).get("source", "")} for v in st.versions()]
        return {"stores": stores, "model": eng.embedder.model_name,
                "k_verify": eng.litmus.k_verify, "k_expand": eng.litmus.k_expand}

    @app.get("/api/samples")
    def get_samples():
        return [{"id": s["id"], "title": s["title"], "evolving": s["evolving"], "gold": s["gold"]} for s in samples]

    @app.get("/api/sample/{qid}")
    def get_sample(qid: str):
        for s in samples:
            if s["id"] == qid:
                return s
        raise HTTPException(404)

    @app.post("/api/search")
    def search(req: SearchRequest):
        try:
            resp = eng.search(req.query, req.store, req.version, k=max(1, min(req.k, 50)), verify=req.verify)
        except KeyError as e:
            raise HTTPException(400, str(e)) from e
        out = resp.to_dict()
        g = gold.get(req.query)
        out["gold"] = g
        out["gold_sha"] = None
        if g:
            st = eng.store(req.store)
            first = st.versions()[0] if st.versions() else None
            out["gold_sha"] = st.entries(first).get(g) if first else None  # the original, labelled snippet
        return out

    @app.get("/api/lineage")
    def lineage(store: str, uid: str):
        st = eng.store(store)
        hist = st.lineage(uid)
        shas = [h["sha"] for h in hist if h["sha"]]
        texts = dict(zip(shas, st.texts(shas))) if shas else {}
        for h in hist:
            h["text"] = texts.get(h["sha"])
        return hist

    return app
