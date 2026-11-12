"""Image memory: signatures, similarity and version diffs."""

from __future__ import annotations

from pathlib import Path

from vi3ion.image_memory import (
    diff_images,
    hamming_similarity,
    layout_similarity,
    perceptual_hash_from_path,
    similarity,
    signature_from_evidence,
    text_similarity,
)
from vi3ion.storage.database import Database


def text(label: str, box: tuple[float, float, float, float]) -> dict:
    return {"kind": "text", "label": label, "bbox": list(box)}


def sig(items: list[dict], width: int = 1000, height: int = 600) -> dict:
    return signature_from_evidence(items, width, height)


def test_signature_counts_text_and_builds_layout():
    signature = sig(
        [
            text("Dashboard", (20, 20, 200, 50)),
            text("Revenue", (30, 90, 120, 115)),
            {"kind": "shape", "label": "rect", "bbox": [0, 0, 10, 10]},
        ]
    )
    assert signature["text_count"] == 2
    assert signature["width"] == 1000
    assert signature["layout_key"].count("1") == 2
    assert signature["signature"]


def test_similarity_uses_perceptual_hash():
    base = {
        "layout_key": "1" * 64,
        "occupied_cells": [0, 1, 2],
        "text_key": "a|b",
        "phash": "ffffffffffffffff",
    }
    same = dict(base)
    other = dict(base, phash="0000000000000000")
    assert similarity(base, same) == 1.0
    # Identical OCR but a different picture is not the same screen.
    assert similarity(base, other) < 0.9
    # Without hashes the previous behaviour applies.
    no_hash_a = {k: v for k, v in base.items() if k != "phash"}
    no_hash_b = dict(no_hash_a)
    assert similarity(no_hash_a, no_hash_b) == 1.0


def test_hamming_similarity_bounds():
    assert hamming_similarity("ffffffffffffffff", "ffffffffffffffff") == 1.0
    assert hamming_similarity("ffffffffffffffff", "0000000000000000") == 0.0
    assert hamming_similarity("", "ffffffffffffffff") == 0.0
    assert hamming_similarity("abcd", "abcdefgh") == 0.0


def test_perceptual_hash_is_stable():
    fixture = Path(__file__).parent / "fixtures" / "sample_ui.png"
    first = perceptual_hash_from_path(str(fixture))
    second = perceptual_hash_from_path(str(fixture))
    assert first and first == second
    assert len(first) == 16


def test_identical_images_score_one():
    a = sig([text("Dashboard", (20, 20, 200, 50)), text("Save", (800, 500, 860, 530))])
    b = sig([text("Dashboard", (20, 20, 200, 50)), text("Save", (800, 500, 860, 530))])
    assert layout_similarity(a, b) == 1.0
    assert text_similarity(a, b) == 1.0
    assert similarity(a, b) == 1.0


def test_empty_layout_is_not_similar():
    empty = sig([])
    other = sig([text("Dashboard", (20, 20, 200, 50))])
    assert layout_similarity(empty, other) == 0.0


def test_diff_pairs_edited_text_as_changed():
    older = sig([text("Dashboard v1", (350, 30, 550, 60))])
    newer = sig([text("Dashboard v2", (350, 30, 550, 60))])
    result = diff_images(older, newer)
    assert result["counts"]["changed"] == 1
    assert result["counts"]["added"] == 0
    assert result["counts"]["removed"] == 0
    change = result["changes"][0]
    assert change["old"] == "Dashboard v1"
    assert change["new"] == "Dashboard v2"
    assert change["region"] == "top-centre"


def test_diff_reports_moved_elements():
    older = sig([text("Save", (100, 100, 180, 130))])
    newer = sig([text("Save", (300, 100, 380, 130))])
    result = diff_images(older, newer)
    assert result["counts"]["moved"] == 1
    assert result["changes"][0]["kind"] == "moved"


def test_diff_reports_added_and_removed():
    older = sig([text("Old label", (10, 10, 120, 40))])
    newer = sig([text("Completely different", (600, 400, 760, 430))])
    result = diff_images(older, newer)
    assert result["counts"]["removed"] == 1
    assert result["counts"]["added"] == 1
    assert result["counts"]["changed"] == 0


def test_registry_persists_labels_and_preserves_them(tmp_path):
    db = Database(tmp_path / "registry.db")
    db.init()

    first = sig([text("Dashboard v1", (10, 10, 200, 40))])
    db.upsert_image_registry("img_1", first)
    assert db.get_image_registry("img_1")["label"] == ""

    assert db.set_image_label("img_1", "dashboard v1") is True
    db.upsert_image_registry("img_1", first)
    row = db.get_image_registry("img_1")
    assert row["label"] == "dashboard v1"
    assert row["signature"]["text_count"] == 1

    listed = db.list_image_registry(limit=10)
    assert [r["image_id"] for r in listed] == ["img_1"]
