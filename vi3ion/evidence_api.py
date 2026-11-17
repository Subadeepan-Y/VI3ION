"""Traceable, question-focused evidence APIs.

These helpers work on an existing ``ToolResponse`` — they never re-run OCR.
They turn measured evidence into:

- a compact answer to *which evidence matters for this question*,
- a graph with stable IDs, provenance and explicit uncertainty,
- a false-confidence audit against ground truth.

Everything here is deterministic and offline. Unknowns stay unknown.
"""

from __future__ import annotations

import re
from typing import Any

from .evaluate import is_supported
from .schemas.common import Evidence

_UNCERTAIN_ATTRS = (
    "uncertain", "possibly", "missing", "split_from", "note_unread",
)
_STOPWORDS = {
    "a", "an", "and", "are", "do", "does", "for", "how", "i", "in", "is",
    "it", "me", "of", "on", "show", "tell", "the", "to", "what", "where",
    "which", "with", "you", "your",
}
_KIND_HINTS = {
    "colour": {"color"},
    "color": {"color"},
    "background": {"color"},
    "where": {"text", "shape"},
    "position": {"text", "shape"},
    "align": {"text", "shape"},
    "read": {"text"},
    "text": {"text"},
    "write": {"text"},
    "shape": {"shape"},
    "circle": {"shape"},
    "compare": {"text", "shape", "color"},
    "change": {"text", "shape", "color"},
}


def is_uncertain(item: Evidence) -> bool:
    """True when an item must not be treated as a confident measurement."""
    if item.observed is False:
        return True
    if item.confidence is not None and item.confidence < 0.5:
        return True
    if any(key in item.attributes for key in _UNCERTAIN_ATTRS):
        return True
    label = str(item.label).lower()
    return "uncertain" in label or "(possibly" in label or "not read" in label


def evidence_node(item: Evidence) -> dict[str, Any]:
    """One traceable evidence node with a stable ID and explicit uncertainty."""
    attrs = item.attributes or {}
    source = attrs.get("source") or {}
    return {
        "id": item.evidence_id,
        "kind": item.kind.value if hasattr(item.kind, "value") else str(item.kind),
        "label": item.label,
        "bbox": item.bbox.as_rounded() if item.bbox is not None else None,
        "confidence": round(item.confidence, 3) if item.confidence is not None else None,
        "observed": item.observed,
        "uncertain": is_uncertain(item),
        "attributes": {
            key: attrs[key]
            for key in ("width", "height", "ink_hex", "ink_name", "bg_hex", "fill_ratio")
            if key in attrs
        },
        "provenance": {
            "module": item.provenance.module,
            "method": item.provenance.method,
            "params": item.provenance.params,
            "image_id": item.image_id,
            "source_image": source.get("uri") or source.get("path") or item.image_id,
        },
    }


def _boxes_overlap(a: list[float], b: list[float]) -> bool:
    y_overlap = min(a[3], b[3]) - max(a[1], b[1])
    if y_overlap <= 0:
        return False
    height = min(a[3] - a[1], b[3] - b[1])
    return height > 0 and y_overlap / height > 0.5


def _inside(a: list[float], b: list[float]) -> bool:
    return (
        b[0] >= a[0] and b[1] >= a[1] and b[2] <= a[2] and b[3] <= a[3]
    )


def evidence_graph(response: Any, max_nodes: int = 40) -> dict[str, Any]:
    """Build a small, referenceable graph from a tool response."""
    items = list(response.evidence or [])
    priority = {"text": 0, "shape": 1, "color": 2, "image": 3, "note": 4}
    items.sort(
        key=lambda e: (
            priority.get(
                e.kind.value if hasattr(e.kind, "value") else str(e.kind), 9
            ),
            -(e.confidence or 0.0),
        )
    )
    items = items[:max_nodes]
    nodes = [evidence_node(item) for item in items]
    relations: list[dict[str, str]] = []
    for i, left in enumerate(nodes):
        for right in nodes[i + 1:]:
            if not left["bbox"] or not right["bbox"]:
                continue
            if _inside(left["bbox"], right["bbox"]):
                relations.append({"from": left["id"], "to": right["id"], "type": "inside"})
            elif _inside(right["bbox"], left["bbox"]):
                relations.append({"from": right["id"], "to": left["id"], "type": "inside"})
            elif _boxes_overlap(left["bbox"], right["bbox"]):
                relations.append({"from": left["id"], "to": right["id"], "type": "same_row"})
    return {
        "ok": True,
        "tool": "evidence_graph",
        "image_id": response.image_id,
        "nodes": nodes,
        "relationships": relations[:120],
        "uncertain_ids": [node["id"] for node in nodes if node["uncertain"]],
        "canvas": next(
            (
                {
                    "width": node.get("attributes", {}).get("width"),
                    "height": node.get("attributes", {}).get("height"),
                }
                for node in nodes
                if node["kind"] == "image"
            ),
            None,
        ),
    }


