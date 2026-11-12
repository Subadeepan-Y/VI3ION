"""Session context. Project context must never silently alter visual evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class SessionContext:
    session_id: str
    image_id: str | None = None
    agent: str = "unknown"
    task: str | None = None
    inspected_regions: list[list[float]] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def note(self, text: str) -> None:
        self.notes.append(text)

    def visited(self, region: list[float]) -> None:
        if region not in self.inspected_regions:
            self.inspected_regions.append(region)
