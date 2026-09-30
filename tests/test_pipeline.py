"""End-to-end: store -> versions -> retrieval -> execution verification -> fusion."""

import pytest

from litmus.benchmark import evaluate_rankings, mrr_at_k, ndcg_at_k
from litmus.evolve import mutate, refactor
from litmus.retriever import CandidateView, Litmus
from litmus.sandbox import Sandbox
from litmus.store import SnippetStore, content_sha

QUERY = """Given two integers a and b, print their sum.

-----Examples-----
Input
2 3

Output
5

Input
10 -4

Output
6
"""

CORRECT = "a, b = map(int, input().split())\nprint(a + b)\n"
LOOKALIKE = "a, b = map(int, input().split())\nprint(a - b)  # sum of integers a b\n"
OTHER = "s = input()\nprint(s[::-1])\n"


@pytest.fixture(scope="module")
def sandbox():
    s = Sandbox(case_timeout=1.0, max_workers=2)
    yield s
    s.close()


def _view(emb, docs):
    ids = list(docs)
    texts = [docs[i] for i in ids]
    return CandidateView(ids, [content_sha(t) for t in texts], emb.encode_documents(texts), texts.__getitem__,
                         [{} for _ in ids])


def test_execution_verification_reranks(fake_embedder, sandbox):
    view = _view(fake_embedder, {"lookalike": LOOKALIKE, "correct": CORRECT, "other": OTHER})
    lit = Litmus(fake_embedder, sandbox, k_verify=3, k_expand=0)
    dense = lit.search(QUERY, view, k=3, verify=False)
    assert dense.hits[0].id == "lookalike"  # the look-alike wins on text similarity
    res = lit.search(QUERY, view, k=3)
    assert res.hits[0].id == "correct"
    assert res.hits[0].verification.tier == "pass_all"
    assert res.profile.kind == "task_with_examples" and len(res.profile.examples) == 2


def test_questions_skip_verification(fake_embedder, sandbox):
    view = _view(fake_embedder, {"correct": CORRECT, "other": OTHER})
    res = Litmus(fake_embedder, sandbox).search("print the input string s reversed", view, k=2)
    assert res.stats["verified"] == 0 and res.hits[0].id == "other"


def test_versioned_store_incremental(tmp_path):
    st = SnippetStore(str(tmp_path / "s"))
    d1 = st.add_version("v1", {"a": CORRECT, "b": OTHER}, parent=None)
    assert d1.to_dict() == {"added": 2, "removed": 0, "modified": 0, "unchanged": 0}
    d2 = st.add_version("v2", {"a": LOOKALIKE, "c": "print(1)\n", "b": None}, partial=True)
    assert d2.to_dict() == {"added": 1, "removed": 1, "modified": 1, "unchanged": 0}
    assert set(st.entries("v2")) == {"a", "c"}
    assert st.entries("v1")["a"] == content_sha(CORRECT)
    assert [h["changed"] for h in st.lineage("a")] == [True, True]
    occ = st.occurrences()
    assert len(occ[content_sha(OTHER)]) == 1 and len(occ) == 4


def test_all_versions_prefers_correct_version(fake_embedder, sandbox, tmp_path):
    from litmus.engine import Engine

    class _S:
        stores_dir = str(tmp_path)
        embedding_cache = None
        execution_cache = None

    eng = Engine.__new__(Engine)
    eng.settings, eng.embedder, eng.sandbox = _S(), fake_embedder, sandbox
    eng.litmus = Litmus(fake_embedder, sandbox, k_verify=5, k_expand=0)
    eng._stores, eng._views, eng.last_build = {}, {}, {}
    import threading
    eng._lock = threading.Lock()
    eng.add_version("demo", "v1", {"sum": CORRECT, "rev": OTHER}, parent=None)
    eng.add_version("demo", "v2", {"sum": LOOKALIKE}, partial=True)  # regression
    res = eng.search(QUERY, "demo", "all", k=3)
    top = res.hits[0]
    assert top.meta["uid"] == "sum" and top.meta["versions"] == ["v1"]
    assert top.verification.tier == "pass_all"


def test_evolve_and_metrics():
    r = refactor(CORRECT)
    assert r != CORRECT and "print(" in r
    m = mutate(CORRECT, seed=0)
    assert m and m[0] != CORRECT
    assert ndcg_at_k(["x", "a"], {"a": 1}) == pytest.approx(0.6309, abs=1e-3)
    assert mrr_at_k(["x", "a"], {"a": 1}) == 0.5
    assert evaluate_rankings({"q": {"a": 2.0, "x": 1.0}}, {"q": {"a": 1}})["ndcg_at_10"] == 1.0
