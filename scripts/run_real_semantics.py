"""Run the screenshot through real semantic providers and print the brief + objects."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vi3ion.config import get_settings  # noqa: E402
from vi3ion.core.engine import Vi3ionEngine  # noqa: E402

SHOT = Path(r"C:\Users\ADMIN\Pictures\Screenshots\Screenshot 2026-10-31 212904.png")


def main() -> None:
    engine = Vi3ionEngine(get_settings())
    record, _ = engine.ingest_path(str(SHOT))
    response = engine.inspect_image(
        image_id=record["image_id"], force=True, detail="standard"
    )
    print(response.summary)
    print()
    print("OBJECTS (from evidence):")
    for e in response.evidence:
        if e.kind.value == "object" and e.bbox is not None:
            print(
                f"  {e.label!r} @{e.bbox.as_rounded()} "
                f"conf={e.confidence} src={e.attributes.get('source')}"
            )
    print()
    print("TIMINGS:", response.timings_ms)


if __name__ == "__main__":
    main()
