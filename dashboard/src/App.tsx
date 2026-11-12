import { useCallback, useEffect, useRef, useState } from "react";
import { api, bboxLabel, formatBytes } from "./api";
import type { ConfigInfo, EvidenceResponse, Health, RemoteImage, ToolPayload } from "./types";
import Workspace from "./components/Workspace";
import ImageViewer from "./components/ImageViewer";
import EvidencePanel from "./components/EvidencePanel";
import AgentSimulator from "./components/AgentSimulator";
import VerifyPanel from "./components/VerifyPanel";

type Tab = "workspace" | "viewer" | "evidence" | "agent" | "verify";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [config, setConfig] = useState<ConfigInfo | null>(null);
  const [images, setImages] = useState<RemoteImage[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [current, setCurrent] = useState<RemoteImage | null>(null);
  const [evidence, setEvidence] = useState<EvidenceResponse | null>(null);
  const [selected, setSelected] = useState<number[] | null>(null);
  const [regionResult, setRegionResult] = useState<null | { payload: ToolPayload; added: number }>(null);
  const [tab, setTab] = useState<Tab>("workspace");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploadBusy, setUploadBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    abortRef.current = new AbortController();
    (async () => {
      try {
        const [healthData, configData, imagesData] = await Promise.all([api.health(), api.config(), api.listImages()]);
        setHealth(healthData);
        setConfig(configData);
        setImages(imagesData.images);
        if (imagesData.images.length) {
          await selectImage(imagesData.images[0].image_id);
        }
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "Failed to connect to Vi3ion.");
      } finally {
        setLoading(false);
      }
    })();
    return () => abortRef.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function selectImage(imageId: string) {
    setLoading(true);
    try {
      const [imageData, evidenceData] = await Promise.all([
        api.image(imageId),
        api.evidence(imageId),
      ]);
      setCurrent(imageData.image);
      setEvidence(evidenceData);
      setCurrentId(imageId);
      setSelected(null);
      setRegionResult(null);
      setTab("viewer");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load image.");
    } finally {
      setLoading(false);
    }
  }

  async function refreshImages() {
    try {
      const data = await api.listImages();
      setImages(data.images);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to refresh image list.");
    }
  }

  async function handleUpload(file: File) {
    setUploadBusy(true);
    setError(null);
    try {
      const result = await api.upload(file);
      setImages((items) => [result.image, ...items.filter((item) => item.image_id !== result.image.image_id)]);
      await selectImage(result.image.image_id);
      setRegionResult(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Upload failed.");
      throw exc;
    } finally {
      setUploadBusy(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      await api.remove(id);
      setImages((items) => items.filter((item) => item.image_id !== id));
      if (currentId === id) {
        setCurrent(null);
        setEvidence(null);
        setCurrentId(null);
        setSelected(null);
        setRegionResult(null);
        setTab("workspace");
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Delete failed.");
    }
  }

  const handleInspect = useCallback(
    async (bbox: number[]) => {
      if (!currentId || !bbox) return;
      try {
        const result = await api.inspectRegion(currentId, bbox);
        setRegionResult({ payload: result, added: 0 });
        const evidenceData = await api.evidence(currentId);
        setEvidence(evidenceData);
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "Inspection failed.");
      }
    },
    [currentId],
  );

  if (loading) {
    return (
      <div className="app">
        <div className="app-loading">Loading Vi3ion dashboard…</div>
      </div>
    );
  }

  const tabItems: { key: Tab; label: string }[] = [
    { key: "workspace", label: "Workspace" },
    { key: "viewer", label: "View evidence" },
    { key: "evidence", label: "Evidence" },
    { key: "agent", label: "Agent simulator" },
    { key: "verify", label: "Verification" },
  ];

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-dot" />
          <span className="brand-name">VI3ION</span>
          <span className="brand-sub">visual evidence layer</span>
        </div>
        <nav className="app-nav">
          {tabItems.map((item) => (
            <button
              key={item.key}
              className={`tab ${tab === item.key ? "active" : ""}`}
              onClick={() => setTab(item.key)}
              disabled={!currentId && item.key !== "workspace"}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="app-status">
          <span className="mono small">
            {current
              ? `${current.width}×${current.height} · ${bboxLabel(selected)} · ${current.format} · ${formatBytes(current.size_bytes)}`
              : "no image selected"}
          </span>
        </div>
      </header>

      {error && (
        <div className="error-banner">
          <span>{error}</span>
          <button className="tiny" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      )}

      <main className="app-main">
        {tab === "workspace" ? (
          <Workspace
            images={images}
            health={health ?? { status: "unknown", version: "?", images: 0, data_dir: "", ocr: { enabled: false, available: false }, semantic_provider: "none", coordinate_space: "original px" }}
            config={config ?? { version: "?", host: "", port: 0, data_dir: "", limits: {}, allowed_roots: [], ocr: { enabled: false, min_confidence: 0 }, semantic: { provider: "none", model: null, remote_enabled: false }, coordinate_space: "original px" }}
            selectedId={currentId}
            onSelect={selectImage}
            onUpload={handleUpload}
            onRefresh={refreshImages}
            onDelete={handleDelete}
            uploadBusy={uploadBusy}
          />
        ) : current ? (
          tab === "viewer" ? (
            <ImageViewer
              image={current}
              evidence={evidence?.evidence ?? []}
              selected={selected}
              onSelect={setSelected}
              onInspect={handleInspect}
              inspecting={false}
              regionResult={regionResult?.payload ?? null}
            />
          ) : tab === "evidence" ? (
            <EvidencePanel
              evidence={evidence?.evidence ?? []}
              selected={selected}
              onSelect={setSelected}
            />
          ) : tab === "agent" ? (
            <AgentSimulator imageId={currentId} selected={selected} />
          ) : (
            <VerifyPanel imageId={currentId} />
          )
        ) : (
          <div className="empty-main">
            <div className="empty-main-content">
              <div className="empty-main-head">Open a workspace tab to get started.</div>
              <div className="empty-main-sub">
                Upload an image and explore it through structured evidence: OCR, bounding boxes,
                measured geometry and verified claims.
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
