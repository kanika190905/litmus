"""Turn a code source into ``{uid: snippet_text}`` for a store version.

Supported sources:

* ``apps``                     - the CoIR-apps corpus (uid = dataset doc id)
* ``path/to/file.jsonl|.json`` - records with ``id``/``_id`` and ``text``/``code``
* ``path/to/dir``              - every source file; ``chunk="file"`` (one snippet per
  file, uid = relative path) or ``chunk="function"`` (Python files split into
  top-level functions / classes / module remainder with :mod:`ast`)
* ``git:REPO@REF``             - a directory as of a git ref, read with ``git show``
  (no checkout, so many versions can be ingested from one clone)
"""

from __future__ import annotations

import ast
import json
import os
import subprocess

CODE_EXTS = {".py"}


def chunk_python(path: str, source: str) -> dict[str, str]:
    """Split a Python module into function/class-level snippets."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {path: source}
    lines = source.splitlines(keepends=True)
    out: dict[str, str] = {}
    covered = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
            end = node.end_lineno
            out["%s::%s" % (path, node.name)] = "".join(lines[start:end])
            covered.update(range(start, end))
    rest = "".join(ln for i, ln in enumerate(lines) if i not in covered).strip()
    if rest:
        out["%s::<module>" % path] = rest + "\n"
    return out


def _from_files(files: dict[str, str], chunk: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel, text in sorted(files.items()):
        if chunk == "function" and rel.endswith(".py"):
            out.update(chunk_python(rel, text))
        else:
            out[rel] = text
    return out


def from_directory(root: str, chunk: str = "file", exts=CODE_EXTS) -> dict[str, str]:
    files = {}
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if not x.startswith(".") and x not in ("__pycache__", "node_modules")]
        for n in names:
            if os.path.splitext(n)[1] in exts:
                p = os.path.join(d, n)
                with open(p, encoding="utf-8", errors="replace") as f:
                    files[os.path.relpath(p, root).replace(os.sep, "/")] = f.read()
    return _from_files(files, chunk)


def from_jsonl(path: str) -> dict[str, str]:
    with open(path, encoding="utf-8") as f:
        if path.endswith(".json"):
            data = json.load(f)
            recs = data.items() if isinstance(data, dict) else ((r.get("id") or r.get("_id"), r.get("text") or r.get("code")) for r in data)
            return {str(k): v for k, v in recs}
        out = {}
        for line in f:
            if line.strip():
                r = json.loads(line)
                out[str(r.get("id") or r.get("_id"))] = r.get("text") if "text" in r else r.get("code")
        return out


def from_git(repo: str, ref: str, chunk: str = "function", exts=CODE_EXTS, subdir: str = "") -> dict[str, str]:
    def git(*args) -> str:
        return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True).stdout.decode("utf-8", "replace")

    names = [n for n in git("ls-tree", "-r", "--name-only", ref, "--", subdir or ".").splitlines()
             if os.path.splitext(n)[1] in exts]
    files = {n: git("show", "%s:%s" % (ref, n)) for n in names}
    return _from_files(files, chunk)


def load_source(spec: str, chunk: str = "file") -> dict[str, str]:
    if spec == "apps":
        from .data import load_apps
        return dict(load_apps("test").corpus)
    if spec.startswith("git:"):
        repo, _, ref = spec[4:].rpartition("@")
        return from_git(repo or ".", ref or "HEAD", chunk=chunk)
    if os.path.isdir(spec):
        return from_directory(spec, chunk=chunk)
    if spec.endswith((".jsonl", ".json")):
        return from_jsonl(spec)
    raise ValueError("unrecognised source %r" % spec)
