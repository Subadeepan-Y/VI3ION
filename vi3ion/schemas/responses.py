"""Response envelope returned by every Vi3ion tool."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from .common import Evidence, VerificationResult


class ToolResponse(BaseModel):
    ok: bool = True
    tool: str
    image_id: str | None = None
    session_id: str | None = None
    summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    evidence_total: int = 0
    evidence_returned: int = 0
    truncated: bool = False
    cached: bool = False
    warnings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    verification: VerificationResult | None = None
    error: str | None = None

    def to_payload(self, detail: str = "standard") -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": self.ok, "tool": self.tool}
        if self.error:
            payload["error"] = self.error
        if self.image_id:
            payload["image_id"] = self.image_id
        if self.session_id:
            payload["session_id"] = self.session_id
        if self.summary:
            payload["summary"] = self.summary
        if self.data:
            payload["data"] = self.data
        if self.evidence:
            payload["evidence"] = [e.compact(detail) for e in self.evidence[: self.evidence_returned]]
        if self.evidence_total:
            payload["evidence_total"] = self.evidence_total
            payload["truncated"] = self.truncated
        if self.cached:
            payload["cached"] = True
        if self.warnings:
            payload["warnings"] = self.warnings
        if self.next_actions:
            payload["next_actions"] = self.next_actions
        if self.verification:
            payload["verification"] = self.verification.model_dump(mode="json")
        if self.timings_ms:
            payload["timings_ms"] = {k: round(v, 1) for k, v in self.timings_ms.items()}
        return payload

    def to_json(self, detail: str = "standard", pretty: bool = False) -> str:
        return json.dumps(
            self.to_payload(detail),
            ensure_ascii=False,
            indent=2 if pretty else None,
        )
