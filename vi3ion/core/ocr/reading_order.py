"""Reading-order estimation: rows first, then left-to-right within a row."""

from __future__ import annotations

import statistics

from .providers import OCRLine


def assign_reading_order(lines: list[OCRLine]) -> list[OCRLine]:
    if not lines:
        return []
    heights = [max(1.0, line.bbox[3] - line.bbox[1]) for line in lines]
    tolerance = max(4.0, statistics.median(heights) * 0.6)

    ordered = sorted(lines, key=lambda line: ((line.bbox[1] + line.bbox[3]) / 2.0, line.bbox[0]))
    rows: list[list[OCRLine]] = []
    for line in ordered:
        center_y = (line.bbox[1] + line.bbox[3]) / 2.0
        placed = False
        for row in rows:
            reference = row[0]
            ref_center = (reference.bbox[1] + reference.bbox[3]) / 2.0
            if abs(center_y - ref_center) <= tolerance:
                row.append(line)
                placed = True
                break
        if not placed:
            rows.append([line])

    index = 0
    for row_index, row in enumerate(rows):
        row.sort(key=lambda line: line.bbox[0])
        for line in row:
            line.order = index
            line.row = row_index
            index += 1
    return [line for row in rows for line in row]
