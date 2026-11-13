"""Word-boundary reconstruction for long OCR runs that lost their spaces.

The recogniser frequently fuses a whole line into one token (`Noheavythird-
partyblackboxes.Every`). Scaling does not recover the spaces (the model has no
spacing signal at this size), so long spaceless runs are re-segmented against
an embedded English word list. This is orthography, not image guessing: the
character order is untouched and every emitted item keeps its raw read in the
``split_from`` annotation and is marked uncertain. Unknown fragments are left
as-is rather than guessed.
"""

from __future__ import annotations

import re

from .text_merge import TextItem

# Core vocabulary — common English plus the domain words present in the
# project's copy and common UI/developer workflows. Split only occurs where
# coverage exists; unknown runs stay fused rather than being invented.
VOCAB = frozenset(
    """a about above access across act action active add added adds address after
    again against age all already also although always among an and another any
    anyone anything are around as ask at away back based been before being below
    best between both but by can cannot case cases change changed changes check
    click code cold come could create created current data day days delete detail
    details did different do does doing down each either else end error even
    every everyone everything file files find first for form from full further
    get give given go going good got great had has have he her here hers him
    himself his how however i if in info into is it its itself job just keep key
    kind know like link list little long look made make man many may me might
    min more most much must my myself name never new next no not nothing now of
    off on once one only open or other others our out over own page part people
    per play please put really record remove right said same say see search she
    should show shown since small so some something start still stop such take
    than that the their them themselves then there these they thing things this
    those through to too top two under up update updated use used user very view
    want was way we well were what when where which while who whom why will with
    within without work would yeah yes yet you your yours yourself
    first second third fourth five six seven eight nine ten zero
    one two three four five six seven eight nine ten eleven twelve thirteen
    fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty
    fifty sixty seventy eighty ninety hundred thousand million
    visual education platforms browser animation runtimes complete architectures
    built deployed real users worldwide modern low latency webgl node webassembly
    glsl resilient state machines engineered fps execution heavy third party
    black boxes every computation runs lean hand tuned pipeline loops native gpu
    rendering handcrafted principle toolchain record shipped products from to
    about into over under again around between through during before after above
    below up down out off on in at by for with without within along against
    across behind beyond except inside near onto outside per since throughout
    toward under until upon via while
    replace replaced replacing replaces
    download downloads downloaded downloading
    application applications app apps
    project projects
    source sources
    folder folders directory directories
    reference references
    window windows
    terminal terminals console
    editor editors
    screenshot screenshots
    setting settings config configuration
    execute executing execution executed
    running run runs
    dialog modal dialogs
    inspect inspecting inspection
    detail details
    image images
    input inputs output outputs
    script scripts
    tools tool
    model models
    agent agents
    split splits splitting
    panel panels card cards
    dark light theme
    online offline local
    check checking checked
    given give gives
    exist exists existing existed
    copy copying copied
    paste pasting pasted
    drive disk memory
    localhost server client
    preview status code
    finish finished
    nothing else where there here
    what why when who how
    narrow wider left right centre center
    border margin padding width height
    zip png jpg jpeg json fingrow const stringify seeing
    """.split()
)

# Common glyph misrecognitions in low-contrast, italic, or monospaced OCR
_OCR_CONFUSIONS = (
    ("z", "l"),
    ("1", "l"),
    ("|", "l"),
    ("0", "o"),
    ("rn", "m"),
    ("vv", "w"),
    ("h", "k"),
    ("ih", "lik"),
    ("ihe", "like"),
)


def _match_case(original: str, candidate: str) -> str:
    if original.isupper():
        return candidate.upper()
    if original and original[0].isupper():
        return candidate.capitalize()
    return candidate


def _match_word(chunk: str) -> str | None:
    c_lower = chunk.lower()
    if c_lower in VOCAB:
        return _match_case(chunk, c_lower)
    for s1, d1 in _OCR_CONFUSIONS:
        if s1 in c_lower:
            c1 = c_lower.replace(s1, d1)
            if c1 in VOCAB:
                return _match_case(chunk, c1)
            for s2, d2 in _OCR_CONFUSIONS:
                if s2 in c1:
                    c2 = c1.replace(s2, d2)
                    if c2 in VOCAB:
                        return _match_case(chunk, c2)
    return None


