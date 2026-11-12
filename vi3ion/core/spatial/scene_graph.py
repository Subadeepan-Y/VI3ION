"""Scene graph construction from detected boxes.

The graph is a convenience view over measured relationships. The measurements
are the evidence; the graph is not a separate source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...schemas import BBox


@dataclass
class SceneElement:
    id: str
    label: str
    bbox: BBox
    kind: str
    text: str | None = None

    def node(self) -> dict:
        node = {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "bbox": self.bbox.as_rounded(),
        }
        if self.text and self.text != self.label:
            node["text"] = self.text[:120]
        return node


@dataclass
class SceneEdge:
    subject: str
    predicate: str
    object: str
    measurements: dict = field(default_factory=dict)
    confidence: float = 1.0

    def as_dict(self) -> dict:
        return {
            "source": self.subject,
            "predicate": self.predicate,
            "target": self.object,
            **self.measurements,
        }


@dataclass
class SceneGraph:
    nodes: list[SceneElement] = field(default_factory=list)
    edges: list[SceneEdge] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    columns: list[list[str]] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "nodes": [node.node() for node in self.nodes],
            "edges": [edge.as_dict() for edge in self.edges],
            "rows": self.rows,
            "columns": self.columns,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
        }
