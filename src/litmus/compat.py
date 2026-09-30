"""Make historical competitive-programming snippets executable on a modern Python 3.

Only used to *execute* a candidate for verification; the indexed text is never changed.
Three strategies are tried in order and the first that compiles wins:

1. ``as_is``   – the snippet itself.
2. ``wrapped`` – snippets extracted from a function body (top-level ``return`` /
   ``nonlocal``) are wrapped in a function and called.
3. ``py2``     – light-weight source rewriting of the most common Python 2 idioms
   (print statement, raw_input, xrange, ``except E, e``, long literals, ...).
"""

from __future__ import annotations

import re
import warnings

_WRAP_ERRORS = ("outside function", "nonlocal", "'yield' outside")


def _compile(src: str):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return compile(src, "<candidate>", "exec")


def _wrap(src: str) -> str:
    body = "\n".join("    " + ln for ln in src.splitlines())
    return "def __litmus_main__():\n" + (body if body.strip() else "    pass") + "\n__litmus_main__()\n"


_PRINT_RE = re.compile(r"^(\s*)print\b(?!\s*\()(?!\s*=)(.*)$")


def _fix_print(line: str) -> str:
    m = _PRINT_RE.match(line)
    if not m:
        return line
    indent, rest = m.group(1), m.group(2).strip()
    comment = ""
    if "#" in rest and rest.count('"') % 2 == 0 and rest.count("'") % 2 == 0:
        idx = rest.find("#")
        rest, comment = rest[:idx].rstrip(), "  " + rest[idx:]
    if rest.startswith(">>"):
        return indent + "pass" + comment
    if rest.endswith(";"):
        rest = rest[:-1].rstrip()
    if not rest:
        return indent + "print()" + comment
    if rest.endswith(","):
        return indent + "print(" + rest[:-1] + ", end=' ')" + comment
    return indent + "print(" + rest + ")" + comment


def py2_to_py3(src: str) -> str:
    out = []
    for line in src.splitlines():
        line = _fix_print(line)
        out.append(line)
    s = "\n".join(out)
    s = re.sub(r"\binput\s*\(", "__py2_input__(", s)
    s = re.sub(r"\braw_input\b", "input", s)
    s = re.sub(r"\bxrange\b", "range", s)
    s = re.sub(r"\.iter(items|keys|values)\s*\(", r".\1(", s)
    s = re.sub(r"\.has_key\s*\(", ".__contains__(", s)
    s = re.sub(r"\bsys\.maxint\b", "sys.maxsize", s)
    s = re.sub(r"\bunichr\b", "chr", s)
    s = re.sub(r"\bunicode\s*\(", "str(", s)
    s = re.sub(r"\blong\s*\(", "int(", s)
    s = re.sub(r"\b(\d+)[lL]\b", r"\1", s)
    s = re.sub(r"except\s+([\w.]+)\s*,\s*(\w+)\s*:", r"except \1 as \2:", s)
    s = re.sub(r"except\s*\(([^)]*)\)\s*,\s*(\w+)\s*:", r"except (\1) as \2:", s)
    s = re.sub(r"^(\s*)raise\s+(\w+)\s*,\s*(.+)$", r"\1raise \2(\3)", s, flags=re.M)
    s = re.sub(r"`([^`\n]+)`", r"repr(\1)", s)
    s = s.replace("<>", "!=")
    s = re.sub(r"(?<![\w.])0([0-7]+)\b", r"0o\1", s)
    return s


PY2_PRELUDE = (
    "import functools as __ft__, builtins as __bi__, string as __st__\n"
    "reduce = __ft__.reduce\n"
    "def __py2_input__(*a):\n"
    "    return eval(__bi__.input(*a))\n"
    "map = lambda *a: list(__bi__.map(*a))\n"
    "filter = lambda *a: list(__bi__.filter(*a))\n"
    "zip = lambda *a: list(__bi__.zip(*a))\n"
    "__st__.letters = __st__.ascii_letters\n"
    "__st__.lowercase = __st__.ascii_lowercase\n"
    "__st__.uppercase = __st__.ascii_uppercase\n"
)


def prepare(src: str):
    """Return (code_object, variant) or (None, error_message)."""
    try:
        return _compile(src), "as_is"
    except (SyntaxError, ValueError) as exc:
        first_err = exc
    if any(k in str(first_err) for k in _WRAP_ERRORS):
        try:
            return _compile(_wrap(src)), "wrapped"
        except (SyntaxError, ValueError):
            pass
    conv = py2_to_py3(src)
    for candidate in (conv, _wrap(conv)):
        try:
            return _compile(PY2_PRELUDE + candidate), "py2"
        except (SyntaxError, ValueError):
            continue
    return None, str(first_err)[:200]
