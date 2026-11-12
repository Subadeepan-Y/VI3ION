import { useState } from "react";
import { api } from "../api";
import type { ToolPayload, Verification } from "../types";

interface Props {
  imageId: string | null;
}

const PRESETS = [
  "The image contains the text \"Save\"",
  "\"Save\" is aligned with \"Cancel\"",
  "\"Save\" is 30 pixels to the left of \"Cancel\"",
  "The Save button is blue",
  "The image is 1280x800",
];

export default function VerifyPanel({ imageId }: Props) {
  const [claim, setClaim] = useState(PRESETS[0]);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [payload, setPayload] = useState<ToolPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [history, setHistory] = useState<Verification[]>([]);

  async function run(nextClaim?: string) {
    const text = (nextClaim ?? claim).trim();
    if (!imageId || !text) return;
    setRunning(true);
    setError(null);
    try {
      const result = await api.verify(imageId, text);
      setPayload(result);
      setVerification(result.verification ?? null);
      if (result.verification) {
        setHistory((items) => [result.verification!, ...items].slice(0, 8));
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="verify-grid">
      <div className="verify-form">
        <div className="panel-heading">
          <span>Claim verification</span>
          <span className="mono subtle">measured, not judged</span>
        </div>
        <label className="micro-label">Claim</label>
        <textarea
          className="claim-input"
          value={claim}
          onChange={(event) => setClaim(event.target.value)}
          placeholder='e.g. "Save" is aligned with "Cancel"'
        />
        <div className="preset-row">
          {PRESETS.map((preset) => (
            <button
              key={preset}
              className="preset"
              onClick={() => {
                setClaim(preset);
                run(preset);
              }}
              disabled={!imageId || running}
            >
              {preset}
            </button>
          ))}
        </div>
        <div className="row-actions">
          <button className="primary" onClick={() => run()} disabled={!imageId || running}>
            {running ? "Checking…" : "Verify claim"}
          </button>
          <button className="ghost" onClick={() => setVerification(null)}>
            Clear result
          </button>
        </div>
        {error && <p className="error small">{error}</p>}
        {!imageId && <p className="warning small">Select an image first.</p>}

        <div className="panel-divider" />
        <div className="micro-label">Supported forms</div>
        <ul className="plain-list small subtle">
          <li>“A is aligned with B” / “A and B are left-aligned”</li>
          <li>“A is 12 pixels to the right of B”</li>
          <li>“A is wider than B”, “A is inside B”, “A overlaps B”</li>
          <li>“The image contains the text ‘Save’”</li>
          <li>“The Save button is blue”, “The image is 1280x800”</li>
          <li>Anything else returns inconclusive by design.</li>
        </ul>
      </div>

      <div className="verify-result">
        <div className="panel-heading">
          <span>Verdict</span>
          {verification && (
            <span className="mono subtle">confidence {Math.round(verification.confidence * 100)}%</span>
          )}
        </div>

        {!verification && !error && (
          <div className="empty-state small">
            A verdict is only returned when the claim can be measured. Unsupported claims return
            inconclusive instead of a guess.
          </div>
        )}

        {verification && (
          <>
            <div className={`verdict ${verification.status}`}>
              <span className="verdict-status">{verification.status}</span>
              <span className="verdict-claim">“{verification.claim}”</span>
            </div>
            <p className="summary">{verification.explanation}</p>

            {verification.measurements.length > 0 && (
              <div className="measurement-table">
                <div className="measurement-head">
                  <span>Measurement</span>
                  <span>Value</span>
                  <span>Expected</span>
                  <span>Δ</span>
                </div>
                {verification.measurements.map((item, index) => (
                  <div className="measurement-row" key={`${item.name}-${index}`}>
                    <span className="mono">{item.name}</span>
                    <span className="mono">{formatValue(item.value)}</span>
                    <span className="mono subtle">{formatValue(item.expected)}</span>
                    <span className="mono">{item.delta === null ? "—" : item.delta}</span>
                  </div>
                ))}
              </div>
            )}

            <div className="response-meta">
              <span className="mono tiny">method: {verification.method}</span>
              <span className="mono tiny">evidence: {verification.evidence_ids.length}</span>
              {payload?.timings_ms?.total_ms !== undefined && (
                <span className="mono tiny">{Math.round(payload.timings_ms.total_ms)} ms</span>
              )}
            </div>
          </>
        )}

        <div className="panel-divider" />
        <div className="micro-label">Recent verdicts</div>
        <div className="history">
          {history.length === 0 && <span className="subtle small">No verdicts yet.</span>}
          {history.map((item, index) => (
            <button
              key={`${item.claim}-${index}`}
              className="history-row"
              onClick={() => {
                setClaim(item.claim);
                setVerification(item);
              }}
            >
              <span className={`mini-verdict ${item.status}`}>{item.status}</span>
              <span className="history-summary">{item.claim}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return `[${value.join(", ")}]`;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
