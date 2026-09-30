"""Synthetic code evolution for the version demo and the evolutionary-retrieval benchmark.

* ``refactor``  - behaviour-preserving: consistent renaming of locally bound variables
  and re-formatting through ``ast.unparse`` (comments dropped).  Text and embedding
  drift, behaviour does not.
* ``mutate``    - behaviour-changing single-point bug (comparison boundary, arithmetic
  operator, off-by-one constant), the kind of change a regression commit introduces.
  The mutant is textually almost identical to the original, which is exactly what makes
  cross-version ranking hard for embeddings.
"""

from __future__ import annotations

import ast
import builtins
import keyword
import random

_BUILTINS = set(dir(builtins)) | set(keyword.kwlist)


class _Renamer(ast.NodeTransformer):
    def __init__(self, mapping):
        self.mapping = mapping

    def visit_Name(self, node):
        if node.id in self.mapping:
            node.id = self.mapping[node.id]
        return node

    def visit_arg(self, node):
        if node.arg in self.mapping:
            node.arg = self.mapping[node.arg]
        return node


def refactor(code: str, seed: int = 0) -> str | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                imported.add((a.asname or a.name).split(".")[0])
    stored = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            stored.append(n.id)
        elif isinstance(n, ast.arg):
            stored.append(n.arg)
    names = [x for x in dict.fromkeys(stored) if x not in _BUILTINS and x not in imported and not x.startswith("__")]
    if not names:
        return ast.unparse(tree) + "\n"
    rng = random.Random(seed)
    pool = ["val", "item", "acc", "cnt", "tmp", "res", "cur", "nxt", "lo", "hi", "buf", "idx", "tot", "arr"]
    rng.shuffle(pool)
    mapping = {}
    for i, n in enumerate(names):
        mapping[n] = "%s_%d" % (pool[i % len(pool)], i)
    tree = _Renamer(mapping).visit(tree)
    return ast.unparse(tree) + "\n"


_CMP_SWAP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
_BIN_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv, ast.FloorDiv: ast.Mult}


def _sites(tree):
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for j, op in enumerate(node.ops):
                if type(op) in _CMP_SWAP:
                    sites.append(("cmp", node, j))
        elif isinstance(node, ast.BinOp) and type(node.op) in _BIN_SWAP:
            sites.append(("bin", node, None))
        elif isinstance(node, ast.Constant) and type(node.value) is int and 0 <= node.value <= 1000:
            sites.append(("const", node, None))
    return sites


def mutate(code: str, seed: int = 0) -> tuple[str, str] | None:
    """Return (mutated_code, description) or None if no mutation site exists."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    sites = _sites(tree)
    if not sites:
        return None
    kind, node, j = random.Random(seed).choice(sites)
    if kind == "cmp":
        old = type(node.ops[j])
        node.ops[j] = _CMP_SWAP[old]()
        desc = "comparison %s -> %s" % (old.__name__, type(node.ops[j]).__name__)
    elif kind == "bin":
        old = type(node.op)
        node.op = _BIN_SWAP[old]()
        desc = "operator %s -> %s" % (old.__name__, type(node.op).__name__)
    else:
        desc = "constant %d -> %d" % (node.value, node.value + 1)
        node.value = node.value + 1
    return ast.unparse(tree) + "\n", desc
