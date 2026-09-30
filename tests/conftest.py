import hashlib
import os
import re
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))


class FakeEmbedder:
    """Deterministic hashed bag-of-tokens embedder (no model download needed)."""

    model_name = "fake-embedder"

    def __init__(self, dim: int = 256):
        self.dim = dim
        self.stats = {"encoded": 0, "cache_hits": 0, "encode_seconds": 0.0}

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, np.float32)
        for tok in re.findall(r"[A-Za-z_]+|\d+", text.lower()):
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.dim] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def encode_documents(self, texts, **kw):
        self.stats["encoded"] += len(texts)
        return np.stack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim), np.float32)

    def encode_queries(self, texts, **kw):
        return self.encode_documents(texts)


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()
