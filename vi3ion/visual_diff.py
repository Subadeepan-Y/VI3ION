"""Visual diff between two stored screenshots.

Text diffs miss changes that are not words: a button that changed colour, a
card that moved, a spinner that appeared. This module compares the pixels of
two images and reports where they differ.

Everything is measured, never inferred: the output is a changed-pixel
percentage plus the bounding boxes of the changed areas.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# A pixel counts as changed when any channel differs by more than this.
CHANNEL_TOLERANCE = 12

# Ignore tiny differences: antialiasing noise and compression artefacts.
MIN_REGION_PIXELS = 24


def _load(path: str):
    try:
        import cv2
    except Exception:  # noqa: BLE001 - optional dependency
        return None, None
    if not path or not Path(path).exists():
        return cv2, None  # avoids OpenCV's noisy imread warning
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    return cv2, image


def visual_diff(
    older_path: str,
    newer_path: str,
    tolerance: int = CHANNEL_TOLERANCE,
    max_regions: int = 12,
) -> dict[str, Any]:
    """Compare two images pixel-wise.

    Returns a dict with `changed_percent`, `changed_regions` (bounding boxes
    in the newer image's pixels) and `size_match`.
    """
    cv2, older = _load(older_path)
    if cv2 is None:
        return {"available": False, "reason": "opencv unavailable"}
    _, newer = _load(newer_path)
    if older is None or newer is None:
        return {"available": False, "reason": "image could not be read"}

    h_old, w_old = older.shape[:2]
    h_new, w_new = newer.shape[:2]
    size_match = (w_old, h_old) == (w_new, h_new)

    if not size_match:
        # Compare at the size of the newer image.
        older = cv2.resize(older, (w_new, h_new), interpolation=cv2.INTER_AREA)
        h_old, w_old = h_new, h_new

    diff = cv2.absdiff(older, newer)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, tolerance, 255, cv2.THRESH_BINARY)

    total = mask.shape[0] * mask.shape[1]
    changed_pixels = int(cv2.countNonZero(mask))
    changed_percent = round(changed_pixels / total * 100, 3) if total else 0.0

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    regions: list[dict[str, Any]] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < MIN_REGION_PIXELS:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        regions.append(
            {
                "bbox": [int(x), int(y), int(x + w), int(y + h)],
                "pixels": int(area),
                "position": _position(x, y, w, h, w_new, h_new),
            }
        )
    regions.sort(key=lambda item: item["pixels"], reverse=True)

    return {
        "available": True,
        "size_match": size_match,
        "older_size": [int(w_old), int(h_old)],
        "newer_size": [int(w_new), int(h_new)],
        "changed_percent": changed_percent,
        "changed_pixels": changed_pixels,
        "changed_regions": regions[:max_regions],
        "changed_region_count": len(regions),
        "tolerance": tolerance,
    }


def _position(x: int, y: int, w: int, h: int, width: int, height: int) -> str:
    """Where the changed area sits, in plain words."""
    cx = x + w / 2
    cy = y + h / 2
    col = "left" if cx < width / 3 else ("right" if cx > 2 * width / 3 else "centre")
    row = "top" if cy < height / 3 else ("bottom" if cy > 2 * height / 3 else "middle")
    if row == "middle" and col == "centre":
        return "centre"
    return f"{row}-{col}"


def describe_visual(result: dict[str, Any]) -> str:
    """One-line summary for the agent."""
    if not result.get("available"):
        return "visual comparison unavailable"
    percent = result.get("changed_percent", 0.0)
    if percent < 0.05:
        return "pixels are effectively identical"
    regions = result.get("changed_regions", [])
    where = ", ".join(sorted({r["position"] for r in regions})) or "unknown area"
    return f"{percent}% of pixels differ (changed areas: {where})"


def changed_since(path: str, reference_path: str) -> dict[str, Any]:
    """Convenience wrapper: newer vs reference."""
    return visual_diff(reference_path, path)


def paths_exist(*paths: str) -> bool:
    return all(path and Path(path).exists() for path in paths)
