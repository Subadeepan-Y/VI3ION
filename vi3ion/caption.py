"""Caption layer: small local VLM served by Ollama.

Produces the ``Scene description`` section of the brief. The VLM is lazy-loaded
once per process; results are cached by image SHA-256 + model name. If the VLM
is unavailable, the brief says so explicitly — the section is never omitted
silently.

No object-detection models are used. This is the only semantic component.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

OLLAMA_BASE = os.environ.get("VI3ION_OLLAMA_BASE", "http://127.0.0.1:11434")
MODEL = os.environ.get("VI3ION_VLM_MODEL", "moondream")
TIMEOUT_S = float(os.environ.get("VI3ION_CAPTION_TIMEOUT_S", "60"))
CACHE_PATH = Path("data") / "caption_cache.json"
MAX_WORDS = 150

PROMPT = (
    "Describe this screenshot for a developer who cannot see it. In 3 to 6 "
    "sentences: what kind of interface or scene it is, the main visual "
    "elements and where they are (use top, bottom, left, right, centre), and "
    "anything that looks like an error or a warning. Do not transcribe text; "
    'it has been read separately. Say "unclear" for anything you cannot tell.'
)


def _load_cache() -> dict[str, str]:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict[str, str]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")


def ollama_available(timeout: float = 2.0) -> bool:
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(f"{OLLAMA_BASE}/api/tags")
        return response.status_code == 200
    except Exception:
        return False


def _strip_quoted_ocr(text: str, ocr_texts: list[str]) -> str:
    """Remove quoted spans that duplicate OCR text (OCD: no duplication)."""
    import re

    cleaned = text
    for match in re.findall(r"[\"']([^\"']{4,})[\"']", text):
        norm = re.sub(r"[^a-z0-9]+", "", match.lower())
        if any(
            norm and norm in re.sub(r"[^a-z0-9]+", "", t.lower())
            for t in ocr_texts
            if len(t) >= 4
        ):
            cleaned = cleaned.replace(match, "").replace('""', "").strip()
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _cap_words(text: str, max_words: int = MAX_WORDS) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " …"


def caption(
    image_bytes: bytes,
    ocr_texts: list[str] | None = None,
    model: str = MODEL,
    force: bool = False,
) -> tuple[str | None, str | None]:
    """Return (caption_text, error). Caption text is None when unavailable."""
    digest = hashlib.sha256(image_bytes).hexdigest()
    key = f"{model}:{digest}"
    cache = _load_cache()
    if not force and key in cache:
        return cache[key], None

    if not ollama_available():
        reason = "local VLM (Ollama) is not reachable"
        return None, reason

    b64 = base64.b64encode(image_bytes).decode("ascii")
    started = time.perf_counter()
    payload: dict[str, Any] = {
        "model": model,
        "prompt": PROMPT,
        "images": [b64],
        "stream": False,
        "options": {"num_predict": 200},
    }
    try:
        with httpx.Client(timeout=TIMEOUT_S) as client:
            response = client.post(f"{OLLAMA_BASE}/api/generate", json=payload)
            response.raise_for_status()
            body = response.json()
        raw = str(body.get("response", "")).strip()
        if not raw:
            return None, "VLM returned an empty response"
        cleaned = _strip_quoted_ocr(raw, ocr_texts or [])
        final = _cap_words(cleaned)
        cache[key] = final
        _save_cache(cache)
        return final, None
    except Exception as exc:  # noqa: BLE001
        return None, f"VLM call failed: {type(exc).__name__}: {exc}"