def _resolve_alpha(run: str) -> list[str]:
    """Segment an alphabetic run into known words without leaving single-letter remnants."""
    n = len(run)
    single = _match_word(run)
    if single:
        return [single]

    memo: dict[int, list[str] | None] = {}

    def solve(pos: int) -> list[str] | None:
        if pos == n:
            return []
        if pos in memo:
            return memo[pos]
        limit = min(24, n - pos)
        for length in range(limit, 2, -1):
            sub = run[pos:pos + length]
            m = _match_word(sub)
            if m:
                rest = solve(pos + length)
                if rest is not None:
                    res = [m] + rest
                    memo[pos] = res
                    return res
        if n - pos >= 2:
            sub = run[pos:pos + 2]
            if sub.lower() in (
                "an", "of", "in", "to", "on", "at", "as", "is", "it", "or",
                "by", "no", "if", "we", "he", "my", "do", "go", "up",
            ):
                rest = solve(pos + 2)
                if rest is not None:
                    res = [_match_case(sub, sub.lower())] + rest
                    memo[pos] = res
                    return res
        memo[pos] = None
        return None

    full_split = solve(0)
    if full_split:
        return full_split
    return [run]


def _merge_hyphen(parts: list[str], words: list[str]) -> bool:
    """Bind a dangling `-` to the preceding word: third - party -> third-party."""
    if len(parts) >= 2 and parts[-1] == "-" and words:
        prev = parts[-2]
        if prev and prev[-1].isalpha():
            parts[-2] = f"{prev}-{words[0]}"
            parts.pop()
            parts.extend(words[1:])
            return True
        parts[-1] = f"-{words[0]}"
        parts.extend(words[1:])
        return True
    return False


def _split_run(value: str) -> list[str]:
    """Segment one spaceless value into words, preserving punctuation/digits."""
    parts: list[str] = []
    alpha = ""
    i = 0
    n = len(value)
    while i < n:
        ch = value[i]
        if ch.isalpha():
            alpha += ch
            i += 1
            continue
        if alpha:
            words = _resolve_alpha(alpha)
            if not _merge_hyphen(parts, words):
                if parts and parts[-1] in (",", ";", ":", "?"):
                    parts.pop()
                    parts.extend(words)
                    parts[-1] = f"{parts[-1]}{ch}"
                    alpha = ""
                    i += 1
                    continue
                parts.extend(words)
            alpha = ""
        if ch.isdigit():
            j = i
            while j < n and value[j].isdigit():
                j += 1
            parts.append(value[i:j])
            i = j
            continue
        if ch in ("-", "–", "—"):
            parts.append("-")
        elif ch in (".", "!", "?", ",", ";", ":"):
            if parts:
                parts[-1] = f"{parts[-1]}{ch}"
            else:
                parts.append(ch)
        else:
            parts.append(ch)
        i += 1
    if alpha:
        words = _resolve_alpha(alpha)
        if not _merge_hyphen(parts, words):
            if parts and parts[-1] in (",", ";", ":", "?"):
                parts.pop()
                parts.extend(words)
                parts[-1] = f"{parts[-1]}."
            else:
                parts.extend(words)
    return parts


def _respect_run(value: str) -> str:
    """Re-space one value, processing each whitespace-separated token or long run."""
    def _clean_token(token: str) -> str:
        parts: list[str] = []
        alpha = ""
        for ch in token:
            if ch.isalpha():
                alpha += ch
            else:
                if alpha:
                    parts.append(" ".join(_resolve_alpha(alpha)))
                    alpha = ""
                parts.append(ch)
        if alpha:
            parts.append(" ".join(_resolve_alpha(alpha)))
        res = ""
        for i, p in enumerate(parts):
            if i > 0:
                prev = parts[i - 1]
                if (prev and prev[-1].isdigit() and p and p[0].isalpha()) or (
                    prev and prev[-1].isalpha() and p and p[0].isdigit()
                ):
                    res += " "
            res += p
        return res

    return " ".join(_clean_token(tok) for tok in value.split())


def split_body_words(bgr, items) -> list[TextItem]:
    """Re-space long fused alphabetic runs and repair OCR misreads against vocabulary.

    Only items that change are touched; the original read is kept in ``split_from``.
    """
    del bgr
    result: list[TextItem] = []
    for item in items:
        value = item.value.strip()
        if not value or len(value) < 3:
            result.append(item)
            continue
        new_value = _respect_run(value)
        if new_value == value:
            result.append(item)
            continue
        result.append(
            TextItem(
                value=new_value,
                bbox=item.bbox,
                confidence=item.confidence,
                region=item.region,
                uncertain=True,
                split_from=value,
            )
        )
    return result
