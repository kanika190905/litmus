"""Generate the figures used in the README and the presentation (docs/figures/*.png).

Result charts are drawn from the JSON files in results/ - never from hard-coded numbers.
"""

from __future__ import annotations

import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "figures")
PURPLE, BLUE, TEAL, GREY, INK, LIGHT = "#704EA6", "#1428A0", "#2A9D8F", "#63637E", "#1B1B2F", "#F1ECF8"
plt.rcParams.update({"font.family": "Calibri", "font.size": 12})


def _box(ax, x, y, w, h, title, body, color, fc="white"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012,rounding_size=0.02",
                                linewidth=2, edgecolor=color, facecolor=fc))
    ax.text(x + w / 2, y + h - 0.035, title, ha="center", va="top", fontsize=13, fontweight="bold", color=color)
    ax.text(x + w / 2, y + h - 0.105, body, ha="center", va="top", fontsize=10.2, color=INK, linespacing=1.35)


def _arrow(ax, x1, y1, x2, y2, color=GREY, style="-|>", ls="-"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=16,
                                 linewidth=1.8, color=color, linestyle=ls))


def architecture():
    fig, ax = plt.subplots(figsize=(13.33, 6.2), dpi=150)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    y, h, w = 0.52, 0.40, 0.132
    xs = [0.015, 0.180, 0.345, 0.510, 0.675, 0.840]
    boxes = [
        ("Query", "natural-language\nquestion or task\n(EN / RU / ...)", GREY, LIGHT),
        ("1. Analyse", "categorise query\nlanguage, style\nextract sample\ntests (98% of\nAPPS test queries)", PURPLE, "white"),
        ("2. Dense recall", "F2LLM-v2-0.6B\nCPU, fp32, batch 1\ninstruction prompt\ncosine top-50", BLUE, "white"),
        ("3. Verify", "run top-20 in a\nsandbox on the\nquery's own tests\npass / partial /\nwrong / error", PURPLE, "white"),
        ("4. Expand", "nothing passes?\nverify ranks\n21-50 as well\n(agentic\nsearch-until-verified)", PURPLE, "white"),
        ("5. Fuse", "score = cos / T\n+ LLR[tier]\n\nranked snippets\n+ evidence", TEAL, "white"),
    ]
    for (t, b, c, fc), x in zip(boxes, xs):
        _box(ax, x, y, w, h, t, b, c, fc)
    for a, b in zip(xs[:-1], xs[1:]):
        _arrow(ax, a + w + 0.013, y + h / 2, b - 0.013, y + h / 2)
    # storage layer
    sy, sh = 0.05, 0.30
    _box(ax, 0.180, sy, 0.225, sh, "Versioned snippet store",
         "version = manifest {uid -> sha1}\nblobs stored once (content-addressed)\nsources: dir / JSONL / git ref / APPS\ndiff, lineage, history", GREY, LIGHT)
    _box(ax, 0.435, sy, 0.17, sh, "Vector cache",
         "sha1(model, text) -> vector\nnew version embeds only\nchanged snippets (P1)\nresumable eval", GREY, LIGHT)
    _box(ax, 0.635, sy, 0.17, sh, "Execution cache",
         "sha1(code, tests) -> outcome\nunchanged snippet is never\nre-executed", GREY, LIGHT)
    _box(ax, 0.835, sy, 0.14, sh, "All versions",
         "dedupe identical\ncontent, keep\nlineage + version\nspan (Bonus)", TEAL, LIGHT)
    _arrow(ax, 0.29, sy + sh + 0.012, 0.246, y - 0.015, GREY, ls="--")
    _arrow(ax, 0.52, sy + sh + 0.012, 0.411, y - 0.015, GREY, ls="--")
    _arrow(ax, 0.72, sy + sh + 0.012, 0.576, y - 0.015, GREY, ls="--")
    _arrow(ax, 0.905, sy + sh + 0.012, 0.906, y - 0.015, GREY, ls="--")
    fig.savefig(os.path.join(OUT, "architecture.png"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def subset_results():
    p = os.path.join(ROOT, "results", "subset_eval.json")
    if not os.path.exists(p):
        return
    rep = json.load(open(p, encoding="utf-8"))
    runs = rep["runs"]
    names = list(runs)
    labels = {"dense_only": "Dense only\n(F2LLM-v2-0.6B)", "verify_top20": "+ execution\nverification (top-20)",
              "verify_top20_expand30 (Litmus)": "+ adaptive expansion\n(Litmus)"}
    fig, ax = plt.subplots(figsize=(8.6, 4.6), dpi=150)
    metrics = [("ndcg_at_10", "NDCG@10", PURPLE), ("mrr_at_10", "MRR@10", BLUE), ("recall_at_1", "Recall@1", TEAL)]
    bw = 0.26
    for j, (m, lab, c) in enumerate(metrics):
        vals = [runs[n][m] for n in names]
        xs = [i + (j - 1) * bw for i in range(len(names))]
        bars = ax.bar(xs, vals, bw, label=lab, color=c)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.002, "%.3f" % v, ha="center", fontsize=9.5, color=INK)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([labels.get(n, n) for n in names])
    ax.set_ylim(0.90, 1.0)
    ax.set_ylabel("score (axis starts at 0.90)", color=GREY)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.16))
    ax.set_title("Representative subset: %d real test queries, %d-snippet corpus" % (
        rep["setup"]["queries"], rep["setup"]["corpus"]), fontsize=12, color=GREY)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "subset_results.png"), facecolor="white")
    plt.close(fig)


