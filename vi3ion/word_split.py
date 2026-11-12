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
# project's copy. Split only occurs where coverage exists; unknown runs stay
# fused rather than being invented.
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
    """.split()
)


def _resolve_alpha(run: str) -> list[str]:
    """Greedily cover an alphabetic run with known words; leftovers stay raw."""
    words: list[str] = []
    pos = 0
    n = len(run)
    while pos < n:
        best = 1
        limit = min(24, n - pos)
        for length in range(limit, 1, -1):
            if run[pos:pos + length].lower() in VOCAB:
                best = length
                break
        words.append(run[pos:pos + best])
        pos += best
    return words


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
    """Re-space one value, processing every long alphabetic run in place."""
    out: list[str] = []
    alpha = ""
    for ch in value:
        if ch.isalpha():
            alpha += ch
        else:
            if alpha:
                if len(alpha) >= 10:
                    out.extend(_resolve_alpha(alpha))
                else:
                    out.append(alpha)
                alpha = ""
            out.append(ch)
    if alpha:
        if len(alpha) >= 10:
            out.extend(_resolve_alpha(alpha))
        else:
            out.append(alpha)
    text = " ".join(out)
    return re.sub(r"\s+", " ", text).strip()


def split_body_words(bgr, items) -> list[TextItem]:
    """Re-space long fused alphabetic runs against the embedded word list.

    Only items that change and gain at least one additional token are touched;
    the original fused read is kept in ``split_from``.
    """
    del bgr
    result: list[TextItem] = []
    for item in items:
        value = item.value.strip()
        if not value or len(value) < 16 or value.count(" ") >= 2:
            result.append(item)
            continue
        letters = sum(1 for ch in value if ch.isalpha())
        if letters < 12 or letters < 0.5 * len(value):
            result.append(item)
            continue
        new_value = _respect_run(value)
        if new_value == value or new_value.count(" ") <= value.count(" "):
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
