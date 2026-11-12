import { useMemo, useState } from "react";
import type { EvidenceItem } from "../types";
import { bboxLabel } from "../api";

interface Props {
  evidence: EvidenceItem[];
  selected: number[] | null;
  onSelect: (bbox: number[] | null) => void;
}

const KINDS = ["all", "text", "shape", "relationship", "color", "object", "note", "image"];

export default function EvidencePanel({ evidence, selected, onSelect }: Props) {
  const [kind, setKind] = useState("all");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return evidence.filter((item) => {
      if (kind !== "all" && item.kind !== kind) return false;
      if (!needle) return true;
      const haystack = `${item.label} ${JSON.stringify(item.attributes)}`.toLowerCase();
      return haystack.includes(needle);
    });
  }, [evidence, kind, query]);

  const counts = useMemo(() => {
    const map: Record<string, number> = {};
    for (const item of evidence) map[item.kind] = (map[item.kind] ?? 0) + 1;
    return map;
  }, [evidence]);

  return (
    <div className="evidence-panel">
      <div className="evidence-toolbar">
        <div className="toggle-row wrap">
          {KINDS.map((item) => (
            <button
              key={item}
              className={`chip ${kind === item ? "on" : ""}`}
              onClick={() => setKind(item)}
            >
              {item}
              <span className="count">{item === "all" ? evidence.length : counts[item] ?? 0}</span>
            </button>
          ))}
        </div>
        <input
          className="text-input narrow"
          placeholder="Filter label or attribute…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      <div className="evidence-head">
        <span>Kind</span>
        <span>Label</span>
        <span>BBox (x0, y0, x1, y1)</span>
        <span>Conf.</span>
        <span>Method</span>
      </div>

      <div className="evidence-list">
        {filtered.length === 0 && <div className="empty-state small">No evidence matches this filter.</div>}
        {filtered.map((item) => {
          const isOpen = expanded === item.evidence_id;
          const isSelected =
            selected && item.bbox
              ? selected.every((value, index) => Math.abs(value - item.bbox![index]) < 0.6)
              : false;
          return (
            <div className="evidence-item" key={item.evidence_id}>
              <button
                className={`evidence-row ${isSelected ? "selected" : ""}`}
                onClick={() => {
                  onSelect(item.bbox ?? null);
                  setExpanded(isOpen ? null : item.evidence_id);
                }}
              >
                <span className={`kind-badge ${item.kind}`}>{item.kind}</span>
                <span className="evidence-label" title={item.label}>
                  {item.label}
                  {!item.observed && <span className="inferred">inferred</span>}
                </span>
                <span className="mono subtle">
                  {item.bbox ? `[${bboxLabel(item.bbox)}]` : "—"}
                </span>
                <span className="mono">
                  {item.confidence === null || item.confidence === undefined
                    ? "—"
                    : `${Math.round(item.confidence * 100)}%`}
                </span>
                <span className="mono subtle tiny">{item.provenance?.method}</span>
              </button>
              {isOpen && (
                <div className="evidence-detail">
                  <div className="detail-meta">
                    <span className="mono tiny">{item.evidence_id}</span>
                    <span className="mono tiny">
                      {item.provenance?.module} / {item.provenance?.method} v{item.provenance?.version}
                    </span>
                    <span className="mono tiny">scope: {item.scope}</span>
                  </div>
                  <pre className="json-block">{JSON.stringify(item.attributes, null, 2)}</pre>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="evidence-footer">
        {filtered.length} shown · {evidence.length} total · coordinates in original pixels
      </div>
    </div>
  );
}
