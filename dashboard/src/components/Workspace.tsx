import { useRef, useState } from "react";
import { formatBytes } from "../api";
import type { ConfigInfo, Health, RemoteImage } from "../types";

interface Props {
  images: RemoteImage[];
  health: Health;
  config: ConfigInfo;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onUpload: (file: File) => void;
  onRefresh: () => void;
  onDelete: (id: string) => void;
  uploadBusy: boolean;
}

export default function Workspace({
  images,
  health,
  config,
  selectedId,
  onSelect,
  onUpload,
  onRefresh,
  onDelete,
  uploadBusy,
}: Props) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [drag, setDrag] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  async function handleFiles(list: FileList | null) {
    setUploadError(null);
    if (!list || list.length === 0) return;
    setDrag(false);
    const file = list[0];
    if (!file.type.startsWith("image/")) {
      setUploadError("Please upload an image file (PNG, JPEG, WebP, BMP, TIFF).");
      return;
    }
    try {
      await onUpload(file);
    } catch (exc) {
      setUploadError(exc instanceof Error ? exc.message : "Upload failed.");
    }
  }

  return (
    <div className="workspace">
      <div className="upload-zone" onDragOver={(event) => event.preventDefault()} onDragLeave={() => setDrag(false)} onDrop={(event) => { event.preventDefault(); handleFiles(event.dataTransfer.files); }}>
        <div className={`upload-content ${drag ? "dragging" : ""}`}>
          <div className="upload-icon">↑</div>
          <div className="upload-text">
            <strong>Drop an image here</strong>
            <span>or click to select one. It will be uploaded, analysed and stored locally.</span>
          </div>
          <button
            className="primary"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadBusy}
          >
            {uploadBusy ? "Uploading…" : "Choose image"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/bmp,image/tiff"
            onChange={(event) => handleFiles(event.target.files)}
          />
        </div>
      </div>

      {uploadError && <p className="error small">{uploadError}</p>}

      <div className="panel-section">
        <div className="panel-heading">
          <span>Local image store</span>
          <button className="ghost tiny" onClick={onRefresh}>Refresh</button>
        </div>
        {images.length === 0 ? (
          <div className="empty-state">No images yet. Upload your first screenshot above.</div>
        ) : (
          <div className="image-grid">
            {images.map((image) => (
              <div
                key={image.image_id}
                className={`image-card ${selectedId === image.image_id ? "selected" : ""}`}
                onClick={() => onSelect(image.image_id)}
              >
                <img
                  src={image.thumbnail_url}
                  alt=""
                  draggable={false}
                  onError={(event) =>
                    (event.currentTarget.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='128' height='80' viewBox='0 0 128 80'%3E%3Crect fill='%231a1e24' width='128' height='80'/%3E%3Ctext fill='%236b7280' font-size='10' font-family='monospace' x='50%' y='50%' text-anchor='middle'%3ENO PREVIEW%3C/text%3E%3C/svg%3E")
                  }
                />
                <div className="image-card-body">
                  <div className="image-name mono small">{image.image_id}</div>
                  <div className="image-meta">
                    <span className="mono">{image.width}×{image.height}</span>
                    <span className="mono">{image.format}</span>
                    <span className="mono">{formatBytes(image.size_bytes)}</span>
                  </div>
                  <div className="image-meta">
                    <span className="mono tiny">
                      {image.evidence_count ?? 0} evidence
                    </span>
                    <span className="mono tiny">{new Date(image.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
                <button
                  className="ghost delete"
                  onClick={(event) => {
                    event.stopPropagation();
                    if (confirm(`Delete ${image.image_id}?`)) onDelete(image.image_id);
                  }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="panel-section">
        <div className="panel-heading"><span>Engine status</span></div>
        <div className="status-grid">
          <div className="status-card">
            <span className="mono tiny">service</span>
            <div className="mono">{health.status === "ok" ? "running" : health.status}</div>
          </div>
          <div className="status-card">
            <span className="mono tiny">version</span>
            <div className="mono">{health.version}</div>
          </div>
          <div className="status-card">
            <span className="mono tiny">images</span>
            <div className="mono">{health.images}</div>
          </div>
          <div className="status-card">
            <span className="mono tiny">OCR</span>
            <div className="mono">{health.ocr.enabled && health.ocr.available ? "ready" : "disabled"}</div>
          </div>
          <div className="status-card">
            <span className="mono tiny">semantic</span>
            <div className="mono">{config.semantic.provider}</div>
          </div>
          <div className="status-card">
            <span className="mono tiny">data dir</span>
            <div className="mono tiny">{config.data_dir}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
