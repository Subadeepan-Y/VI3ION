"""Image memory: identity signatures, similarity, and version diffs.

Keeps track of every analysed image (layout signature, OCR text fingerprint,
box count) so Vi3ion can:
- recognise that a new image is close to one already seen (label suggestion),
- diff two versions of the same screen (text/geometry changes).

Diff output is evidence, not verdicts: Vi3ion reports what changed as
observations, and the agent double-checks against the codebase.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any

# ---------------------------------------------------------------------------
# Signatures
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+")

GRID = 8  # 8x8 coarse layout grid
SIGNATURE_VERSION = 3  # v3 adds the perceptual hash (phash)


def _fingerprint(text: str) -> str:
    return _TOKEN_RE.sub("", str(text).lower())


def _get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _bbox(item: Any) -> tuple[float, float, float, float] | None:
    box = _get(item, "bbox")
    if box is None:
        return None
    if hasattr(box, "as_list"):
        box = box.as_list()
    elif isinstance(box, dict):
        box = [box.get(k) for k in ("x0", "y0", "x1", "y1")]
    try:
        values = [float(v) for v in box[:4]]
    except Exception:  # noqa: BLE001 - evidence may be partial
        return None
    if len(values) < 4:
        return None
    return tuple(round(v, 1) for v in values)  # type: ignore[return-value]


def _kind_name(item: Any) -> str:
    kind = _get(item, "kind", "")
    value = getattr(kind, "value", kind)
    return str(value).lower()


def signature_from_evidence(
    items: list[Any], width: int, height: int
) -> dict[str, Any]:
    """Deterministic layout/identity signature from analysis evidence.

    Accepts Evidence models or plain dicts. Only text evidence participates;
    each text item contributes its OCR fingerprint and box.
    """
    width = max(1, int(round(width)))
    height = max(1, int(round(height)))

    text_items: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[float, ...]]] = set()
    for item in items:
        if _kind_name(item) != "text":
            continue
        box = _bbox(item)
        if box is None:
            continue
        raw = str(_get(item, "label", "")).strip()
        text = _fingerprint(raw)[:80]
        if not text:
            continue
        key = (text, box)
        if key in seen:
            continue
        seen.add(key)
        text_items.append({"t": text, "raw": raw[:200], "b": box})

    text_items.sort(key=lambda x: (x["b"][1], x["b"][0], x["t"]))

    occupied: list[int] = []
    cells = [0] * (GRID * GRID)
    for item in text_items:
        x0, y0, x1, y1 = item["b"]
        cx = int(((x0 + x1) / 2) / width * GRID)
        cy = int(((y0 + y1) / 2) / height * GRID)
        index = min(GRID - 1, max(0, cy)) * GRID + min(GRID - 1, max(0, cx))
        cells[index] = 1
    for index, value in enumerate(cells):
        if value:
            occupied.append(index)

    layout_key = "".join(map(str, cells))
    text_key = "|".join(x["t"] for x in text_items)
    label_list = [x["raw"] for x in text_items]
    box_list = [list(x["b"]) for x in text_items]
    signature = hashlib.sha256(
        f"{width}x{height}::{layout_key}::{text_key}".encode()
    ).hexdigest()[:16]

    return {
        "version": SIGNATURE_VERSION,
        "width": width,
        "height": height,
        "layout_key": layout_key,
        "occupied_cells": occupied,
        "text_key": text_key,
        "text_count": len(text_items),
        "label_list": label_list,
        "box_list": box_list,
        "signature": signature,
    }


def layout_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Jaccard overlap of occupied layout cells (0..1)."""
    if not a or not b:
        return 0.0
    cells_a = set(a.get("occupied_cells") or [])
    cells_b = set(b.get("occupied_cells") or [])
    if not cells_a and not cells_b:
        return 0.0
    return len(cells_a & cells_b) / len(cells_a | cells_b)


