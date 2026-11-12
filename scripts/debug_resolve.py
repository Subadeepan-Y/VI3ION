"""Debug reference resolution (run with venv python)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TMP = Path(tempfile.mkdtemp(prefix="vi3ion-dbg-"))
(TMP / "data").mkdir()
os.environ["VI3ION_DATA_DIR"] = str(TMP / "data")
os.environ["VI3ION_ALLOWED_ROOTS"] = "D:/PROJECTS/VI3ION;" + str(TMP / "data")
os.environ["VI3ION_SEMANTIC_PROVIDER"] = "none"

from vi3ion.config import get_settings  # noqa: E402
from vi3ion.core.engine import Vi3ionEngine  # noqa: E402
from vi3ion.core.verification import ClaimVerifier  # noqa: E402
from vi3ion.core.verification.claims import parse_claim  # noqa: E402

eng = Vi3ionEngine(get_settings())
record, _ = eng.ingest_path("tests/fixtures/sample_ui.png")
image_id = record["image_id"]
response = eng.inspect_image(image_id=image_id, detail="full")
print("evidence_total", response.evidence_total)

texts = [e for e in response.evidence if e.kind.value == "text"]
print("texts:", [(e.label, e.bbox.as_rounded() if e.bbox else None) for e in texts[:10]])
shapes = [e for e in response.evidence if e.kind.value == "shape"]
print("shapes:", [(e.label, e.bbox.as_rounded() if e.bbox else None) for e in shapes[:10]])

verifier = ClaimVerifier(
    image_id=image_id,
    evidence=response.evidence,
    width=1280,
    height=800,
    bgr=eng.loader.load_bgr(record),
    ocr_available=True,
)

claims = [
    "The Save button is aligned with the Cancel button",
    "The Save button is 10 pixels to the right of the Cancel button",
    'The image contains the text "All changes saved"',
    "The image is 1280x800",
]
for claim in claims:
    parsed = parse_claim(claim)
    print("\nCLAIM:", claim)
    print("  parsed intent:", parsed.intent, "| subject:", getattr(parsed, "subject", None), "| object:", getattr(parsed, "object", None))
    result = verifier.verify(claim)
    print("  status:", result.status.value)
    print("  explanation:", result.explanation[:220])
