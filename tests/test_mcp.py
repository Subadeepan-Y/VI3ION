"""MCP adapter: tools return JSON strings on stdio contract, never crash."""

from __future__ import annotations

import json

import pytest

import vi3ion.mcp_server as mcp


def test_tools_registered():
    import asyncio

    from mcp.types import Tool

    tools = asyncio.run(mcp.server.list_tools())
    tool_names = {tool.name for tool in tools}
    assert tool_names == {
        "inspect_image",
        "inspect_region",
        "query_evidence",
        "verify_claim",
        "compare_regions",
        "cross_check_text",
        "list_images",
        "remember_image",
        "diff_images",
        "local_stack",
        "doctor",
    }


def test_doctor_tool():
    result = mcp.doctor()
    payload = json.loads(result)
    assert payload["ok"] is True
    names = {c["check"] for c in payload["checks"]}
    assert {"ocr", "resources", "registry", "local_runtimes"} <= names
    assert isinstance(payload["next_actions"], list)


def test_local_stack_tool():
    result = mcp.local_stack(timeout=0.2)
    payload = json.loads(result)
    assert payload["ok"] is True
    assert "runtimes" in payload
    assert "recommendation" in payload
    assert isinstance(payload["vision_models"], list)


def test_inspect_image_tool(sample_ui_bytes):
    # Use the path-based entry; sample lives inside the project root (allowed).
    result = mcp.inspect_image(path=str(__import__("pathlib").Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sample_ui.png"), detail="compact")
    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["tool"] == "inspect_image"
    assert payload["image_id"].startswith("img_")
    assert "summary" in payload


def test_verify_claim_tool(sample_ui_id):
    result = mcp.verify_claim(image_id=sample_ui_id, claim="The image is 1280x800")
    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["verification"]["status"] == "verified"


def test_inspect_region_tool(sample_ui_id):
    result = mcp.inspect_region(image_id=sample_ui_id, region=[329, 599, 491, 653], detail="compact")
    payload = json.loads(result)
    assert payload["ok"] is True
    assert "summary" in payload


def test_error_boundary_returns_json():
    result = mcp.inspect_image(image_id="img_missing")
    payload = json.loads(result)
    assert payload["ok"] is False
    assert "error" in payload


def test_remember_and_list_images_tool(sample_ui_id):
    result = mcp.remember_image(image_id=sample_ui_id, label="settings screen")
    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["data"]["label"] == "settings screen"

    listed = json.loads(mcp.list_images(limit=100))
    assert listed["ok"] is True
    match = [i for i in listed["images"] if i["image_id"] == sample_ui_id]
    assert match and match[0]["label"] == "settings screen"
    assert match[0]["text_count"] > 0


def test_diff_images_tool(sample_ui_id):
    result = mcp.diff_images(image_id_a=sample_ui_id, image_id_b=sample_ui_id)
    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["tool"] == "diff_images"
    diff = payload["data"]["diff"]
    assert diff["overall_similarity"] == 1.0
    assert diff["change_count"] == 0
    assert payload["next_actions"]