def text_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Multiset overlap of OCR text fingerprints (0..1)."""
    tokens_a = [t for t in str(a.get("text_key", "")).split("|") if t]
    tokens_b = [t for t in str(b.get("text_key", "")).split("|") if t]
    if not tokens_a or not tokens_b:
        return 0.0
    counter_a, counter_b = Counter(tokens_a), Counter(tokens_b)
    overlap = sum((counter_a & counter_b).values())
    union = sum((counter_a | counter_b).values())
    return overlap / union if union else 0.0


def perceptual_hash_from_path(path: str) -> str:
    """64-bit difference hash of an image (16 hex chars).

    Catches "same screen, slightly different text" cases that an OCR
    fingerprint cannot. Returns "" when the image cannot be read.
    """
    try:
        import cv2
        import numpy as np
    except Exception:  # noqa: BLE001 - optional dependency
        return ""
    try:
        bgr = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if bgr is None:
            return ""
        small = cv2.resize(bgr, (9, 8), interpolation=cv2.INTER_AREA)
        bits = small[:, 1:] > small[:, :-1]
        value = 0
        for bit in np.asarray(bits).flatten():
            value = (value << 1) | int(bit)
        return f"{value:016x}"
    except Exception:  # noqa: BLE001
        return ""


def hamming_similarity(a: str, b: str) -> float:
    """Similarity of two perceptual hashes (1.0 = identical bits)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    try:
        distance = bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return 0.0
    bits = len(a) * 4  # hex chars -> bits
    return max(0.0, 1.0 - distance / bits)


def similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Combined identity similarity from layout, text and visual hash.

    Weights: layout 40%, text 40%, perceptual hash 20%. The hash keeps
    "same screen, different wording" pairs above the identity threshold.
    """
    layout = layout_similarity(a, b)
    text = text_similarity(a, b)
    phash = hamming_similarity(str(a.get("phash", "")), str(b.get("phash", "")))
    if not a.get("phash") or not b.get("phash"):
        return round(0.5 * layout + 0.5 * text, 3)
    return round(0.4 * layout + 0.4 * text + 0.2 * phash, 3)


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

@dataclass
class RegionDiff:
    kind: str  # added | removed | changed | moved
    region: str
    old: str = ""
    new: str = ""
    box_old: tuple | None = None
    box_new: tuple | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["box_old"] = list(self.box_old) if self.box_old else None
        data["box_new"] = list(self.box_new) if self.box_new else None
        return data


def _region_name(box: tuple | None, width: int, height: int) -> str:
    if not box or width <= 0 or height <= 0:
        return "unknown"
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    col = "left" if cx < width / 3 else ("right" if cx > 2 * width / 3 else "centre")
    row = "top" if cy < height / 3 else ("bottom" if cy > 2 * height / 3 else "middle")
    if row == "middle" and col == "centre":
        return "centre"
    return f"{row}-{col}"


def _items_from_sig(sig: dict[str, Any]) -> list[dict[str, Any]]:
    texts = [t for t in str(sig.get("text_key", "")).split("|") if t]
    labels = sig.get("label_list") or []
    boxes = sig.get("box_list") or []
    out: list[dict[str, Any]] = []
    for index, (text, box) in enumerate(zip(texts, boxes)):
        try:
            parsed = tuple(float(v) for v in box[:4])
        except Exception:  # noqa: BLE001
            continue
        raw = labels[index] if index < len(labels) and labels[index] else text
        out.append({"t": text, "label": str(raw), "b": parsed})
    return out


def _center(box: tuple) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _match_exact(
    old_items: list[dict[str, Any]], new_items: list[dict[str, Any]]
) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    """Greedily match identical text by nearest box, return pairs + leftovers."""
    remaining_new = list(new_items)
    pairs: list[tuple[dict, dict]] = []
    old_left: list[dict[str, Any]] = []
    for old in old_items:
        best_index = -1
        best_distance = float("inf")
        for index, new in enumerate(remaining_new):
            if new["t"] != old["t"]:
                continue
            old_cx, old_cy = _center(old["b"])
            new_cx, new_cy = _center(new["b"])
            distance = (old_cx - new_cx) ** 2 + (old_cy - new_cy) ** 2
            if distance < best_distance:
                best_distance = distance
                best_index = index
        if best_index >= 0:
            pairs.append((old, remaining_new.pop(best_index)))
        else:
            old_left.append(old)
    return pairs, old_left, remaining_new


def _similar_text(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _label(item: dict[str, Any]) -> str:
    return str(item.get("label") or item.get("t", ""))


def diff_images(older: dict[str, Any], newer: dict[str, Any]) -> dict[str, Any]:
    """Compare two image signatures -> structured observation list.

    Exact text is matched first (moved if the box center shifted). Leftovers
    are paired fuzzily into "changed" when the strings and positions are close;
    everything left becomes added/removed. This avoids reporting a typo fix as
    one addition plus one removal.
    """
    width = int(newer.get("width") or older.get("width") or 0)
    height = int(newer.get("height") or older.get("height") or 0)

    old_items = _items_from_sig(older)
    new_items = _items_from_sig(newer)

    pairs, old_left, new_left = _match_exact(old_items, new_items)

    changes: list[RegionDiff] = []
    for old, new in pairs:
        old_cx, old_cy = _center(old["b"])
        new_cx, new_cy = _center(new["b"])
        dx = abs(new_cx - old_cx)
        dy = abs(new_cy - old_cy)
        if dx >= 12 or dy >= 12:
            changes.append(
                RegionDiff(
                    kind="moved",
                    region=_region_name(new["b"], width, height),
                    old=_label(old),
                    new=_label(new),
                    box_old=old["b"],
                    box_new=new["b"],
                    detail=f"center shifted dx={dx:.0f} dy={dy:.0f}",
                )
            )

    # Fuzzy pairing for text edits: same element, edited label. Strings that
    # sit at nearly the same position are treated as a replacement even when
    # the wording is completely different (e.g. "System" -> "Custom").
    used_new: set[int] = set()
    still_old: list[dict[str, Any]] = []
    max_shift = max(120.0, 0.2 * max(width, height))
    for old in old_left:
        best_index = -1
        best_score = 0.0
        best_ratio = 0.0
        for index, new in enumerate(new_left):
            if index in used_new:
                continue
            ratio = _similar_text(old["t"], new["t"])
            old_cx, old_cy = _center(old["b"])
            new_cx, new_cy = _center(new["b"])
            shift = max(abs(new_cx - old_cx), abs(new_cy - old_cy))
            if shift > max_shift:
                continue
            near = shift <= 24 and len(old["t"]) <= 24 and len(new["t"]) <= 24
            if ratio < 0.7 and not near:
                continue
            score = ratio + (0.25 if near else 0.0)
            if score > best_score:
                best_score = score
                best_ratio = ratio
                best_index = index
        if best_index >= 0:
            new = new_left[best_index]
            used_new.add(best_index)
            detail = (
                f"text similarity {best_ratio:.2f}"
                if best_ratio >= 0.7
                else "label replaced at the same position"
            )
            changes.append(
                RegionDiff(
                    kind="changed",
                    region=_region_name(new["b"], width, height),
                    old=_label(old),
                    new=_label(new),
                    box_old=old["b"],
                    box_new=new["b"],
                    detail=detail,
                )
            )
        else:
            still_old.append(old)

    for old in still_old:
        changes.append(
            RegionDiff(
                kind="removed",
                region=_region_name(old["b"], width, height),
                old=_label(old),
                box_old=old["b"],
            )
        )
    for index, new in enumerate(new_left):
        if index in used_new:
            continue
        changes.append(
            RegionDiff(
                kind="added",
                region=_region_name(new["b"], width, height),
                new=_label(new),
                box_new=new["b"],
            )
        )

    order = {"changed": 0, "added": 1, "removed": 2, "moved": 3}
    changes.sort(
        key=lambda c: (
            order.get(c.kind, 9),
            (c.box_new or c.box_old or (0, 0, 0, 0))[1],
            (c.box_new or c.box_old or (0, 0, 0, 0))[0],
        )
    )

    counts = Counter(c.kind for c in changes)
    combined = similarity(older, newer)
    return {
        "overall_similarity": combined,
        "layout_similarity": round(layout_similarity(older, newer), 3),
        "text_similarity": round(text_similarity(older, newer), 3),
        "same_size": bool(
            older.get("width") == newer.get("width")
            and older.get("height") == newer.get("height")
        ),
        "change_count": len(changes),
        "counts": {
            "added": counts.get("added", 0),
            "removed": counts.get("removed", 0),
            "changed": counts.get("changed", 0),
            "moved": counts.get("moved", 0),
        },
        "changes": [c.to_dict() for c in changes],
    }


def signature_json(sig: dict[str, Any]) -> str:
    """Stable JSON encoding for storage."""
    return json.dumps(sig, separators=(",", ":"), ensure_ascii=False, default=list)


def parse_signature(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(data, dict):
        return {}
    data["box_list"] = [list(b) for b in data.get("box_list", [])]
    return data
