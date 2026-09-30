"""Runtime settings (paths and pipeline hyper-parameters).

All state lives under ``LITMUS_HOME`` (default: ``<repo>/.litmus``):

    embeddings.sqlite   content-addressed vector cache
    executions.sqlite   content-addressed execution-result cache
    stores/<name>/      versioned snippet stores (P1 / Bonus)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def litmus_home() -> str:
    return os.environ.get("LITMUS_HOME") or os.path.join(_REPO, ".litmus")


@dataclass
class Settings:
    home: str = field(default_factory=litmus_home)

    @property
    def embedding_cache(self) -> str:
        return os.path.join(self.home, "embeddings.sqlite")

    @property
    def execution_cache(self) -> str:
        return os.path.join(self.home, "executions.sqlite")

    @property
    def stores_dir(self) -> str:
        return os.path.join(self.home, "stores")
