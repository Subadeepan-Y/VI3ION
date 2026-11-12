"""Remote semantic provider (OpenAI-compatible chat completions).

Opt-in only. The image leaves the machine when this provider is enabled.
Boxes may be normalized (0..1) or pixels; they are returned in the frame of the
image argument.
"""

from __future__ import annotations

import base64
import json
import re
import time

import cv2
import numpy as np

from ...config import Settings
from ...schemas import BBox
from .interface import SemanticCaption, SemanticObject, SemanticResult


def _httpx():
    """Import httpx lazily: it is only needed for the opt-in remote provider."""
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(
            "the remote semantic provider needs httpx: pip install 'vi3ion[semantic]'"
        ) from exc
    return httpx

PROMPT = """You are a visual perception component inside a reverse-engineering tool.
Describe only what is visibly present. Do not guess hidden behaviour.

Return JSON only, matching:
{
  "description": "one or two factual sentences",
  "objects": [
    {"label": "button|input|text|icon|card|table|chart|photo|logo|window|other",
     "bbox": [x0, y0, x1, y1],
     "confidence": 0.0-1.0}
  ]
}

Coordinates are normalized 0..1 relative to the image (x right, y down).
Only return objects you can actually see. No markdown fences.
"""


class RemoteSemanticProvider:
    name = "remote"
    version = "chat-completions-v1"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = settings.semantic_model

    def _encode(self, bgr: np.ndarray) -> str:
        height, width = bgr.shape[:2]
        max_dim = 1400
        if max(width, height) > max_dim:
            scale = max_dim / max(width, height)
            bgr = cv2.resize(bgr, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
        ok, buffer = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            raise RuntimeError("could not encode image for remote provider")
        return base64.b64encode(buffer.tobytes()).decode("ascii")

    def detect(
        self,
        image: np.ndarray,
        regions: list[BBox] | None = None,
    ) -> SemanticResult:
        started = time.perf_counter()
        if not self.settings.semantic_api_key or not self.model:
            return SemanticResult(
                provider=self.name,
                warning="remote semantic provider requires VI3ION_SEMANTIC_API_KEY and VI3ION_SEMANTIC_MODEL",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        height, width = image.shape[:2]
        data_url = f"data:image/jpeg;base64,{self._encode(image)}"
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 700,
            "messages": [
                {"role": "system", "content": PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Screenshot, {width}x{height} pixels."},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        }
        url = self.settings.semantic_base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {self.settings.semantic_api_key}"}
        try:
            httpx = _httpx()
            with httpx.Client(timeout=self.settings.semantic_timeout_s) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                body = response.json()
            content = body["choices"][0]["message"]["content"]
            parsed = _parse_json(content)
        except Exception as exc:  # noqa: BLE001
            return SemanticResult(
                provider=self.name,
                model=self.model,
                warning=f"remote semantic call failed: {type(exc).__name__}: {exc}",
                duration_ms=(time.perf_counter() - started) * 1000,
            )

        objects: list[SemanticObject] = []
        for item in parsed.get("objects", [])[:40]:
            bbox = None
            raw = item.get("bbox")
            if isinstance(raw, (list, tuple)) and len(raw) == 4:
                try:
                    x0, y0, x1, y1 = (float(v) for v in raw)
                    if max(abs(v) for v in (x0, y0, x1, y1)) <= 1.5:
                        x0, x1 = x0 * width, x1 * width
                        y0, y1 = y0 * height, y1 * height
                    bbox = BBox(x0=x0, y0=y0, x1=x1, y1=y1).clamp(width, height)
                except ValueError:
                    bbox = None
            objects.append(
                SemanticObject(
                    label=str(item.get("label", "object"))[:60],
                    bbox=bbox,
                    confidence=max(0.0, min(1.0, float(item.get("confidence", 0.5)))),
                    source=self.name,
                )
            )
        captions: list[SemanticCaption] = []
        if parsed.get("description"):
            captions.append(
                SemanticCaption(
                    text=str(parsed["description"])[:300],
                    bbox=None,
                    confidence=0.6,
                    source=self.name,
                )
            )
        return SemanticResult(
            objects=objects,
            captions=captions,
            provider=self.name,
            model=self.model,
            duration_ms=(time.perf_counter() - started) * 1000,
        )


def _parse_json(content: str) -> dict:
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {"description": text, "objects": []}
    try:
        parsed = json.loads(text[start : end + 1])
        return parsed if isinstance(parsed, dict) else {"description": text, "objects": []}
    except json.JSONDecodeError:
        return {"description": text, "objects": []}
