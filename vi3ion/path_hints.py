"""Extract navigation hints (file-path-like candidates) from OCR text.

Dialog and console screenshots frequently show file paths that OCR garbles:
letters spaced out, drive letters split, mixed slashes. A vision-less agent
can navigate straight to the failing file when these are surfaced as
candidates. Everything here is evidence, never correction: candidates are
marked uncertain and deduplicated, never asserted as ground truth.
"""

from __future__ import annotations

import re

# A run of single letters separated by single spaces: `o p e n c o d e`.
_SPACED_LETTER_RUN = re.compile(r"\b(?:[A-Za-z] ){2,}[A-Za-z]\b")
_DRIVE_SPLIT = re.compile(r"\b([A-Za-z]) : [\\/]")
_PATH_WITH_DRIVE = re.compile(r"[A-Za-z]:[\\/][A-Za-z0-9_\-\\/ .()]{3,}")
_DOTTED_FILE = re.compile(r"[A-Za-z0-9_\-]{3,}\.(?:json|jsonc|tsx?|jsx?|py|md|yaml|yml|toml|cfg|ini|log|txt|env)")
_SLASH_PATH = re.compile(r"(?:[\\/][A-Za-z0-9_\- .]+){2,}")
_WHITESPACE = re.compile(r"\s+")


def _compact_spaced_letters(text: str) -> str:
    """Collapse `o p e n c o d e` -> `opencode` (single-letter spaced runs)."""
    def _fold(match: re.Match) -> str:
        return _WHITESPACE.sub("", match.group(0))
    return _SPACED_LETTER_RUN.sub(_fold, text)


def _fix_drive_split(text: str) -> str:
    return _DRIVE_SPLIT.sub(r"\1:\\", text)


def _normalise_slashes(text: str) -> str:
    return text.replace("\\", "/")


def _clean(candidate: str) -> str:
    c = candidate.strip(" .()[]\"'")
    return _WHITESPACE.sub(" ", c)


_KNOWN_EXT = (
    "jsonc", "json", "tsx", "ts", "jsx", "js", "py", "md",
    "yaml", "yml", "toml", "cfg", "ini", "log", "txt", "env",
)


def _extend_dotted(candidate: str) -> list[str]:
    """Append a dotted variant when OCR dropped the dot before an extension.

    `opencodejson` -> `opencode.json`; `app.tsx` stays as-is. Only applied to
    the pure-suffix case so words like `repositories` are never split.
    """
    base = candidate.rstrip(".")
    for ext in _KNOWN_EXT:
        if base.lower().endswith(ext) and not base.lower().endswith("." + ext):
            prefix = base[: -len(ext)]
            if prefix:
                return [candidate, f"{prefix}.{ext}"]
    return [candidate]


def path_candidates(texts, limit: int = 10) -> list[str]:
    """Return plausible file-path candidates found in OCR line texts.

    Candidates come from three patterns once spaced-letter runs and drive
    splits are repaired: absolute Windows paths, dotted file names, and
    slash-separated paths. Output is deduplicated, case-preserving, sorted by
    length (shortest first), capped by ``limit``.
    """
    joined = "\n".join(t or "" for t in texts)
    repaired = _fix_drive_split(_compact_spaced_letters(joined))
    seen: set[str] = set()
    candidates: list[str] = []
    for pattern in (_PATH_WITH_DRIVE, _DOTTED_FILE, _SLASH_PATH):
        for match in pattern.finditer(repaired):
            raw = _clean(match.group(0))
            if len(raw) < 4:
                continue
            for variant in _extend_dotted(raw):
                key = variant.lower().replace("/", "\\")
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(variant)
    candidates.sort(key=len)
    return candidates[:limit]
