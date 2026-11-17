"""Traceable evidence: focus, graph, audit and privacy controls."""

from __future__ import annotations

import json
from pathlib import Path

from vi3ion.config import get_settings
from vi3ion.core.engine import Vi3ionEngine
from vi3ion.evidence_api import confidence_audit, evidence_graph, focus_evidence, is_uncertain
from vi3ion.schemas.common import BBox, Evidence, EvidenceKind, Provenance


def _item(label: str, kind: EvidenceKind = EvidenceKind.TEXT, confidence: float = 0.9,
          uncertain: bool = False, box=None):
    attrs = {"uncertain": True} if uncertain else {}
    return Evidence(
        evidence_id=f"id_{label[:4]}",
        image_id="img_test",
        kind=kind,
        label=label,
        bbox=BBox(x0=0, y0=0, x1=10, y1=10) if box is None else box,
        confidence=confidence,
        attributes=attrs,
        provenance=Provenance(module="ocr", method="test"),
    )


class _Response:
    image_id = "img_test"
    evidence = [
        _item("Save button"),
        _item("blue background", EvidenceKind.COLOR),
        _item("Save (uncertain)", uncertain=True, confidence=0.4),
    ]


def test_uncertain_flag():
    assert is_uncertain(_Response.evidence[0]) is False
    assert is_uncertain(_Response.evidence[2]) is True


def test_focus_evidence_filters_by_question():
    result = focus_evidence(_Response(), "what colour is the background?")
    labels = [item["label"] for item in result["evidence"]]
    assert "blue background" in labels
    assert result["prompt"]
    assert all(item["id"] for item in result["evidence"])


def test_evidence_graph_has_provenance_and_uncertainty():
    result = evidence_graph(_Response())
    assert result["nodes"][0]["provenance"]["module"] == "ocr"
    assert any(node["uncertain"] for node in result["nodes"])
    assert all("from" in relation and "to" in relation for relation in result["relationships"]) or not result["relationships"]


def test_confidence_audit_counts_only_confident_claims():
    result = confidence_audit(_Response(), ["Save button"])
    assert result["confident_items"] == 1
    assert result["uncertain_items"] == 1
    assert result["false_confidence_rate"] == 0.0


def test_forget_removes_image(tmp_path, monkeypatch):
    monkeypatch.setenv("VI3ION_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    engine = Vi3ionEngine(get_settings())
    image = Path(__file__).resolve().parent / "fixtures" / "sample_ui.png"
    record, _ = engine.loader.ingest_path(image)
    result = engine.forget(record["image_id"])
    assert result["forgot"] == record["image_id"]
    get_settings.cache_clear()


def test_purge_requires_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("VI3ION_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    engine = Vi3ionEngine(get_settings())
    result = engine.purge(days=0, confirm=False)
    assert result["ok"] is False
    assert "confirm" in result["error"]
    get_settings.cache_clear()


def test_task_benchmark_dry_run():
    from scripts.task_benchmark import main

    out = tmp = None
    # no tmp_path fixture needed: use a temp file under the repo docs dir
    from pathlib import Path

    target = Path(__file__).resolve().parent.parent / "docs" / "task-benchmark-test.json"
    rc = main(["--dry-run", "--out", str(target.relative_to(Path(__file__).resolve().parent.parent))])
    assert rc == 0
    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["mode"].startswith("dry-run")
    assert "with_vi3ion" in report["summary"]
    target.unlink(missing_ok=True)
