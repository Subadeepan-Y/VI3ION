import { useEffect, useState } from "react";
import { api } from "../api";
import type { ToolDefinition, ToolPayload } from "../types";

interface Props {
  imageId: string | null;
  selected: number[] | null;
}

function templateFor(tool: string, imageId: string | null, region: number[] | null): Record<string, unknown> {
  const fallbackRegion = region ?? [320, 580, 710, 670];
  if (tool === "inspect_image") {
    return { image_id: imageId, detail: "compact", tasks: [] };
  }
  if (tool === "inspect_region") {
    return { image_id: imageId, region: fallbackRegion, detail: "standard" };
  }
  if (tool === "query_evidence") {
    return { image_id: imageId, kind: "text", limit: 20 };
  }
  if (tool === "verify_claim") {
    return { image_id: imageId, claim: "The image contains the text \"Settings\"" };
  }
  if (tool === "compare_regions") {
    return {
      image_id: imageId,
      region_a: [329, 599, 491, 653],
      region_b: [509, 599, 692, 654],
      aspects: ["position", "size", "color", "text"],
    };
  }
  return {};
}

export default function AgentSimulator({ imageId, selected }: Props) {
  const [tools, setTools] = useState<ToolDefinition[]>([]);
  const [tool, setTool] = useState("inspect_image");
  const [args, setArgs] = useState(() => JSON.stringify(templateFor("inspect_image", imageId, selected), null, 2));
  const [result, setResult] = useState<ToolPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [history, setHistory] = useState<Array<{ tool: string; summary: string; result: ToolPayload }>>([]);

  useEffect(() => {
    api.tools().then((data) => setTools(data.tools)).catch(() => undefined);
  }, []);

  useEffect(() => {
    setArgs(JSON.stringify(templateFor(tool, imageId, selected), null, 2));
  }, [tool, imageId]);

  async function run() {
    setError(null);
    setRunning(true);
    try {
      const parsed = JSON.parse(args) as Record<string, unknown>;
      const payload = await api.runTool(tool, parsed);
      setResult(payload);
      setHistory((items) =>
        [{ tool, summary: payload.summary ?? payload.error ?? "", result: payload }, ...items].slice(0, 6),
      );
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      setResult(null);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="agent-grid">
      <div className="agent-form">
        <div className="panel-heading">
          <span>Tool call</span>
          <span className="mono subtle">same 5 tools the MCP server exposes</span>
        </div>
        <div className="tool-picker">
          {(tools.length ? tools : FALLBACK_TOOLS).map((item) => (
            <button
              key={item.name}
              className={`tool-card ${tool === item.name ? "on" : ""}`}
              onClick={() => setTool(item.name)}
            >
              <span className="mono">{item.name}</span>
              <span className="tool-description">{item.description}</span>
            </button>
          ))}
        </div>

        <label className="micro-label">Arguments (JSON)</label>
        <textarea
          className="json-input"
          value={args}
          spellCheck={false}
          onChange={(event) => setArgs(event.target.value)}
        />
        <div className="row-actions">
          <button className="primary" onClick={run} disabled={running || !imageId}>
            {running ? "Running…" : "Send to Vi3ion"}
          </button>
          <button
            className="ghost"
            onClick={() => setArgs(JSON.stringify(templateFor(tool, imageId, selected), null, 2))}
          >
            Reset args
          </button>
        </div>
        {error && <p className="error small">{error}</p>}
        {!imageId && <p className="warning small">Select an image first.</p>}

        <div className="panel-divider" />
        <div className="micro-label">Session calls</div>
        <div className="history">
          {history.length === 0 && <span className="subtle small">No calls yet.</span>}
          {history.map((entry, index) => (
            <button
              key={`${entry.tool}-${index}`}
              className="history-row"
              onClick={() => {
                setResult(entry.result);
                setTool(entry.tool);
              }}
            >
              <span className="mono">{entry.tool}</span>
              <span className="history-summary">{entry.summary}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="agent-result">
        <div className="panel-heading">
          <span>Response</span>
          {result && (
            <span className="mono subtle">
              {result.cached ? "cached" : "fresh"} · {result.evidence_total ?? 0} evidence
            </span>
          )}
        </div>
        {!result && <div className="empty-state small">Run a tool to see the exact payload an agent receives.</div>}
        {result && (
          <>
            <p className="summary">{result.summary}</p>
            {result.warnings?.map((warning) => (
              <p key={warning} className="warning small">
                {warning}
              </p>
            ))}
            <div className="response-meta">
              <span className="mono tiny">image {result.image_id}</span>
              {result.timings_ms?.total_ms !== undefined && (
                <span className="mono tiny">{Math.round(result.timings_ms.total_ms)} ms</span>
              )}
              {result.truncated && <span className="badge amber">truncated</span>}
            </div>
            <pre className="json-block tall">{JSON.stringify(result, null, 2)}</pre>
          </>
        )}
      </div>
    </div>
  );
}

const FALLBACK_TOOLS: ToolDefinition[] = [
  { name: "inspect_image", description: "Initial analysis", arguments: {} },
  { name: "inspect_region", description: "Targeted crop inspection", arguments: {} },
  { name: "query_evidence", description: "Stored evidence lookup", arguments: {} },
  { name: "verify_claim", description: "Measured claim verdict", arguments: {} },
  { name: "compare_regions", description: "Two-region comparison", arguments: {} },
];
