"""Versioned, content-addressed snippet store (P1 + Bonus foundation).

Layout (``<LITMUS_HOME>/stores/<name>/``)::

    blobs.sqlite           sha1(text) -> text           (each distinct snippet stored once)
    versions/<v>.json      {"name", "parent", "created", "source", "entries": {uid: sha}, "diff": {...}}
    history.json           ordered list of version names

A *version* is a manifest mapping a stable snippet id (``uid``: e.g. ``path::function``
or a dataset id) to the content hash of that snippet in that version - the same idea as
a git tree.  Because vectors and execution results are cached by content hash, adding a
version only costs work proportional to what changed, and retrieving across *all*
versions only has to score each distinct snippet once.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass


def content_sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "surrogatepass")).hexdigest()


_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass
class VersionDiff:
    added: list[str]
    removed: list[str]
    modified: list[str]
    unchanged: int

    def to_dict(self) -> dict:
        return {"added": len(self.added), "removed": len(self.removed),
                "modified": len(self.modified), "unchanged": self.unchanged}


class SnippetStore:
    def __init__(self, root: str):
        self.root = root
        os.makedirs(os.path.join(root, "versions"), exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(os.path.join(root, "blobs.sqlite"), check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS blob (sha TEXT PRIMARY KEY, text TEXT)")
        self._db.commit()
        self._manifests: dict[str, dict] = {}

    # ------------------------------------------------------------- history
    def _history_path(self) -> str:
        return os.path.join(self.root, "history.json")

    def versions(self) -> list[str]:
        p = self._history_path()
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def latest(self) -> str | None:
        v = self.versions()
        return v[-1] if v else None

    def resolve(self, version: str | None) -> str:
        vs = self.versions()
        if not vs:
            raise KeyError("store %r has no versions" % self.root)
        if version in (None, "latest", "HEAD"):
            return vs[-1]
        if version not in vs:
            raise KeyError("unknown version %r (have: %s)" % (version, ", ".join(vs)))
        return version

    # ------------------------------------------------------------- blobs
    def put_texts(self, texts: list[str]) -> list[str]:
        shas = [content_sha(t) for t in texts]
        with self._lock:
            self._db.executemany("INSERT OR IGNORE INTO blob VALUES (?, ?)", list(zip(shas, texts)))
            self._db.commit()
        return shas

    def texts(self, shas: list[str]) -> list[str]:
        found: dict[str, str] = {}
        uniq = list(dict.fromkeys(shas))
        with self._lock:
            for i in range(0, len(uniq), 900):
                chunk = uniq[i : i + 900]
                q = "SELECT sha, text FROM blob WHERE sha IN (%s)" % ",".join("?" * len(chunk))
                found.update(dict(self._db.execute(q, chunk).fetchall()))
        return [found[s] for s in shas]

    # ------------------------------------------------------------- versions
    def manifest(self, version: str | None = None) -> dict:
        v = self.resolve(version)
        if v not in self._manifests:
            with open(os.path.join(self.root, "versions", v + ".json"), encoding="utf-8") as f:
                self._manifests[v] = json.load(f)
        return self._manifests[v]

    def entries(self, version: str | None = None) -> dict[str, str]:
        return self.manifest(version)["entries"]

    def add_version(
        self,
        name: str,
        snippets: dict[str, str],
        parent: str | None = "latest",
        source: str = "",
        replace: bool = False,
        partial: bool = False,
    ) -> VersionDiff:
        """Register a new version.

        ``snippets`` maps uid -> text.  With ``partial=True`` it is a *change set*
        applied on top of ``parent`` (uids mapped to ``None`` are deleted); otherwise it
        is the complete content of the new version.
        """
        if not _NAME_RE.match(name) or name in ("latest", "HEAD", "all"):
            raise ValueError("invalid version name %r" % name)
        history = self.versions()
        if name in history and not replace:
            raise ValueError("version %r already exists" % name)
        parent_name = None
        if parent and history:
            parent_name = history[-1] if parent in ("latest", "HEAD") else self.resolve(parent)
        base = dict(self.entries(parent_name)) if parent_name else {}

        live = {u: t for u, t in snippets.items() if t is not None}
        shas = self.put_texts(list(live.values()))
        new_entries = dict(base) if partial else {}
        for uid in [u for u, t in snippets.items() if t is None]:
            new_entries.pop(uid, None)
        new_entries.update(dict(zip(live.keys(), shas)))

        diff = VersionDiff(
            added=[u for u in new_entries if u not in base],
            removed=[u for u in base if u not in new_entries],
            modified=[u for u in new_entries if u in base and base[u] != new_entries[u]],
            unchanged=sum(1 for u in new_entries if base.get(u) == new_entries[u]),
        )
        manifest = {
            "name": name, "parent": parent_name, "created": time.time(), "source": source,
            "entries": new_entries, "diff": diff.to_dict(),
        }
        with open(os.path.join(self.root, "versions", name + ".json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        self._manifests[name] = manifest
        if name not in history:
            history.append(name)
        with open(self._history_path(), "w", encoding="utf-8") as f:
            json.dump(history, f, indent=1)
        return diff

    def diff(self, old: str, new: str) -> VersionDiff:
        a, b = self.entries(old), self.entries(new)
        return VersionDiff(
            added=[u for u in b if u not in a], removed=[u for u in a if u not in b],
            modified=[u for u in b if u in a and a[u] != b[u]],
            unchanged=sum(1 for u in b if a.get(u) == b[u]),
        )

    # ------------------------------------------------------------- evolution
    def occurrences(self, versions: list[str] | None = None) -> dict[str, list[tuple[str, str]]]:
        """sha -> [(version, uid), ...] across the given (default: all) versions."""
        occ: dict[str, list[tuple[str, str]]] = {}
        for v in versions or self.versions():
            for uid, sha in self.entries(v).items():
                occ.setdefault(sha, []).append((v, uid))
        return occ

    def lineage(self, uid: str) -> list[dict]:
        """The history of one logical snippet: [{version, sha, changed}, ...]."""
        out, prev = [], None
        for v in self.versions():
            sha = self.entries(v).get(uid)
            out.append({"version": v, "sha": sha, "changed": sha != prev})
            prev = sha
        return out

    def close(self) -> None:
        with self._lock:
            self._db.close()
