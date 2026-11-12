"""Manual smoke test: analyse the sample screenshot and exercise the tools."""

from __future__ import annotations

from vi3ion.config import Settings
from vi3ion.core.engine import Vi3ionEngine

CLAIMS = [
    '"Save" is aligned with "Cancel"',
    '"Save" is 20 pixels to the left of "Cancel"',
    "image is 1280x800",
    'the image contains the text "Settings"',
    '"Save" is blue',
    "the user looks confused",
]


def main() -> None:
    engine = Vi3ionEngine(Settings(data_dir="data"))
    response = engine.inspect_image(path="tests/fixtures/sample_ui.png", detail="full", force=True)
    shapes = [item for item in response.evidence if item.kind.value == "shape"]
    print("SHAPES", [(item.attributes.get("shape"), item.bbox.as_rounded()) for item in shapes])
    print("SUMMARY", response.summary[:400])

    for claim in CLAIMS:
        verified = engine.verify_claim(response.image_id, claim)
        print("\n---", claim, "=>", verified.verification.status.value)
        print(verified.verification.explanation[:300])

    region = engine.inspect_region(response.image_id, [320, 580, 710, 670], detail="standard")
    print("\nREGION EVIDENCE", region.evidence_total)
    print(region.summary[:800])

    compared = engine.compare_regions(
        response.image_id, [329, 599, 491, 653], [509, 599, 692, 654]
    )
    print("\nCOMPARE", compared.summary[:600])


if __name__ == "__main__":
    main()
