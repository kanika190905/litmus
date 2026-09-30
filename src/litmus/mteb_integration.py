"""MTEB adapters.

Two models are exposed so the official ``mteb.evaluate`` flow from the PRISM guidelines
can be used unchanged:

* :class:`PrePostPipelineEncoder` - an ``AbsEncoder`` (exactly the template in the
  guidelines).  It is the *dense stage* only: MTEB computes cosine similarities itself,
  so no post-processing is possible through this interface.
* :class:`LitmusSearch` - an MTEB ``SearchProtocol`` implementation of the *full*
  pipeline (dense retrieval + execution-verified re-ranking + adaptive expansion).
  MTEB's retrieval evaluator accepts any object implementing ``index``/``search``
  (its own BM25 baseline is implemented the same way) and produces the same result
  JSON (``ndcg_at_10``, ``mrr_at_10``, ...).

Neither model reads document or query ids: ids are only passed through so MTEB can score
the returned rankings.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from mteb.models.abs_encoder import AbsEncoder
from mteb.models.model_meta import ModelMeta, ScoringFunction
from mteb.types import PromptType

from . import __version__
from .config import Settings
from .embedder import DEFAULT_INSTRUCTION, DEFAULT_MODEL, Embedder
from .retriever import Litmus
from .sandbox import Sandbox


def _meta(name: str, description: str) -> ModelMeta:
    return ModelMeta.create_empty(overwrites={
        "name": name,
        "revision": __version__,
        "languages": ["eng-Latn", "python-Code"],
        "open_weights": True,
        "embed_dim": 1024,
        "max_tokens": 1024,
        "license": "apache-2.0",
        "similarity_fn_name": ScoringFunction.COSINE,
        "use_instructions": True,
        "reference": "https://huggingface.co/" + DEFAULT_MODEL,
        "adapted_from": DEFAULT_MODEL,
        "public_training_code": None,
        "public_training_data": None,
        "framework": ["PyTorch", "Sentence Transformers"],
        "citation": description,
    })


class PrePostPipelineEncoder(AbsEncoder):
    """Dense stage as an MTEB AbsEncoder (query instruction + F2LLM-v2-0.6B, cosine)."""

    def __init__(self, settings: Settings | None = None, instruction: str = DEFAULT_INSTRUCTION):
        s = settings or Settings()
        self.embedder = Embedder(cache_path=s.embedding_cache)
        self.instruction = instruction
        self.mteb_model_meta = _meta("litmus/dense-f2llm-v2-0.6b", "Litmus dense stage")

    def encode(self, inputs, *, task_metadata, hf_split, hf_subset, prompt_type=None, **kwargs) -> np.ndarray:
        texts: list[str] = []
        for batch in inputs:
            texts.extend(batch["text"])
        if prompt_type == PromptType.query:
            return self.embedder.encode_queries(texts, instruction=self.instruction, progress=True)
        return self.embedder.encode_documents(texts, progress=True)



class LitmusSearch:
    """Full Litmus pipeline as an MTEB SearchProtocol."""

    def __init__(
        self,
        settings: Settings | None = None,
        verify: bool = True,
        k_verify: int = 20,
        k_expand: int = 30,
        workers: int | None = None,
        params: dict | None = None,
    ):
        s = settings or Settings()
        self.sandbox = Sandbox(cache_path=s.execution_cache, max_workers=workers) if verify else None
        self.litmus = Litmus(Embedder(cache_path=s.embedding_cache), self.sandbox, params=params,
                             k_verify=k_verify, k_expand=k_expand, verify=verify)
        name = "litmus/f2llm-v2-0.6b+exec-verify" if verify else "litmus/f2llm-v2-0.6b-dense"
        self.mteb_model_meta = _meta(name, "Litmus: execution-verified code retrieval")
        self.view = None
        self.last_diagnostics: dict[str, Any] = {}

    def index(self, corpus, *, task_metadata, hf_split, hf_subset, encode_kwargs, num_proc=None) -> None:
        docs = {}
        for row in corpus:
            title = row.get("title") or ""
            docs[row["id"]] = (title + "\n" + row["text"]) if title else row["text"]
        self.view = self.litmus.view_from_corpus(docs, name=task_metadata.name, progress=True)

    def search(self, queries, *, task_metadata, hf_split, hf_subset, top_k, encode_kwargs,
               top_ranked=None, num_proc=None) -> dict[str, dict[str, float]]:
        qs = {row["id"]: row["text"] for row in queries}
        results, diag = self.litmus.search_batch(qs, self.view, top_k=top_k, progress=True)
        self.last_diagnostics = diag
        return results

    def close(self) -> None:
        if self.sandbox is not None:
            self.sandbox.close()