def evolution_results():
    p = os.path.join(ROOT, "results", "evolution_eval.json")
    if not os.path.exists(p):
        return
    rep = json.load(open(p, encoding="utf-8"))
    runs = rep["runs"]
    fig, ax = plt.subplots(figsize=(8.6, 4.2), dpi=150)
    metrics = [("ndcg_at_10", "NDCG@10"), ("correct_version_at_1", "Correct version @1"),
               ("regression_ranked_above_correct", "Regression ranked\nabove correct (lower = better)")]
    bw = 0.36
    for j, (run, c, lab) in enumerate([("dense_only", GREY, "Dense only"), ("litmus_exec_verified", PURPLE, "Litmus")]):
        vals = [runs[run][m] for m, _ in metrics]
        xs = [i + (j - 0.5) * bw for i in range(len(metrics))]
        bars = ax.bar(xs, vals, bw, color=c, label=lab)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.01, "%.2f" % v, ha="center", fontsize=9.5)
    ax.set_xticks(range(len(metrics)))
    ax.set_xticklabels([m[1] for m in metrics])
    ax.set_ylim(0, 1.1)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper right")
    ax.set_title("Retrieval across all versions: %d evolving solutions (v1 original, v2 regression, v3 refactor)"
                 % rep["setup"]["lineages"], fontsize=11, color=GREY)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "evolution_results.png"), facecolor="white")
    plt.close(fig)


def official_results():
    lit = os.path.join(ROOT, "results", "appsretrieval_results.json")
    den = os.path.join(ROOT, "results", "appsretrieval_results_dense.json")
    ref = os.path.join(ROOT, "results", "published_reference.json")
    if not (os.path.exists(lit) and os.path.exists(den) and os.path.exists(ref)):
        return
    L = json.load(open(lit, encoding="utf-8"))["scores"]["test"][0]["ndcg_at_10"]
    D = json.load(open(den, encoding="utf-8"))["scores"]["test"][0]["ndcg_at_10"]
    R = json.load(open(ref, encoding="utf-8"))["ndcg_at_10"]
    rows = [
        ("F2LLM-v2-0.6B alone (our run)", D, GREY),
        ("F2LLM-v2-4B (published)", R["codefuse-ai/F2LLM-v2-4B"], "#B9B9C8"),
        ("F2LLM-v2-8B (published)", R["codefuse-ai/F2LLM-v2-8B"], "#B9B9C8"),
        ("F2LLM-v2-14B (published)", R["codefuse-ai/F2LLM-v2-14B"], "#B9B9C8"),
        ("Litmus: 0.6B + execution verification (ours)", L, PURPLE),
    ]
    fig, ax = plt.subplots(figsize=(8.6, 4.4), dpi=150)
    ys = list(range(len(rows)))[::-1]
    for y, (name, v, c) in zip(ys, rows):
        ax.barh(y, v, color=c, height=0.62)
        ax.text(v + 0.002, y, "%.4f" % v, va="center", fontsize=11, fontweight="bold" if c == PURPLE else None,
                color=PURPLE if c == PURPLE else INK)
    ax.set_yticks(ys)
    ax.set_yticklabels([r[0] for r in rows], fontsize=10.5)
    ax.set_xlim(0.88, 0.985)
    ax.set_xlabel("NDCG@10 (axis starts at 0.88)", color=GREY)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title("Official MTEB AppsRetrieval, full test split (3,765 queries, 8,765 snippets)", fontsize=11.5, color=GREY)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "official_results.png"), facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    architecture()
    subset_results()
    evolution_results()
    official_results()
    print("figures written to", OUT)
