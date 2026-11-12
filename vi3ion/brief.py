"""Brief: compose the text layer + shape/colour descriptions into the final
model-facing text.

Structure:
1. Header — dimensions, format, file name.
2. Dominant colour — one definition (never "background" unless edge-measured).
3. Colour map — 4x3 named cells with brightness.
4. Text sections — per spatial region, spatial names in prose, exact boxes
   kept for follow-up, uncertainties and possible-misread flags.
5. Composition + shape descriptions — plain-language sentences (no raw
   coordinates as the main content, no object names).
6. Scene evidence — specks, lit rectangles, detail focus, corner content.
7. Omitted / not transcribed — per-region drop counts.
8. Honesty note — what the brief intentionally does not cover.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .analyzer import REGION_ORDER, AnalyzerResult, analyze_image
from .core.pixels.element_color import color_suffix
from .describe_shapes import color_map_grid, describe_scene
from .evidence import describe_evidence

logger = logging.getLogger("vi3ion.brief")

SPATIAL_NAME = {
    "top_bar": "top bar",
    "left_column": "left column",
    "centre": "centre",
    "right_column": "right column",
    "bottom_bar": "bottom bar",
}


@dataclass
class BriefResult:
    text: str
    tokens: int = 0
    omitted: dict[str, int] = field(default_factory=dict)
    shape_count: int = 0
    duration_ms: float = 0.0
    layout: str = ""
    budget_tokens: int = 0
    truncated: bool = False


# Sections in priority order for token-budgeted briefs. OCR text matters most
# for a vision-less model; colour/scene prose is nice-to-have.
BUDGET_SECTIONS = (
    "header",
    "text",
    "omitted",
    "composition",
    "colour",
    "scene",
    "note",
)


def _trim_sections(sections: list[tuple[str, str]], budget_tokens: int) -> tuple[list[str], bool]:
    """Keep sections in priority order until the token budget is exhausted."""
    kept: list[str] = []
    used = 0
    truncated = False
    order = {name: index for index, name in enumerate(BUDGET_SECTIONS)}
    for name, body in sorted(sections, key=lambda item: order.get(item[0], 99)):
        cost = len(body.split())
        if budget_tokens > 0 and used + cost > budget_tokens:
            # Keep a partial body when it still fits and something is left.
            remaining = budget_tokens - used
            if remaining >= 24 and body:
                words = body.split()
                kept.append(" ".join(words[:remaining]))
                used += remaining
            truncated = True
            continue
        kept.append(body)
        used += cost
    return kept, truncated


def _dominant_color(bgr: np.ndarray) -> tuple[str, float]:
    """Most frequent quantized colour + its share (one definition)."""
    small = cv2.resize(bgr, (128, 64), interpolation=cv2.INTER_AREA)
    pixels = small.reshape(-1, 3).astype(np.int32)
    quantized = (pixels // 16) * 16 + 8
    colors, counts = np.unique(quantized, axis=0, return_counts=True)
    best = int(np.argmax(counts))
    rgb = [int(v) for v in colors[best]]
    share = float(counts[best]) / float(counts.sum())
    hex_value = "#{:02x}{:02x}{:02x}".format(rgb[0], rgb[1], rgb[2])
    return hex_value, share


def _render_item(item) -> str:
    x0, y0, x1, y1 = (round(v) for v in item.bbox)
    value = item.value
    parts = [f'"{value}"']
    if item.maybe:
        parts.append(f'(possibly "{item.maybe}", uncertain)')
    elif item.missing and not value[:1].isdigit():
        parts.append(f'(number not read, expected "{item.missing}", uncertain)')
    elif item.uncertain:
        parts.append("(uncertain)")
    if item.split_from:
        parts.append(f'(split from "{item.split_from}")')
    # Measured colour, unquoted so the fidelity scorer keeps counting only the
    # text values: "Save" ink:#2B66E6 on:#FFFFFF contrast:12.4 @[373,619,421,640]
    colour = getattr(item, "color", None)
    if colour:
        suffix = color_suffix(colour)
        if suffix:
            parts.append(suffix)
    parts.append(f"@{[x0, y0, x1, y1]}")
    return " ".join(parts)


_X_BANDS = (0.25, 0.5, 0.75)
_Y_BANDS = (0.33, 0.67)


def _x_band(x_center: float, width: int) -> str:
    frac = x_center / width if width else 0.0
    if frac < _X_BANDS[0]:
        return "left"
    if frac < _X_BANDS[1]:
        return "left-center"
    if frac < _X_BANDS[2]:
        return "right-center"
    return "right"


def _y_band(y_center: float, height: int) -> str:
    frac = y_center / height if height else 0.0
    if frac < _Y_BANDS[0]:
        return "top"
    if frac < _Y_BANDS[1]:
        return "middle"
    return "bottom"


def spatial_layout(sections: dict[str, list], width: int, height: int) -> str:
    """Compact markdown table: region, text, integer box, relative position.

    The position words (top/middle/bottom + left/right) let a vision-less
    model reason about layout without doing arithmetic on raw coordinates.
    """
    rows = ["| Region | Text | Box (x0, y0, x1, y1) | Position |",
            "|---|---|---|---|"]
    for region in REGION_ORDER:
        for item in sections.get(region, []):
            x0, y0, x1, y1 = (round(v) for v in item.bbox)
            cx = (x0 + x1) / 2
            cy = (y0 + y1) / 2
            wide = (x1 - x0) > 0.6 * width
            x_word = "full-width" if wide else _x_band(cx, width)
            pos = f"{_y_band(cy, height)}-{x_word}"
            value = item.value.replace("|", "/").replace("\n", " ")
            rows.append(
                f"| {region} | {value[:60]} | ({x0}, {y0}, {x1}, {y1}) | {pos} |"
            )
    return "\n".join(rows)


def make_brief(image_path: str | Path, budget_tokens: int = 0) -> BriefResult:
    started = time.perf_counter()
    analysis = analyze_image(image_path)
    bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"could not decode image: {image_path}")

    sections: list[tuple[str, str]] = []
    sections.append(
        (
            "header",
            f"Image {analysis.width}x{analysis.height} "
            f"({Path(image_path).name}).",
        )
    )

    hex_value, share = _dominant_color(bgr)
    colour_line = f"Dominant colour: {hex_value} ({share * 100:.0f}%)."

    grid = color_map_grid(bgr)
    if grid:
        if len(set(grid)) == 1:
            colour_line += f" Colour map: {grid[0]} (uniform across the image)."
        else:
            colour_line += " Colour map: " + "; ".join(grid) + "."

    text_lines: list[str] = []
    for region in REGION_ORDER:
        items = analysis.sections.get(region, [])
        if not items:
            continue
        rendered = "; ".join(_render_item(item) for item in items)
        text_lines.append(f"{SPATIAL_NAME[region].capitalize()}: {rendered}.")
    sections.append(("text", " ".join(text_lines)))

    scene = describe_scene(bgr, analysis.items)
    composition_line = ""
    if scene.composition:
        composition_line = f"Composition: {scene.composition}"
    if scene.shapes:
        shape_line = "Shapes: " + " ".join(scene.shapes)
        composition_line = f"{composition_line} {shape_line}".strip()

    evidence = describe_evidence(bgr)
    scene_line = ""
    if evidence:
        scene_line = "Scene evidence: " + " ".join(evidence)

    omitted_bits = ""
    if analysis.omitted:
        bits = ", ".join(
            f"{SPATIAL_NAME[region]}: {count} truncated for budget"
            for region, count in analysis.omitted.items()
        )
        omitted_bits = f"Omitted from brief: {bits}."

    if analysis.untranscribed:
        bits = ", ".join(
            f"{SPATIAL_NAME[region]}: {count}"
            for region, count in analysis.untranscribed.items()
        )
        omitted_bits = (
            f"{omitted_bits} Not transcribed (below confidence floor): {bits}."
            if omitted_bits
            else f"Not transcribed (below confidence floor): {bits}."
        )

    note_line = (
        "Note: this brief describes visible text, layout, shapes and colour "
        "regions. It does not name objects; use these descriptions to "
        "recognise what is shown. Decorative lettering too faint for OCR is "
        "not transcribed. Fine detail is intentionally not covered."
    )

    sections.append(("omitted", omitted_bits))
    sections.append(("composition", composition_line))
    sections.append(("colour", colour_line))
    sections.append(("scene", scene_line))
    sections.append(("note", note_line))

    kept, truncated = _trim_sections(sections, budget_tokens)
    text = " ".join(part for part in kept if part)
    tokens = len(text.split())
    logger.debug("brief tokens=%d shapes=%d", tokens, len(scene.shapes))
    return BriefResult(
        text=text,
        tokens=tokens,
        omitted=analysis.omitted,
        shape_count=len(scene.shapes),
        duration_ms=(time.perf_counter() - started) * 1000,
        layout=spatial_layout(analysis.sections, analysis.width, analysis.height),
        budget_tokens=budget_tokens,
        truncated=truncated,
    )
