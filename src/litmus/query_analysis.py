"""Query understanding: categorise a natural-language query and extract executable evidence.

A query that describes a programming task often embeds sample test cases
("Examples", "Sample Input / Sample Output", ...).  Those examples are the
strongest relevance signal we have for code, because they let us *verify* a
candidate snippet by running it instead of only comparing text.

This module is deliberately dependency-free and purely lexical so that it runs in
microseconds per query.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Section splitting
# --------------------------------------------------------------------------- #

# Problem statements (Codeforces, AtCoder, CodeChef, HackerRank, ...) delimit
# sections with lines such as "-----Sample Input 1-----" or "=====Example=====".
_HEADER_RE = re.compile(r"^[ \t]*(?:-{3,}|={3,})[ \t]*(.*?)[ \t]*(?:-{3,}|={3,})[ \t]*$", re.M)

# NB: in Russian statements "Входные данные" is the *format* section header, not a
# sample, so only explicit "Пример входных/выходных данных" headers count here.
_SAMPLE_IN_RE = re.compile(r"^(?:sample|example)\s*(?:test\s*)?input\b|^пример\s+входных", re.I)
_SAMPLE_OUT_RE = re.compile(r"^(?:sample|example)\s*(?:test\s*)?output\b|^пример\s+выходных", re.I)
_EXAMPLES_RE = re.compile(r"^(?:examples?|samples?|sample\s+tests?|примеры?|test\s+data)\b", re.I)

# Inside an "Examples" block the cases are introduced by bare marker lines.
_IN_MARKER_RE = re.compile(r"^\s*(?:input|sample input|входные данные)\s*(?:\d+)?\s*:?\s*$", re.I)
_OUT_MARKER_RE = re.compile(r"^\s*(?:output|sample output|выходные данные)\s*(?:\d+)?\s*:?\s*$", re.I)

# LeetCode-style "Example 1:\nInput: a = [1,2]\nOutput: 3" (function-call tasks).
_FUNC_EXAMPLE_RE = re.compile(r"^\s*Input\s*:\s*(.+?)\s*$\s*^\s*Output\s*:\s*(.+?)\s*$", re.M)

_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")


@dataclass
class Example:
    """One executable sample: stdin text and the expected stdout text."""

    input: str
    output: str


@dataclass
class QueryProfile:
    """Everything the pipeline learns about a query before retrieval."""

    text: str
    kind: str  # "task_with_examples" | "task_spec" | "function_task" | "question"
    language: str  # "en" | "ru" | ...
    platform: str  # heuristic origin, e.g. "codeforces-style"
    examples: list[Example] = field(default_factory=list)
    function_examples: int = 0
    sections: dict[str, str] = field(default_factory=dict)

    @property
    def verifiable(self) -> bool:
        return bool(self.examples)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "language": self.language,
            "platform": self.platform,
            "n_examples": len(self.examples),
            "n_function_examples": self.function_examples,
            "sections": sorted(self.sections),
            "verifiable": self.verifiable,
        }


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Return [(header, body), ...]; the preamble has header ''."""
    out: list[tuple[str, str]] = []
    pos, header = 0, ""
    for m in _HEADER_RE.finditer(text):
        out.append((header, text[pos : m.start()]))
        header, pos = m.group(1).strip().rstrip(":").strip(), m.end()
    out.append((header, text[pos:]))
    return out


def _clean_block(block: str, stop_at_blank: bool) -> str:
    lines = block.replace("\r\n", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if stop_at_blank:
        # AtCoder puts an explanation after the sample output, separated by a blank line.
        for i, ln in enumerate(lines):
            if not ln.strip():
                lines = lines[:i]
                break
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(ln.rstrip() for ln in lines)


def _parse_examples_block(body: str) -> list[Example]:
    """Parse the Codeforces/CodeChef style: Input\\n...\\nOutput\\n...\\n(Input ...)*"""
    lines = body.replace("\r\n", "\n").split("\n")
    examples: list[Example] = []
    mode, cur_in, cur_out = None, [], []

    def flush():
        if cur_in or cur_out:
            inp = _clean_block("\n".join(cur_in), stop_at_blank=False)
            out = _clean_block("\n".join(cur_out), stop_at_blank=True)
            if inp.strip() and out.strip():
                examples.append(Example(inp + "\n", out))

    for ln in lines:
        if _IN_MARKER_RE.match(ln):
            if mode == "out":
                flush()
                cur_in, cur_out = [], []
            mode = "in"
            continue
        if _OUT_MARKER_RE.match(ln):
            mode = "out"
            continue
        if mode == "in":
            cur_in.append(ln)
        elif mode == "out":
            cur_out.append(ln)
    if mode == "out":
        flush()
    return examples


def extract_examples(text: str) -> list[Example]:
    """Extract stdin/stdout sample tests from a problem statement."""
    sections = _split_sections(text)
    examples: list[Example] = []
    pending_input: str | None = None
    for header, body in sections:
        if _SAMPLE_IN_RE.match(header):
            pending_input = _clean_block(body, stop_at_blank=False)
        elif _SAMPLE_OUT_RE.match(header):
            if pending_input is not None and pending_input.strip():
                out = _clean_block(body, stop_at_blank=True)
                if out.strip():
                    examples.append(Example(pending_input + "\n", out))
            pending_input = None
        elif _EXAMPLES_RE.match(header):
            examples.extend(_parse_examples_block(body))
    # De-duplicate while preserving order.
    seen, uniq = set(), []
    for ex in examples:
        key = (ex.input, ex.output)
        if key not in seen:
            seen.add(key)
            uniq.append(ex)
    return uniq


def _platform(text: str, headers: set[str]) -> str:
    low = {h.lower() for h in headers}
    if any(h.startswith("problem statement") for h in low) and any("format" in h for h in low):
        return "hackerrank-style"
    if "sample input" in low or "constraints" in low:
        return "atcoder-style"
    if "subtasks" in low or "input:" in low or "example input" in low:
        return "codechef-style"
    if "examples" in low or "example" in low or "примеры" in low:
        return "codeforces-style"
    if re.search(r"^\s*class Solution", text, re.M) or _FUNC_EXAMPLE_RE.search(text):
        return "leetcode-style"
    return "free-text"


def analyze_query(text: str) -> QueryProfile:
    """Categorise a query and pull out anything we can execute."""
    sections = _split_sections(text)
    headers = {h for h, _ in sections if h}
    examples = extract_examples(text)
    func_examples = 0 if examples else len(_FUNC_EXAMPLE_RE.findall(text))
    cyr = len(_CYRILLIC_RE.findall(text))
    language = "ru" if cyr > 0.2 * max(1, len(re.findall(r"[A-Za-zЀ-ӿ]", text))) else "en"

    if examples:
        kind = "task_with_examples"
    elif func_examples:
        kind = "function_task"
    elif headers or len(text) > 400:
        kind = "task_spec"
    else:
        kind = "question"
    return QueryProfile(
        text=text,
        kind=kind,
        language=language,
        platform=_platform(text, headers),
        examples=examples,
        function_examples=func_examples,
        sections={h: b for h, b in sections if h},
    )
