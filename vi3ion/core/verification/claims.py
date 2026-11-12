"""Deterministic claim parsing.

Only claims with measurable or directly checkable content are accepted here.
Everything else is deliberately returned as inconclusive by the verifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SUPPORTED_INTENTS = (
    "alignment",
    "distance",
    "color",
    "size",
    "containment",
    "overlap",
    "text_present",
    "dimensions",
    "existence",
    "unsupported",
)

COLOR_WORDS = {
    "black", "near-black", "charcoal", "gray", "grey", "silver", "light-gray",
    "off-white", "white", "red", "crimson", "pink", "orange", "amber", "yellow",
    "lime", "green", "emerald", "teal", "cyan", "sky", "blue", "navy", "indigo",
    "violet", "purple", "magenta", "brown", "beige", "olive", "mint", "dark", "light",
}

ORDINAL_WORDS = {
    "first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2,
    "fourth": 3, "4th": 3, "fifth": 4, "5th": 4, "sixth": 5, "6th": 5,
    "seventh": 6, "7th": 6, "eighth": 7, "8th": 7, "ninth": 8, "9th": 8,
    "tenth": 9, "10th": 9, "last": -1,
}


@dataclass
class ParsedClaim:
    intent: str
    raw: str
    subject: str | None = None
    object: str | None = None
    attribute: str | None = None
    value: float | None = None
    unit: str | None = None
    text: str | None = None
    color: str | None = None
    comparison: str | None = None
    direction: str | None = None
    width: int | None = None
    height: int | None = None


def clean_reference(value: str) -> str:
    text = value.strip().strip("\"'").strip()
    text = re.sub(r"^(?:the|a|an)\s+", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"^(?:text|label|word|words|title)\s+", "", text, flags=re.IGNORECASE).strip()
    text = text.strip("\"'").strip()
    text = text.rstrip("?.!").strip()
    return text


def _colour_claim(text: str) -> ParsedClaim | None:
    """Parse "<element> is <colour>" when the last word really is a colour."""
    match = re.match(
        r"^(?P<a>.+?)\s+(?:is|are|appears?|looks?)\s+(?P<color>[a-zA-Z#0-9\-]+)[.?!]?$",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    color = match.group("color").lower()
    if color in COLOR_WORDS or re.fullmatch(r"#[0-9a-f]{6}", color):
        return ParsedClaim(
            intent="color", raw=text,
            subject=clean_reference(match.group("a")), color=color,
        )
    return None


def ordinal_reference(value: str) -> tuple[int | None, str]:
    match = re.match(
        r"^(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|last|\d+(?:st|nd|rd|th))\s+(.+)$",
        value.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return None, value.strip()
    ordinal = ORDINAL_WORDS.get(match.group(1).lower())
    return ordinal, match.group(2).strip()


def parse_claim(claim: str | dict[str, Any]) -> ParsedClaim:
    if isinstance(claim, dict):
        return _parse_dict(claim)
    text = " ".join(claim.strip().split())
    if not text:
        return ParsedClaim(intent="unsupported", raw="")

    # Colour is checked first: "the text 'Save' is white" is a colour claim
    # about an element, not a text-presence claim.
    colour_claim = _colour_claim(text)
    if colour_claim is not None:
        return colour_claim

    # Text presence -------------------------------------------------------
    patterns_text = [
        r"(?:contains?|shows?|has|includes?)\s+(?:the\s+)?(?:text|label|word|words)\s+[\"'](?P<text>.+?)[\"']",
        r"(?:the\s+)?text\s+[\"'](?P<text>.+?)[\"']\s+(?:is|appears|exists|present|visible)",
        r"(?:reads?|says?)\s+[\"'](?P<text>.+?)[\"']",
        r"(?:contains?|shows?)\s+[\"'](?P<text>.+?)[\"']",
    ]
    for pattern in patterns_text:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return ParsedClaim(intent="text_present", raw=text, text=match.group("text"))

    # Dimensions ----------------------------------------------------------
    match = re.search(
        r"(?:image|screenshot|picture)\s+(?:is|has|measures)\s+(\d{2,5})\s*[x×]\s*(\d{2,5})",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return ParsedClaim(
            intent="dimensions", raw=text,
            width=int(match.group(1)), height=int(match.group(2)),
        )

    # Alignment -----------------------------------------------------------
    match = re.match(
        r"^(?P<a>.+?)\s+(?:is|are)\s+(?:(?P<orientation>vertically|horizontally)\s+)?aligned\s+(?:with|to)\s+(?P<b>.+?)[.?!]?$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        orientation = (match.group("orientation") or "").lower()
        attribute = {"vertically": "center_x", "horizontally": "center_y"}.get(orientation)
        return ParsedClaim(
            intent="alignment", raw=text,
            subject=clean_reference(match.group("a")),
            object=clean_reference(match.group("b")),
            attribute=attribute,
        )
    match = re.match(
        r"^(?P<a>.+?)\s+and\s+(?P<b>.+?)\s+(?:are\s+)?(?:(?P<edge>left|right|top|bottom|center)[- ])?aligned[.?!]?$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return ParsedClaim(
            intent="alignment", raw=text,
            subject=clean_reference(match.group("a")),
            object=clean_reference(match.group("b")),
            attribute=match.group("edge"),
        )
    match = re.match(
        r"^(?P<a>.+?)\s+(?:shares?|have|has)\s+the\s+same\s+(?P<edge>left|right|top|bottom|center)\s+edge",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return ParsedClaim(
            intent="alignment", raw=text,
            subject=clean_reference(match.group("a")),
            object=clean_reference(match.group("b")) if "b" in match.groupdict() else None,
            attribute=match.group("edge"),
        )

    # Distance ------------------------------------------------------------
    match = re.match(
        r"^(?P<a>.+?)\s+(?:is|are)\s+(?P<dist>\d+(?:\.\d+)?)\s*(?:px|pixels?)\s+"
        r"(?P<direction>to the right of|to the left of|right of|left of|above|below|higher than|lower than)\s+"
        r"(?P<b>.+?)[.?!]?$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return ParsedClaim(
            intent="distance", raw=text,
            subject=clean_reference(match.group("a")),
            object=clean_reference(match.group("b")),
            value=float(match.group("dist")), unit="px",
            direction=match.group("direction").lower(),
        )

    # Size ----------------------------------------------------------------
    match = re.match(
        r"^(?P<a>.+?)\s+(?:is|are)\s+(?P<comparison>wider|narrower|taller|shorter|larger|smaller|bigger)\s+than\s+(?P<b>.+?)[.?!]?$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return ParsedClaim(
            intent="size", raw=text,
            subject=clean_reference(match.group("a")),
            object=clean_reference(match.group("b")),
            comparison=match.group("comparison").lower(),
        )

    # Containment / overlap ----------------------------------------------
    match = re.match(
        r"^(?P<a>.+?)\s+(?:is|are)\s+(?:inside|within|contained\s+(?:in|within))\s+(?P<b>.+?)[.?!]?$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return ParsedClaim(
            intent="containment", raw=text,
            subject=clean_reference(match.group("a")),
            object=clean_reference(match.group("b")),
        )
    match = re.match(
        r"^(?P<a>.+?)\s+overlaps?\s+(?P<b>.+?)[.?!]?$", text, flags=re.IGNORECASE
    )
    if match:
        return ParsedClaim(
            intent="overlap", raw=text,
            subject=clean_reference(match.group("a")),
            object=clean_reference(match.group("b")),
        )

    # Colour --------------------------------------------------------------
    colour_claim = _colour_claim(text)
    if colour_claim is not None:
        return colour_claim

    # Existence -----------------------------------------------------------
    match = re.match(
        r"^(?:there\s+(?:is|are)\s+)?(?:a|an|the)?\s*(?P<a>.+?)\s+(?:is|are)?\s*(?:present|visible|shown)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return ParsedClaim(intent="existence", raw=text, subject=clean_reference(match.group("a")))

    return ParsedClaim(intent="unsupported", raw=text)


def _parse_dict(claim: dict[str, Any]) -> ParsedClaim:
    intent = str(claim.get("type") or claim.get("intent") or "unsupported").lower()
    aliases = {
        "text": "text_present",
        "text_contains": "text_present",
        "aligned": "alignment",
        "position": "distance",
        "contained": "containment",
        "contains": "containment",
        "overlaps": "overlap",
    }
    intent = aliases.get(intent, intent)
    if intent not in SUPPORTED_INTENTS:
        intent = "unsupported"
    raw = str(claim.get("claim") or claim.get("description") or f"{intent} claim")
    value = claim.get("expected_px", claim.get("pixels", claim.get("value")))
    return ParsedClaim(
        intent=intent,
        raw=raw,
        subject=_optional_ref(claim.get("subject")),
        object=_optional_ref(claim.get("object")),
        attribute=claim.get("edge") or claim.get("axis") or claim.get("attribute"),
        value=float(value) if value is not None else None,
        unit=claim.get("unit", "px"),
        text=claim.get("text"),
        color=str(claim["color"]).lower() if claim.get("color") else None,
        comparison=str(claim["comparison"]).lower() if claim.get("comparison") else None,
        direction=claim.get("direction"),
        width=int(claim["width"]) if claim.get("width") else None,
        height=int(claim["height"]) if claim.get("height") else None,
    )


def _optional_ref(value: Any) -> str | None:
    return clean_reference(str(value)) if value is not None else None
