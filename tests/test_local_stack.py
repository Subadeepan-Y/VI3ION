"""Local runtime detection: vision classification and probe behaviour."""

from __future__ import annotations

import json
from typing import Any

import vi3ion.local_stack as ls


def test_model_supports_vision_names():
    assert ls.model_supports_vision("llava:7b")
    assert ls.model_supports_vision("qwen2.5vl:7b")
    assert ls.model_supports_vision("llama3.2-vision:11b")
    assert ls.model_supports_vision("minicpm-v:latest")
    assert ls.model_supports_vision("claude-sonnet-4-6")
    assert ls.model_supports_vision("gpt-4o")
    assert ls.model_supports_vision("gemini-2.5-pro")
    assert not ls.model_supports_vision("qwen3:8b")
    assert not ls.model_supports_vision("")
    assert not ls.model_supports_vision("llama3.1:8b")
    assert not ls.model_supports_vision("deepseek-v3")


def test_is_local_provider():
    assert ls.is_local_provider("ollama")
    assert ls.is_local_provider("lmstudio")
    assert ls.is_local_provider("custom", "http://127.0.0.1:8080/v1")
    assert ls.is_local_provider("custom", "http://localhost:1234/v1")
    # A local GPU exposed through a tunnel is still local inference.
    assert ls.is_local_provider(
        "kaggle-qwen", "https://jeff-sail-aquatic-fabrics.trycloudflare.com/v1"
    )
    assert ls.is_local_provider("custom", "https://x.unsloth.app/v1")
    assert not ls.is_local_provider("openai", "https://api.openai.com/v1")
    assert not ls.is_local_provider("whatstoken", "https://www.whatstoken.ai/v1")


def test_describe_role_cloud_vision_model():
    assistant = ls.describe_role("claude-sonnet-4-6", provider_id="agentrouter")
    assert assistant["role"] == "assistant"
    assert assistant["vision_capable"] is True


def test_local_model_named_like_cloud_model_is_not_vision():
    # A local server serving something called "gpt-4o" is still a blind local
    # model unless the name carries a local vision hint.
    role = ls.describe_role("gpt-4o", provider_id="ollama")
    assert role["local"] is True
    assert role["vision_capable"] is False
    assert role["role"] == "eyes"


def test_describe_role():
    eyes = ls.describe_role("qwen3:8b", provider_id="ollama")
    assert eyes["role"] == "eyes"
    assert eyes["local"] is True
    assert eyes["vision_capable"] is False

    assistant = ls.describe_role("llava:7b", provider_id="ollama")
    assert assistant["role"] == "assistant"
    assert assistant["vision_capable"] is True


def test_model_names_parsing():
    openai_style = {"data": [{"id": "qwen3:8b"}, {"id": "llava:7b"}]}
    ollama_style = {"models": [{"name": "qwen3:8b"}, {"name": "llava:7b"}]}
    assert ls._model_names(openai_style) == ["qwen3:8b", "llava:7b"]
    assert ls._model_names(ollama_style) == ["qwen3:8b", "llava:7b"]
    assert ls._model_names({"nope": 1}) == []
    assert ls._model_names(None) == []


def test_find_runtime_binary_ignores_non_executables(monkeypatch, tmp_path):
    # A file named like a runtime binary but with a non-executable extension
    # must not count as an installed runtime (regression: main.CPL).
    fake = tmp_path / "main.CPL"
    fake.write_text("not a binary")
    monkeypatch.setattr(ls.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        ls,
        "RUNTIME_INSTALL_DIRS",
        {"llama.cpp": (str(tmp_path),)},
    )
    monkeypatch.setattr(ls, "RUNTIME_BINARIES", {"llama.cpp": ("main", "main.exe")})
    assert ls.find_runtime_binary("llama.cpp") is None

    real = tmp_path / "main.exe"
    real.write_text("MZ")
    assert ls.find_runtime_binary("llama.cpp") == str(real)


def test_probe_runtime_reports_closed_port(monkeypatch):
    monkeypatch.setattr(ls, "_port_open", lambda *a, **k: False)
    status = ls.probe_runtime("ollama", ls.RUNTIMES["ollama"])
    assert status.reachable is False
    assert status.error == "port closed"
    assert status.vision_models == []


def test_probe_runtime_reads_models(monkeypatch):
    monkeypatch.setattr(ls, "_port_open", lambda *a, **k: True)

    def fake_json(url: str, timeout: float) -> Any:
        if url.endswith("/api/tags"):
            return {"models": [{"name": "llava:7b"}, {"name": "qwen3:8b"}]}
        return None

    monkeypatch.setattr(ls, "_http_json", fake_json)
    status = ls.probe_runtime("ollama", ls.RUNTIMES["ollama"])
    assert status.reachable is True
    assert status.models == ["llava:7b", "qwen3:8b"]
    assert status.vision_models == ["llava:7b"]
    assert status.base_url == "http://127.0.0.1:11434/v1"


def test_probe_runtime_handles_http_error(monkeypatch):
    monkeypatch.setattr(ls, "_port_open", lambda *a, **k: True)

    def boom(url: str, timeout: float) -> Any:
        raise OSError("connection reset")

    monkeypatch.setattr(ls, "_http_json", boom)
    status = ls.probe_runtime("vllm", ls.RUNTIMES["vllm"])
    assert status.reachable is True
    assert status.error == "connection reset"


def test_local_stack_report_shape(monkeypatch):
    monkeypatch.setattr(ls, "_port_open", lambda *a, **k: False)
    report = ls.local_stack_report()
    assert report["ok"] is True
    assert report["runtimes"] == []
    assert "ollama" in report["offline_runtimes"]
    assert "eyes" in report["recommendation"]
    json.dumps(report)  # must be JSON-serialisable


def test_local_stack_report_with_vision_model(monkeypatch):
    monkeypatch.setattr(ls, "_port_open", lambda *a, **k: True)
    monkeypatch.setattr(
        ls,
        "_http_json",
        lambda url, timeout: {"data": [{"id": "qwen2.5vl:7b"}]},
    )
    report = ls.local_stack_report()
    assert report["vision_models"] == ["qwen2.5vl:7b"]
    assert "assistant" in report["recommendation"]
