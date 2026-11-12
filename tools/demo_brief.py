"""Print the Vi3ion brief for a screenshot (text + scene description)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vi3ion.brief import make_brief  # noqa: E402

DEFAULT_IMAGE = (
    Path.home()
    / "Pictures"
    / "Screenshots"
    / "Screenshot 2026-10-31 212904.png"
)


def main() -> int:
    image = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_IMAGE
    if not image.exists():
        print(f"error: image not found: {image}", file=sys.stderr)
        return 2
    result = make_brief(image)
    print(result.text)
    print()
    print(f"[tokens={result.tokens}, omitted={result.omitted}, "
          f"shapes={result.shape_count}, duration_ms={result.duration_ms:.0f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
