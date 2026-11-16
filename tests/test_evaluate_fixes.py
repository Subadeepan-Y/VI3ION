"""Evaluation fixes: uncertain ground truth, markers, hedges, shape blueprints."""

from __future__ import annotations

import json

from vi3ion.evaluate import FidelityReport, normalize, review
from vi3ion import mcp_server


BRIEF = """Top bar: "SUBADEEPAN" @[1, 2, 3, 4]; "[M] AUDIO" @[1, 2, 3, 4].
Composition: a blue band. Dominant colour: #080808 (25%). Colour map: row 1, col 1: grey, mid.
Shapes: a circle. Note: this brief describes visible text, layout, shapes and colour regions. It does not name objects; use these descriptions to recognise what is shown."""


def test_uncertain_ground_truth_is_not_scored():
    expected = {
        "text": [
            {"value": "SUBADEEPAN", "region": "top_bar"},
            {"value": "[garbled-kanji]", "region": "top_bar", "uncertain": True},
        ]
    }
    report = review(BRIEF, expected)
    assert report.expected_units == 1
    assert report.uncertain_units == 1
    assert report.recall == 1.0


def test_keyboard_marker_is_ignored_when_comparing():
    assert normalize("[M] AUDIO") == "audio"
    assert normalize("[SPACE] DOSSIER") == "dossier"
    assert normalize("AUDIO") == normalize("[M] AUDIO")


MINIMAL = (
    'Top bar: "REAL" @[1, 2, 3, 4]. Composition: a blue band. '
    'Shapes: a circle. Note: this brief describes visible text, layout, shapes and colour regions. '
    'It does not name objects; use these descriptions to recognise what is shown.'
)


def test_hedged_alternatives_do_not_lower_precision():
    # A hedged reading is still a recall candidate, but it is not a confident
    # assertion that should be charged against precision.
    hedged = MINIMAL.replace('"REAL"', '"REAL" (possibly "GARBLED", uncertain)', 1)
    expected = {"text": [{"value": "REAL", "region": "top_bar"}]}
    plain = review(MINIMAL, expected)
    scored = review(hedged, expected)
    assert plain.precision == 1.0
    assert scored.recall == 1.0  # the hedge still helps recall
    assert scored.spurious == []  # but it is not scored as a wrong claim


def test_number_not_read_annotation_does_not_pollute_value():
    text = MINIMAL + ' "TITLE" (number not read, expected "00")'
    report = review(text, {"text": [{"value": "REAL", "region": "top_bar"}, {"value": "TITLE"}]})
    assert report.spurious == []


def test_blueprint_reports_normalised_shapes(monkeypatch):
    class Box:
        def as_rounded(self):
            return [0, 0, 10, 20]

    class Item:
        def __init__(self, kind, attrs):
            self.kind = type("K", (), {"value": kind})()
            self.attributes = attrs
            self.bbox = Box()

    class Response:
        image_id = "shot"
        evidence = [
            Item("image", {"width": 100, "height": 200}),
            Item("color", {"hex": "#ffffff", "share": 0.9}),
            Item("shape", {"shape": "circle", "ink_hex": "#ff0000",
                           "ink_name": "red", "rotation_deg": 0, "area_px": 100}),
        ]
        def to_json(self, detail):
            return "{}"

    class Engine:
        def inspect_image(self, **kwargs):
            return Response()

    monkeypatch.setattr(mcp_server, "engine", lambda: Engine())
    result = json.loads(mcp_server.reconstruction_blueprint(path="x.png"))
    assert result["canvas"] == {"width": 100, "height": 200, "background": "#ffffff"}
    assert result["shapes"][0]["box_pct"] == [0.0, 0.0, 10.0, 10.0]
    assert "10.0%,10.0%" in result["recreation_prompt"]
