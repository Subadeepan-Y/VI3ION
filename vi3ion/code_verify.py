"""Cross-check OCR candidates against the user's codebase.

A vision-less agent already knows languages, conventions and the project it is
working in. When Vi3ion surfaces an uncertain reading, the agent can verify it
against source files: a text that literally appears in the code (a UI string,
a label, a report title) is far more likely to be what the image shows.

This module builds a small offline index of string literals and text lines from
the configured roots. It never edits anything — it only reports matches with
file/line/snippet so the agent can decide.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("vi3ion.code_verify")

SOURCE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".htm", ".css", ".scss",
    ".md", ".json", ".yaml", ".yml", ".txt", ".vue", ".svelte", ".ipynb",
}
SKIP_DIRS = {
    ".venv", "venv", "node_modules", "dist", "build", ".git", "__pycache__",
    ".pytest_cache", ".idea", "data", ".cache",
}
LITERAL_RE = re.compile(r"""(['"`])(?:(?!\1).)*\1""")
MAX_SNIPPET = 300


@dataclass
class CodeMatch:
    file: str
    line: int
    snippet: str
    score: float = 0.0


@dataclass
class CodeIndex:
    roots: tuple[str, ...] = ()
    entries: list[tuple[str, int, str]] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.entries)


def iter_source_files(roots: list[Path]):
    for root in roots:
        root = root.expanduser().resolve()
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() not in SOURCE_EXTS:
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    continue
            except OSError:
                continue
            yield path


def _line_literals(text: str, ext: str) -> list[str]:
    if ext in (".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte"):
        return [m.group(0).strip("'\"`") for m in LITERAL_RE.finditer(text)]
    if ext == ".json":
        return [m.group(0).strip('"') for m in LITERAL_RE.finditer(text)]
    # markup / docs / config: every meaningful trimmed line is a candidate
    stripped = text.strip()
    if 3 <= len(stripped) <= MAX_SNIPPET:
        return [stripped]
    return []


def build_index(roots: list[Path]) -> CodeIndex:
    entries: list[tuple[str, int, str]] = []
    for path in iter_source_files(roots):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            for literal in _line_literals(line.strip(), path.suffix.lower()):
                entries.append((path.name, lineno, literal))
    return CodeIndex(roots=tuple(str(r) for r in roots), entries=entries)


def _normalize(text: str) -> str:
    return re.sub(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+", " ", text.lower()).strip()


def find_code_matches(
    query: str, index: CodeIndex, limit: int = 5
) -> list[CodeMatch]:
    q = _normalize(query)
    if not q or not index:
        return []
    q_words = set(q.split())
    results: list[CodeMatch] = []
    for file, lineno, literal in index.entries:
        lit = _normalize(literal)
        if not lit:
            continue
        if q in lit or lit in q:
            score = 1.0
        else:
            lit_words = set(lit.split())
            if not lit_words:
                continue
            score = len(q_words & lit_words) / len(q_words)
        if score < 0.75:
            continue
        results.append(CodeMatch(file=file, line=lineno, snippet=literal, score=score))
    results.sort(key=lambda m: (-m.score, m.file, m.line))
    return results[:limit]


_INDEX = None
_INDEX_LOCK = threading.Lock()
_INDEX_ROOTS: tuple[str, ...] = ()


def hint_terms(context: str) -> list[str]:
    """Terms worth matching: quoted phrases, path-like tokens, single words."""
    terms: list[str] = []
    for quoted in re.findall(r"[\"']([^\"']{4,80})[\"']", context):
        terms.append(quoted.strip())
    for token in re.findall(r"[A-Za-z0-9_./\\-]{4,80}", context):
        token = token.strip()
        if token and token not in terms:
            terms.append(token)
    return terms


def context_code_matches(context: str, index: CodeIndex, limit: int = 8) -> list[CodeMatch]:
    """Ranked code matches for a user message (whole text + quoted phrases)."""
    if not context or not index:
        return []
    seen: set[tuple[str, int]] = set()
    results: list[CodeMatch] = []
    queries = [context] + hint_terms(context)
    for query in queries:
        for m in find_code_matches(query, index, limit=4):
            key = (m.file, m.line)
            if key in seen:
                continue
            seen.add(key)
            results.append(m)
    results.sort(key=lambda m: (-m.score, m.file, m.line))
    return results[:limit]


def get_code_index(roots: list[Path]) -> CodeIndex:
    """Lazy cached index for a given roots set; rebuilt when roots change."""
    global _INDEX, _INDEX_ROOTS
    key = tuple(str(r) for r in roots)
    if _INDEX is not None and _INDEX_ROOTS == key:
        return _INDEX
    with _INDEX_LOCK:
        if _INDEX is None or _INDEX_ROOTS != key:
            _INDEX = build_index(roots)
            _INDEX_ROOTS = key
            logger.debug("code index built: %d entries", len(_INDEX.entries))
    return _INDEX
