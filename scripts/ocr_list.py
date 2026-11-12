"""Print all stored text evidence for an image, in reading order."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["VI3ION_SEMANTIC_PROVIDER"] = "none"

from vi3ion.config import get_settings  # noqa: E402
from vi3ion.core.engine import Vi3ionEngine  # noqa: E402

image_id = sys.argv[1] if len(sys.argv) > 1 else None
if not image_id:
    print("usage: python scripts/ocr_list.py <image_id>")
    raise SystemExit(2)

engine = Vi3ionEngine(get_settings())
response = engine.query_evidence(image_id=image_id, kind="text", limit=200, detail="standard")
items = sorted(
    (e for e in response.evidence if e.bbox is not None),
    key=lambda e: (round(e.bbox.y0 / 20), e.bbox.x0),
)
for e in items:
    text = (e.attributes.get("text") or e.label).strip()
    print(f"[{e.bbox.as_rounded(0)}] {text}")
print(f"\n{len(items)} text items")
