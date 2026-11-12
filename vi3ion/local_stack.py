"""Local LLM runtime detection.

Vi3ion is the perception layer for agents. Many of those agents run against a
local model (Ollama, llama.cpp, LM Studio, vLLM, Unsloth, SGLang, LocalAI,
Jan, koboldcpp, text-generation-webui). This module answers two questions the
agent cannot answer on its own:

  1. Which local runtimes are reachable right now, and what models do they
     serve?
  2. Does a given model accept images (so should Vi3ion be eyes or assistant)?

Everything here is offline-friendly: only loopback HTTP is used, requests have
short timeouts, and a failed probe is reported, never raised.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT = 1.5

# Known local runtimes: name -> (default port, probe paths).
# Probe paths are tried in order; the first HTTP response wins.
RUNTIMES: dict[str, dict[str, Any]] = {
    "ollama": {
        "port": 11434,
        "paths": ["/api/tags", "/v1/models"],
        "models_path": "/api/tags",
        "openai": False,
    },
    "llama.cpp": {
        "port": 8080,
        "paths": ["/v1/models", "/props"],
        "models_path": "/v1/models",
        "openai": True,
    },
    "lmstudio": {
        "port": 1234,
        "paths": ["/v1/models"],
        "models_path": "/v1/models",
        "openai": True,
    },
    "vllm": {
        "port": 8000,
        "paths": ["/v1/models"],
        "models_path": "/v1/models",
        "openai": True,
    },
    "localai": {
        "port": 8080,
        "paths": ["/v1/models"],
        "models_path": "/v1/models",
        "openai": True,
    },
    "sglang": {
        "port": 30000,
        "paths": ["/v1/models"],
        "models_path": "/v1/models",
        "openai": True,
    },
    "text-generation-webui": {
        "port": 5000,
        "paths": ["/v1/models"],
        "models_path": "/v1/models",
        "openai": True,
    },
    "koboldcpp": {
        "port": 5001,
        "paths": ["/v1/models", "/api/v1/model"],
        "models_path": "/v1/models",
        "openai": True,
    },
    "jan": {
        "port": 1337,
        "paths": ["/v1/models"],
        "models_path": "/v1/models",
        "openai": True,
    },
    "llamafile": {
        "port": 8080,
        "paths": ["/v1/models"],
        "models_path": "/v1/models",
        "openai": True,
    },
}

# Model-name fragments that indicate image input support.
VISION_HINTS = (
    "llava",
    "bakllava",
    "nanollava",
    "moondream",
    "minicpm-v",
    "minicpmv",
    "qwen-vl",
    "qwen2-vl",
    "qwen2.5-vl",
    "qwen2.5vl",
    "qwen3-vl",
    "qwen3vl",
    "gemma3",
    "gemma-3",
    "llama3.2-vision",
    "llama-3.2-vision",
    "llama3.2v",
    "internvl",
    "idefics",
    "pixtral",
    "phi3-vision",
    "phi-3.5-vision",
    "granite-vision",
    "smolvlm",
    "molmo",
    "cogvlm",
    "ernie-4.5-vl",
    "step-1v",
    "hunyuan-vision",
    "kimi-vl",
    "em-3",
    "llama4",
    "llama-4",
)

# Cloud model names that accept images. Used so a cloud model is not mistaken
# for a blind one when the caller asks for a recommended role.
CLOUD_VISION_HINTS = (
    "claude",
    "anthropic",
    "gpt-4o",
    "gpt-5",
    "gpt-6",
    "o1-",
    "o3-",
    "o4-",
    "gemini",
    "grok",
    "glm-4v",
    "glm-5v",
    "qwen-vl",
    "qwen2.5-vl",
    "qwen3-vl",
    "minicpm-v",
    "internvl",
    "deepseek-vl",
    "pixtral",
    "mistral-small",
    "nova-pro",
    "nova-lite",
    "llama-3.2-vision",
)

# Provider ids that map to a local runtime in OpenCode configs.
LOCAL_PROVIDER_IDS = (
    "ollama",
    "lmstudio",
    "lm-studio",
    "llamacpp",
    "llama-cpp",
    "llama.cpp",
    "vllm",
    "sglang",
    "localai",
    "local-ai",
    "unsloth",
    "jan",
    "koboldcpp",
    "kobold",
    "text-generation-webui",
    "oobabooga",
    "llamafile",
    "mlx",
)

# URL fragments that mean "a local GPU, exposed over the network".
# Unsloth serves on *.unsloth.app; tunnels (cloudflare/ngrok/loca.lt) expose a
# local port; these are still local inference, so the local profile applies.
LOCAL_URL_MARKERS = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    ".unsloth.app",
    "trycloudflare.com",
    "ngrok.io",
    "ngrok-free.app",
    "loca.lt",
    "serveo.net",
)


def model_supports_vision(name: str, local: bool = False) -> bool:
    """Name-based vision detection for models without modality metadata.

    Local models are judged only by local model names: a local server serving a
    model called "gpt-4o" is not necessarily a vision model.
    """
    lowered = str(name or "").lower()
    if not lowered:
        return False
    if any(hint in lowered for hint in VISION_HINTS):
        return True
    if local:
        return False
    return any(hint in lowered for hint in CLOUD_VISION_HINTS)


def is_local_provider(provider_id: str, base_url: str = "") -> bool:
    """True when a provider points at a local runtime."""
    pid = str(provider_id or "").lower()
    if any(pid == known or pid.startswith(known) for known in LOCAL_PROVIDER_IDS):
        return True
    url = str(base_url or "").lower()
    return any(marker in url for marker in LOCAL_URL_MARKERS)


def _port_open(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_json(url: str, timeout: float) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback only
        raw = response.read(2 * 1024 * 1024)
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None


def _model_names(payload: Any) -> list[str]:
    """Extract model ids from either an OpenAI-style or Ollama-style payload."""
    names: list[str] = []
    if not isinstance(payload, dict):
        return names
    data = payload.get("data")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                model = item.get("id") or item.get("name") or item.get("model")
                if model:
                    names.append(str(model))
            elif isinstance(item, str):
                names.append(item)
    models = payload.get("models")
    if isinstance(models, list):
        for item in models:
            if isinstance(item, dict):
                model = item.get("name") or item.get("model") or item.get("id")
                if model:
                    names.append(str(model))
            elif isinstance(item, str):
                names.append(item)
    return names


# Executables that indicate a runtime is installed but not started.
# Names are specific on purpose: generic names like "main" cause false hits.
RUNTIME_BINARIES = {
    "ollama": ("ollama", "ollama.exe"),
    "llama.cpp": ("llama-server", "llama-server.exe", "llama-server.exe.manifest"),
    "lmstudio": ("lms", "lmstudio", "LM Studio.exe"),
    "vllm": ("vllm", "vllm.exe"),
    "localai": ("local-ai", "local-ai.exe"),
    "jan": ("jan", "jan.exe"),
    "koboldcpp": ("koboldcpp", "koboldcpp.exe"),
    "text-generation-webui": ("webui", "webui.exe"),
}

# Common install locations checked when the binary is not on PATH.
RUNTIME_INSTALL_DIRS = {
    "ollama": ("%LOCALAPPDATA%\\Programs\\Ollama", "%USERPROFILE%\\.ollama"),
    "llama.cpp": ("%USERPROFILE%\\llama.cpp", "%USERPROFILE%\\llama-server"),
    "lmstudio": ("%LOCALAPPDATA%\\Programs\\LM Studio",),
    "jan": ("%LOCALAPPDATA%\\Programs\\Jan", "%APPDATA%\\Jan"),
}

# Only files with these extensions count as executables.
EXECUTABLE_SUFFIXES = {".exe", ".bat", ".cmd", ".ps1"}


def _is_executable(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in EXECUTABLE_SUFFIXES


def _expand_dirs(template: str) -> list[Path]:
    raw = os.path.expandvars(template)
    return [Path(raw)] if raw else []


def find_runtime_binary(name: str) -> str | None:
    """Locate an installed runtime binary (PATH first, then known folders)."""
    for candidate in RUNTIME_BINARIES.get(name, ()):
        found = shutil.which(candidate)
        if found:
            return found
    for template in RUNTIME_INSTALL_DIRS.get(name, ()):
        for folder in _expand_dirs(template):
            if not folder.exists():
                continue
            for candidate in RUNTIME_BINARIES.get(name, ()):
                direct = folder / candidate
                if _is_executable(direct):
                    return str(direct)
                try:
                    children = sorted(folder.glob(f"**/{candidate}"))
                except OSError:
                    continue
                for child in children:
                    if _is_executable(child):
                        return str(child)
    return None


@dataclass
class RuntimeStatus:
    """Reachability and contents of one local runtime."""

    name: str
    host: str
    port: int
    reachable: bool = False
    openai_compatible: bool = False
    models: list[str] = field(default_factory=list)
    error: str = ""
    installed_at: str | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/v1"

    @property
    def vision_models(self) -> list[str]:
        return [m for m in self.models if model_supports_vision(m, local=True)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "reachable": self.reachable,
            "openai_compatible": self.openai_compatible,
            "base_url": self.base_url if self.openai_compatible else "",
            "models": self.models,
            "vision_models": self.vision_models,
            "error": self.error,
            "installed_at": self.installed_at,
            "state": self.state,
        }

    @property
    def state(self) -> str:
        if self.reachable:
            return "running"
        if self.installed_at:
            return "installed-not-running"
        return "not-installed"


def probe_runtime(
    name: str,
    spec: dict[str, Any],
    host: str = "127.0.0.1",
    timeout: float = DEFAULT_TIMEOUT,
) -> RuntimeStatus:
    """Probe one runtime: TCP check first, then a models endpoint."""
    port = int(spec.get("port", 0))
    status = RuntimeStatus(
        name=name,
        host=host,
        port=port,
        openai_compatible=bool(spec.get("openai", False)),
        installed_at=find_runtime_binary(name),
    )
    if not port or not _port_open(host, port):
        status.error = "port closed"
        return status

    last_error = ""
    for path in spec.get("paths", []):
        url = f"http://{host}:{port}{path}"
        try:
            payload = _http_json(url, timeout)
        except urllib.error.URLError as exc:
            last_error = str(exc.reason)
            continue
        except (TimeoutError, socket.timeout):
            last_error = "timeout"
            continue
        except OSError as exc:
            last_error = str(exc)
            continue
        if payload is None:
            last_error = "no json"
            continue
        names = _model_names(payload)
        status.models = names
        status.reachable = True
        status.error = ""
        return status

    status.reachable = True
    status.error = last_error or "no models endpoint"
    return status


def detect_runtimes(
    host: str = "127.0.0.1",
    timeout: float = DEFAULT_TIMEOUT,
    only_reachable: bool = False,
) -> list[RuntimeStatus]:
    """Probe all known local runtimes."""
    results: list[RuntimeStatus] = []
    for name, spec in RUNTIMES.items():
        status = probe_runtime(name, spec, host=host, timeout=timeout)
        if only_reachable and not status.reachable:
            continue
        results.append(status)
    return results


def describe_role(model_name: str, provider_id: str = "", base_url: str = "") -> dict[str, Any]:
    """Recommended Vi3ion role for a model: eyes (visionless) or assistant."""
    local = is_local_provider(provider_id, base_url)
    vision = model_supports_vision(model_name, local=local)
    if vision:
        role = "assistant"
        reason = "model name indicates image input; your own vision is primary"
    elif local:
        role = "eyes"
        reason = "local runtime model without image input; Vi3ion is the eyes"
    else:
        role = "eyes"
        reason = "no image input detected; Vi3ion is the eyes"
    return {
        "model": model_name,
        "provider": provider_id,
        "local": local,
        "vision_capable": vision,
        "role": role,
        "reason": reason,
    }


def local_stack_report(
    host: str = "127.0.0.1",
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Full report: reachable runtimes, their models, and Vi3ion's role."""
    runtimes = detect_runtimes(host=host, timeout=timeout)
    reachable = [r for r in runtimes if r.reachable]
    stopped = [r for r in runtimes if not r.reachable and r.installed_at]
    vision_models = sorted({m for r in reachable for m in r.vision_models})
    text_models = sorted({m for r in reachable for m in r.models if m not in r.vision_models})
    roles = [
        describe_role(model, provider_id=r.name)
        for r in reachable
        for model in r.models
    ]
    return {
        "ok": True,
        "host": host,
        "runtimes": [r.to_dict() for r in reachable],
        "stopped_runtimes": [
            {"name": r.name, "port": r.port, "installed_at": r.installed_at}
            for r in stopped
        ],
        "offline_runtimes": [r.name for r in runtimes if not r.reachable and not r.installed_at],
        "vision_models": vision_models,
        "text_models": text_models,
        "roles": roles,
        "recommendation": (
            "A local vision model is serving: keep Vi3ion as an assistant."
            if vision_models
            else "No local vision model detected: Vi3ion is the eyes for local models."
        ),
        "notes": [
            "Vi3ion never calls the model; it only measures images.",
            "Use detail='compact' for small local models to save context.",
        ],
    }
