"""Execution-verified re-ranking.

For a query that carries sample tests, each short-listed snippet is executed on the
sample inputs and its outputs are compared with the expected outputs.  The outcome is
summarised as a *tier* and fused with the dense score as evidence:

    score = cos(q, d) / T  +  LLR[tier]

where ``LLR[tier] = log P(tier | relevant) / P(tier | non-relevant)`` is estimated on
the *train* split from the dense retriever's own short-lists (hard negatives), see
``scripts/fit_fusion.py``.  A candidate that reproduces every sample output therefore
jumps above candidates that only *look* similar, while snippets we cannot run (Python 2
leftovers, missing third-party modules) are neither rewarded nor punished.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

from .query_analysis import Example
from .sandbox import CaseResult, outputs_match

TIERS = ("pass_all", "pass_partial", "unverified", "wrong_answer", "error")
_UNRUNNABLE = {"syntax_error", "import_error", "blocked"}

# Defaults; overwritten by fitted values in fusion_params.json when present.
DEFAULT_PARAMS = {
    "temperature": 0.02,
    "llr": {"pass_all": 7.0, "pass_partial": 1.5, "unverified": 0.0, "wrong_answer": -2.0, "error": -3.0},
}


@dataclass
class Verification:
    tier: str
    passed: int
    total: int
    variant: str = "as_is"
    cases: list[dict] = field(default_factory=list)
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "tier": self.tier, "passed": self.passed, "total": self.total,
            "variant": self.variant, "seconds": round(self.seconds, 4), "cases": self.cases,
        }


def judge(results: list[CaseResult], examples: list[Example]) -> Verification:
    passed = 0
    cases = []
    for r, ex in zip(results, examples):
        ok = r.status == "ok" and outputs_match(r.stdout, ex.output)
        passed += ok
        cases.append({
            "status": "pass" if ok else ("wrong_answer" if r.status == "ok" else r.status),
            "got": r.stdout[:400], "expected": ex.output[:400], "error": r.error[:200],
            "seconds": r.seconds,
        })
    total = len(examples)
    statuses = {r.status for r in results}
    variant = results[0].variant if results else "none"
    if total and passed == total:
        tier = "pass_all"
    elif passed > 0:
        tier = "pass_partial"
    elif statuses and statuses <= _UNRUNNABLE:
        tier = "unverified"
    elif variant == "py2":
        tier = "unverified"  # our Python-2 shim is imperfect (e.g. integer '/'): no evidence
    elif "ok" in statuses and not (statuses & {"runtime_error", "timeout", "crash"}):
        tier = "wrong_answer"
    else:
        tier = "error"
    return Verification(tier, passed, total, variant, cases, max((r.seconds for r in results), default=0.0))


def load_params(path: str | None = None) -> dict:
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "fusion_params.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            p = json.load(f)
        merged = dict(DEFAULT_PARAMS)
        merged.update({k: v for k, v in p.items() if k in ("temperature", "llr")})
        return merged
    return dict(DEFAULT_PARAMS)


def fused_score(dense: float, tier: str | None, params: dict) -> float:
    base = dense / params["temperature"]
    if tier is None:
        return base
    return base + params["llr"].get(tier, 0.0)


def llr_from_counts(pos: dict, neg: dict, alpha: float = 1.0) -> dict:
    """Laplace-smoothed log-likelihood ratios per tier."""
    np_, nn = sum(pos.values()), sum(neg.values())
    k = len(TIERS)
    out = {}
    for t in TIERS:
        pp = (pos.get(t, 0) + alpha) / (np_ + alpha * k)
        pn = (neg.get(t, 0) + alpha) / (nn + alpha * k)
        out[t] = round(math.log(pp / pn), 4)
    out["unverified"] = 0.0  # by design: no evidence when we cannot run the snippet
    return out
