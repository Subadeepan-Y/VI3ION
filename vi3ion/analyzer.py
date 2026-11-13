"""Text layer: OCR -> rows -> spatial regions -> budgeted, annotated items.

This is the "exact text and layout" half of the brief. Drop rules:
- confidence < 0.30 -> dropped and logged, counted per region
- confidence < 0.80 -> marked ``(uncertain)``
- per-region budget -> dropped and logged (counts reported per region)

Merged/fragmented OCR text is repaired by :mod:`vi3ion.text_merge` and
:mod:`vi3ion.fused_words`, which run between OCR and region assignment.
Second-look passes (contrast, 2x small-text bands, per-row index recovery) live
in :mod:`vi3ion.relook` and :mod:`vi3ion.relook_rows`; index flags are reasoned
about in :mod:`vi3ion.index_sequence`. Shape/graph data is intentionally not
surfaced here; it belongs in debug logs.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from .cjk_glyphs import recover_cjk
from .core.ocr.providers import get_ocr_provider
from .footer_fix import reconstruct_footer
from .fused_words import split_lowercase_words
from .index_sequence import sequence_correct
from .relook import contrast_items, small_text_items
from .relook_rows import recover_rows
from .word_split import split_body_words
from .text_merge import (  # noqa: F401  (re-exported for callers)
    REGION_ORDER,
    TextItem,
    join_same_row,
    pair_numbers_across_rows,
    split_merged_words,
)

logger = logging.getLogger("vi3ion.analyzer")

TOP_FRACTION = 0.12
BOTTOM_FRACTION = 0.08
COLUMN_FRACTION = 0.25
# Display text wider than this is anchored by its left edge: a headline that
# starts in the left column belongs there even when its centre crosses 25%.
WIDE_TEXT_FRACTION = 0.25
CONF_FLOOR = 0.30
CONF_UNCERTAIN = 0.80

# Budget share per region (items), roughly 1500 tokens total when combined with
# the shape and evidence sections. The bottom bar is never starved.
REGION_BUDGET = {
    "top_bar": 8,
    "left_column": 12,
    "centre": 8,
    "right_column": 14,
    "bottom_bar": 14,
}


@dataclass
class AnalyzerResult:
    items: list[TextItem] = field(default_factory=list)
    sections: dict[str, list[TextItem]] = field(default_factory=dict)
    omitted: dict[str, int] = field(default_factory=dict)
    untranscribed: dict[str, int] = field(default_factory=dict)
    width: int = 0
    height: int = 0
    duration_ms: float = 0.0


def _ensure_debug_log() -> Path:
    debug_dir = Path("data") / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    path = debug_dir / "analyzer.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    if logger.handlers:
        logger.handlers = [handler]
    else:
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    return path


def _ocr_lines(bgr: np.ndarray, path: Path):
    """Primary OCR pass. Returns (kept, dropped) with drops kept for counting."""
    provider = get_ocr_provider()
    if not provider.available:
        logger.warning("OCR provider unavailable: %s", path)
        return [], []
    kept, dropped = [], []
    for line in provider.recognize(bgr):
        text = line.text.strip()
        if not text:
            logger.debug("drop: empty text @ %s", path)
            continue
        if line.confidence < CONF_FLOOR:
            logger.debug(
                "drop: confidence %.2f < %.2f %r @ %s",
                line.confidence, CONF_FLOOR, text, path,
            )
            dropped.append((text, float(line.confidence), tuple(line.bbox)))
            continue
        kept.append(line)
    return kept, dropped


def _text_items(lines, force_uncertain: bool = False) -> list[TextItem]:
    return [
        TextItem(
            value=line.text.strip(),
            bbox=tuple(float(v) for v in line.bbox),
            confidence=float(line.confidence),
            uncertain=force_uncertain or line.confidence < CONF_UNCERTAIN,
        )
        for line in lines
    ]


def _group_rows(items: list[TextItem]) -> list[list[TextItem]]:
    """Cluster by vertical overlap; sort rows top->bottom, items left->right."""
    ordered = sorted(items, key=lambda item: (item.bbox[1], item.bbox[0]))
    rows: list[list[TextItem]] = []
    for item in ordered:
        y0, y1 = item.bbox[1], item.bbox[3]
        item_h = y1 - y0
        item_w = item.bbox[2] - item.bbox[0]
        if item_h > 1.8 * item_w and item_h > 25:
            rows.append([item])
            continue
        placed = False
        for row in rows:
            r0 = min(i.bbox[1] for i in row)
            r1 = max(i.bbox[3] for i in row)
            r_h = r1 - r0
            if r_h <= 0 or item_h <= 0:
                continue
            if min(item_h, r_h) / max(item_h, r_h) < 0.4:
                continue
            overlap = min(y1, r1) - max(y0, r0)
            if overlap > 0.5 * min(item_h, r_h):
                row.append(item)
                placed = True
                break
        if not placed:
            rows.append([item])
    for row in rows:
        row.sort(key=lambda item: item.bbox[0])
    rows.sort(key=lambda row: min(i.bbox[1] for i in row))
    return rows


def _region_of(bbox, width: int, height: int) -> str:
    """Spatial region for one box. Wide display text is anchored by its left edge."""
    x0, y0, x1, y1 = bbox
    if y1 < TOP_FRACTION * height:
        return "top_bar"
    if y0 > (1 - BOTTOM_FRACTION) * height:
        return "bottom_bar"
    anchor = x0 if (x1 - x0) > WIDE_TEXT_FRACTION * width else (x0 + x1) / 2
    if anchor < COLUMN_FRACTION * width:
        return "left_column"
    if anchor > (1 - COLUMN_FRACTION) * width:
        return "right_column"
    return "centre"


def _assign_regions(items: list[TextItem], width: int, height: int) -> None:
    for item in items:
        item.region = _region_of(item.bbox, width, height)


_CODE_OR_SYNTAX_RE = re.compile(
    r"(?:[{};=]|\b(?:const|let|var|function|return|import|export|await|async|def|class|if|for|while|null|true|false)\b|//|\\\\|[a-zA-Z_]\w*\s*\(|:\s*['\"])",
    re.IGNORECASE,
)


def _is_body_text(item: TextItem) -> bool:
    """Paragraph prose: short item, contains lowercase, not code or bare number."""
    h = item.bbox[3] - item.bbox[1]
    if not 10 <= h <= 40:
        return False
    if re.match(r"^\d{1,3}\b", item.value.strip()):
        return False
    if _CODE_OR_SYNTAX_RE.search(item.value):
        return False
    if any(ch.islower() for ch in item.value):
        return True
    return False


def _vertical_adjacent(above: TextItem, below: TextItem) -> bool:
    """Two same-column lines with strong x-overlap and a small gap."""
    ox = min(above.bbox[2], below.bbox[2]) - max(above.bbox[0], below.bbox[0])
    w = min(above.bbox[2] - above.bbox[0], below.bbox[2] - below.bbox[0])
    if w <= 0 or ox < 0.35 * w:
        return False
    gap = below.bbox[1] - above.bbox[3]
    h = above.bbox[3] - above.bbox[1]
    return 0 <= gap <= 2.2 * h


def _join_paragraphs(sections: dict[str, list[TextItem]]) -> dict[str, list[TextItem]]:
    """Merge vertically adjacent body-text lines in a column into one paragraph.

    Only small lowercase-containing lines are considered, so headlines and
    uppercase titles never merge. The joined item inherits every line's text
    in reading order and is marked uncertain.
    """
    for region in ("left_column", "centre"):
        items = sorted(sections[region], key=lambda i: (i.bbox[1], i.bbox[0]))
        out: list[TextItem] = []
        i = 0
        while i < len(items):
            group = [items[i]]
            j = i + 1
            while j < len(items) and _is_body_text(group[-1]) and _is_body_text(items[j]):
                if not _vertical_adjacent(group[-1], items[j]):
                    break
                group.append(items[j])
                j += 1
            if len(group) > 1:
                value = " ".join(g.value for g in group)
                box = (
                    min(g.bbox[0] for g in group),
                    min(g.bbox[1] for g in group),
                    max(g.bbox[2] for g in group),
                    max(g.bbox[3] for g in group),
                )
                out.append(
                    TextItem(
                        value=value,
                        bbox=box,
                        confidence=min(g.confidence for g in group),
                        region=region,
                        uncertain=any(g.uncertain for g in group),
                    )
                )
                i = j
            else:
                out.append(items[i])
                i += 1
        sections[region] = out
    return sections


def _select_budget(sections: dict[str, list[TextItem]]) -> dict[str, int]:
    omitted: dict[str, int] = {}
    for region in REGION_ORDER:
        items = sections.get(region, [])
        cap = REGION_BUDGET[region]
        if len(items) > cap:
            for item in items[cap:]:
                logger.debug("drop: budget %s (%s)", item.value, region)
            sections[region] = items[:cap]
            omitted[region] = len(items) - cap
    return omitted


def _measure_item_colors(bgr, sections) -> None:
    """Attach a measured colour to every text item (ink + local background)."""
    from .core.pixels.element_color import measure_element
    from .text_merge import _glyph_ink

    height, width = bgr.shape[:2]
    for region_items in sections.values():
        for item in region_items:
            try:
                x0, y0, x1, y1 = (int(round(v)) for v in item.bbox)
            except Exception:  # noqa: BLE001
                continue
            x0 = max(0, min(width - 1, x0))
            y0 = max(0, min(height - 1, y0))
            x1 = max(x0 + 1, min(width, x1))
            y1 = max(y0 + 1, min(height, y1))
            crop = bgr[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            mask = None
            try:
                mask = _glyph_ink(crop)
            except Exception:  # noqa: BLE001
                mask = None
            try:
                item.color = measure_element(
                    bgr, (x0, y0, x1, y1), mask if mask is not None else None
                )
            except Exception:  # noqa: BLE001 - colour must never break the brief
                item.color = None


def analyze_image(image_path: str | Path) -> AnalyzerResult:
    started = time.perf_counter()
    _ensure_debug_log()
    path = Path(image_path)
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"could not decode image: {path}")
    height, width = bgr.shape[:2]

    # Small captures (low-DPI screenshots, scaled thumbnails) lose text to the
    # OCR pass. Upscale before OCR and map the boxes back afterwards.
    ocr_bgr = bgr
    scale = 1.0
    if max(width, height) < 900:
        scale = 2.0 if max(width, height) >= 400 else 3.0
        ocr_bgr = cv2.resize(
            bgr, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_CUBIC
        )

    raw, dropped = _ocr_lines(ocr_bgr, path)
    if scale != 1.0:
        for line in raw:
            x0, y0, x1, y1 = line.bbox
            line.bbox = (x0 / scale, y0 / scale, x1 / scale, y1 / scale)
            if line.polygon:
                line.polygon = [[x / scale, y / scale] for x, y in line.polygon]
        dropped = [
            (text, conf, (x0 / scale, y0 / scale, x1 / scale, y1 / scale))
            for text, conf, (x0, y0, x1, y1) in dropped
        ]
    items = _text_items(raw)
    items.extend(contrast_items(bgr, items, path))
    items.extend(small_text_items(bgr, items, path))
    items = split_merged_words(bgr, items)
    items = split_lowercase_words(bgr, items)
    items = split_body_words(bgr, items)
    _assign_regions(items, width, height)
    items.extend(recover_rows(bgr, items, width, height))
    # CJK margin recovery is the most expensive extra pass; skip it in
    # low-resource mode (local models rarely need marginal kanji).
    from .config import get_settings

    if not get_settings().low_resource:
        items.extend(recover_cjk(bgr, items, width, height))

    sections: dict[str, list[TextItem]] = {region: [] for region in REGION_ORDER}
    for row in _group_rows(items):
        for item in row:
            sections[item.region].append(item)
    sections = join_same_row(sections)
    sections = _join_paragraphs(sections)
    # Index reasoning runs after joins so merged rows (label + margin CJK)
    # still get their expected-number flag.
    for region in REGION_ORDER:
        sequence_correct(sections[region])
    sections = pair_numbers_across_rows(sections)
    sections["bottom_bar"] = reconstruct_footer(bgr, sections["bottom_bar"])

    # Measure each element's own colour (ink on its local background). The
    # glyph mask separates letters from the surface behind them.
    _measure_item_colors(bgr, sections)

    untranscribed: dict[str, int] = {}
    for text, confidence, bbox in dropped:
        region = _region_of(bbox, width, height)
        untranscribed[region] = untranscribed.get(region, 0) + 1
        logger.debug("not transcribed (%.2f) %r in %s", confidence, text, region)

    omitted = _select_budget(sections)
    return AnalyzerResult(
        items=items,
        sections=sections,
        omitted=omitted,
        untranscribed=untranscribed,
        width=width,
        height=height,
        duration_ms=(time.perf_counter() - started) * 1000,
    )