def _tokens(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9\u3040-\u9fff]+", str(text).lower())
        if token not in _STOPWORDS and len(token) > 1
    }


def focus_evidence(response: Any, question: str, limit: int = 12) -> dict[str, Any]:
    """Return only the evidence relevant to a question, with referenceable IDs.

    This does not guess an answer. It hands the model the measurements it
    needs, flags uncertain ones, and says when more evidence is available.
    """
    words = _tokens(question)
    wanted_kinds: set[str] = set()
    for hint, kinds in _KIND_HINTS.items():
        if hint in str(question).lower():
            wanted_kinds |= kinds
    scored: list[tuple[float, Evidence]] = []
    for item in response.evidence or []:
        kind = item.kind.value if hasattr(item.kind, "value") else str(item.kind)
        label_tokens = _tokens(item.label)
        overlap = len(words & label_tokens)
        score = float(overlap) * 3.0
        if wanted_kinds and kind in wanted_kinds:
            score += 4.0
        if item.bbox is not None and ("where" in question.lower() or "position" in question.lower()):
            score += 1.0
        score += (item.confidence or 0.0)
        if is_uncertain(item):
            score -= 1.5
        scored.append((score, item))
    scored.sort(key=lambda pair: -pair[0])
    chosen = [item for score, item in scored if score > 0][:limit]
    nodes = [evidence_node(item) for item in chosen]
    lines = []
    for node in nodes:
        suffix = " UNCERTAIN - do not treat as verified" if node["uncertain"] else ""
        where = f" @{node['bbox']}" if node["bbox"] else ""
        lines.append(f"[{node['id']}] {node['kind']}: {node['label']}{where}{suffix}")
    prompt = "\n".join(lines) or "No relevant measured evidence found."
    truncated = len(scored) > len(chosen)
    if truncated:
        prompt += "\nMore evidence exists; call query_evidence or evidence_graph."
    return {
        "ok": True,
        "tool": "ask",
        "image_id": response.image_id,
        "question": question,
        "evidence": nodes,
        "uncertain_ids": [node["id"] for node in nodes if node["uncertain"]],
        "truncated": truncated,
        "prompt": prompt,
        "note": (
            "Measured evidence only. Answer from this; never claim what is "
            "marked UNCERTAIN without further inspection."
        ),
    }


def confidence_audit(response: Any, expected_values: list[str]) -> dict[str, Any]:
    """Count confident text claims not supported by ground truth.

    Lower is better. This is a hallucination-risk proxy, distinct from recall.
    """
    text_items = [
        item for item in response.evidence or []
        if (item.kind.value if hasattr(item.kind, "value") else str(item.kind)) == "text"
    ]
    confident = [item for item in text_items if not is_uncertain(item)]
    wrong = [
        item for item in confident
        if not is_supported(item.label, expected_values)
    ]
    uncertain = [item for item in text_items if is_uncertain(item)]
    rate = len(wrong) / len(confident) if confident else 0.0
    return {
        "ok": True,
        "tool": "confidence_audit",
        "image_id": response.image_id,
        "text_items": len(text_items),
        "confident_items": len(confident),
        "uncertain_items": len(uncertain),
        "unsupported_confident": len(wrong),
        "false_confidence_rate": round(rate, 3),
        "examples": [item.label for item in wrong[:10]],
    }
