import { useEffect, useMemo, useRef, useState } from "react";
import type { EvidenceItem, RemoteImage, ToolPayload } from "../types";
import { bboxLabel } from "../api";

interface Props {
  image: RemoteImage;
  evidence: EvidenceItem[];
  selected: number[] | null;
  onSelect: (bbox: number[] | null) => void;
  onInspect: (bbox: number[]) => void;
  inspecting: boolean;
  regionResult: ToolPayload | null;
}

type Point = { x: number; y: number };

const KIND_COLORS: Record<string, string> = {
  shape: "#4ee1c1",
  text: "#f5b942",
  object: "#b98cff",
  relationship: "#6aa9ff",
};

function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return { ref, size };
}

function normalize(start: Point, end: Point): [number, number, number, number] {
  return [
    Math.min(start.x, end.x),
    Math.min(start.y, end.y),
    Math.max(start.x, end.x),
    Math.max(start.y, end.y),
  ];
}

export default function ImageViewer({
  image,
  evidence,
  selected,
  onSelect,
  onInspect,
  inspecting,
  regionResult,
}: Props) {
  const { ref: viewportRef, size } = useElementSize<HTMLDivElement>();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState<Point>({ x: 0, y: 0 });
  const [panMode, setPanMode] = useState(false);
  const [drag, setDrag] = useState<{ start: Point; current: Point } | null>(null);
  const [panStart, setPanStart] = useState<{ pointer: Point; pan: Point } | null>(null);
  const [hover, setHover] = useState<Point | null>(null);
  const [showShapes, setShowShapes] = useState(true);
  const [showText, setShowText] = useState(true);
  const [showObjects, setShowObjects] = useState(false);
  const [showRelations, setShowRelations] = useState(false);

  useEffect(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setDrag(null);
    setPanStart(null);
  }, [image.image_id]);

  const fit = useMemo(() => {
    if (!size.width || !size.height) return 0;
    return Math.min((size.width - 48) / image.width, (size.height - 48) / image.height);
  }, [size, image.width, image.height]);

  const displayWidth = Math.max(1, image.width * fit * zoom);
  const displayHeight = Math.max(1, image.height * fit * zoom);

  const visibleEvidence = evidence.filter((item) => {
    if (!item.bbox) return false;
    if (item.kind === "shape") return showShapes;
    if (item.kind === "text") return showText;
    if (item.kind === "object") return showObjects;
    if (item.kind === "relationship") return showRelations;
    return false;
  });

  function toImage(event: React.PointerEvent | React.MouseEvent): Point {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    const rect = svg.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / Math.max(1, rect.width)) * image.width;
    const y = ((event.clientY - rect.top) / Math.max(1, rect.height)) * image.height;
    return {
      x: Math.max(0, Math.min(image.width, x)),
      y: Math.max(0, Math.min(image.height, y)),
    };
  }

  function handlePointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    const point = toImage(event);
    viewportRef.current?.setPointerCapture(event.pointerId);
    if (panMode || event.shiftKey) {
      setPanStart({ pointer: { x: event.clientX, y: event.clientY }, pan });
      return;
    }
    setDrag({ start: point, current: point });
  }

  function handlePointerMove(event: React.PointerEvent<HTMLDivElement>) {
    const point = toImage(event);
    setHover(point);
    if (panStart) {
      setPan({
        x: panStart.pan.x + (event.clientX - panStart.pointer.x),
        y: panStart.pan.y + (event.clientY - panStart.pointer.y),
      });
    } else if (drag) {
      setDrag({ start: drag.start, current: point });
    }
  }

  function handlePointerUp(event: React.PointerEvent<HTMLDivElement>) {
    viewportRef.current?.releasePointerCapture(event.pointerId);
    setPanStart(null);
    if (drag) {
      const box = normalize(drag.start, drag.current);
      if (box[2] - box[0] > 5 && box[3] - box[1] > 5) {
        onSelect(box);
      }
    }
    setDrag(null);
  }

  function handleWheel(event: React.WheelEvent<HTMLDivElement>) {
    event.preventDefault();
    const direction = event.deltaY > 0 ? -1 : 1;
    setZoom((value) => Math.max(0.4, Math.min(6, value + direction * 0.15)));
  }

  function resetView() {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }

  const dragBox = drag ? normalize(drag.start, drag.current) : null;
  const selectedKey = selected ? selected.map((value) => Math.round(value)).join(",") : "";

  return (
    <div className="viewer-shell">
      <div className="viewer-toolbar">
        <div className="toggle-row">
          <button
            className={`chip ${showShapes ? "on" : ""}`}
            onClick={() => setShowShapes((value) => !value)}
          >
            <span className="dot" style={{ background: KIND_COLORS.shape }} /> Shapes
          </button>
          <button
            className={`chip ${showText ? "on" : ""}`}
            onClick={() => setShowText((value) => !value)}
          >
            <span className="dot" style={{ background: KIND_COLORS.text }} /> Text
          </button>
          <button
            className={`chip ${showObjects ? "on" : ""}`}
            onClick={() => setShowObjects((value) => !value)}
          >
            <span className="dot" style={{ background: KIND_COLORS.object }} /> Objects
          </button>
          <button
            className={`chip ${showRelations ? "on" : ""}`}
            onClick={() => setShowRelations((value) => !value)}
          >
            <span className="dot" style={{ background: KIND_COLORS.relationship }} /> Relations
          </button>
        </div>
        <div className="toggle-row">
          <button className={`chip ${panMode ? "on" : ""}`} onClick={() => setPanMode((v) => !v)}>
            Pan mode
          </button>
          <button className="chip" onClick={() => setZoom((v) => Math.max(0.4, v - 0.2))}>
            −
          </button>
          <span className="zoom-readout">{Math.round(zoom * 100)}%</span>
          <button className="chip" onClick={() => setZoom((v) => Math.min(6, v + 0.2))}>
            +
          </button>
          <button className="chip" onClick={resetView}>
            Reset
          </button>
        </div>
      </div>

      <div className="viewer-body">
        <div
          className={`viewport ${panMode ? "panning" : ""} ${drag ? "selecting" : ""}`}
          ref={viewportRef}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={() => setHover(null)}
          onWheel={handleWheel}
        >
          {fit === 0 ? null : (
            <div
              className="zoom-layer"
              style={{
                width: displayWidth,
                height: displayHeight,
                transform: `translate(${pan.x}px, ${pan.y}px)`,
              }}
            >
              <img
                src={`${image.file_url}?v=${encodeURIComponent(image.image_id)}`}
                alt=""
                draggable={false}
                style={{ width: displayWidth, height: displayHeight }}
              />
              <svg
                ref={svgRef}
                className="viewer-svg"
                viewBox={`0 0 ${image.width} ${image.height}`}
                preserveAspectRatio="none"
              >
                {visibleEvidence.map((item) => {
                  const box = item.bbox as number[];
                  const key = box.map((value) => Math.round(value)).join(",");
                  const isSelected = key === selectedKey;
                  const color = KIND_COLORS[item.kind] || "#8b98a5";
                  return (
                    <rect
                      key={item.evidence_id}
                      x={box[0]}
                      y={box[1]}
                      width={Math.max(0.5, box[2] - box[0])}
                      height={Math.max(0.5, box[3] - box[1])}
                      fill={isSelected ? "rgba(255,255,255,0.16)" : "transparent"}
                      stroke={isSelected ? "#ffffff" : color}
                      strokeWidth={isSelected ? 3 : item.kind === "shape" ? 1.6 : 1.2}
                      opacity={isSelected ? 1 : 0.85}
                      vectorEffect="non-scaling-stroke"
                    >
                      <title>{`${item.kind}: ${item.label}\n[${bboxLabel(box)}]`}</title>
                    </rect>
                  );
                })}
                {selected && (
                  <rect
                    x={selected[0]}
                    y={selected[1]}
                    width={selected[2] - selected[0]}
                    height={selected[3] - selected[1]}
                    fill="none"
                    stroke="#ffffff"
                    strokeWidth={2}
                    strokeDasharray="8 6"
                    vectorEffect="non-scaling-stroke"
                  />
                )}
                {dragBox && (
                  <rect
                    x={dragBox[0]}
                    y={dragBox[1]}
                    width={dragBox[2] - dragBox[0]}
                    height={dragBox[3] - dragBox[1]}
                    fill="rgba(78,225,193,0.12)"
                    stroke="#4ee1c1"
                    strokeWidth={1.5}
                    strokeDasharray="6 4"
                    vectorEffect="non-scaling-stroke"
                  />
                )}
              </svg>
            </div>
          )}
          <div className="viewer-hud">
            {hover ? `x ${Math.round(hover.x)}  y ${Math.round(hover.y)}` : "drag to select · shift+drag to pan"}
          </div>
        </div>

        <aside className="region-panel">
          <div className="panel-heading">
            <span>Region probe</span>
            <span className="mono subtle">original px</span>
          </div>
          <div className="region-box mono">
            {selected ? `[${selected.map((v) => Math.round(v)).join(", ")}]` : "no selection"}
          </div>
          <div className="row-actions">
            <button
              className="primary"
              disabled={!selected || inspecting}
              onClick={() => selected && onInspect(selected)}
            >
              {inspecting ? "Reading pixels…" : "Inspect region"}
            </button>
            <button className="ghost" disabled={!selected} onClick={() => onSelect(null)}>
              Clear
            </button>
          </div>

          {regionResult && (
            <div className="region-result">
              <div className="panel-divider" />
              <div className="micro-label">Last inspection</div>
              <p className="summary small">{regionResult.summary}</p>
              {regionResult.warnings?.map((warning) => (
                <p className="warning small" key={warning}>
                  {warning}
                </p>
              ))}
              <div className="micro-label">
                Evidence {regionResult.evidence_returned ?? 0}/{regionResult.evidence_total ?? 0}
              </div>
              <div className="mini-evidence">
                {(regionResult.evidence ?? []).slice(0, 14).map((item) => (
                  <div className="mini-evidence-row" key={item.evidence_id}>
                    <span className={`kind-stripe ${item.kind}`} />
                    <span className="mini-label" title={item.label}>
                      {item.label}
                    </span>
                    <span className="mono subtle tiny">{bboxLabel(item.bbox)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
