export type BBox = [number, number, number, number];

export interface RemoteImage {
  image_id: string;
  width: number;
  height: number;
  format: string;
  size_bytes: number;
  created_at: string;
  source?: string;
  meta?: Record<string, unknown>;
  evidence_count?: number | null;
  file_url: string;
  thumbnail_url: string;
}

export interface EvidenceItem {
  evidence_id: string;
  image_id: string;
  kind: string;
  label: string;
  bbox: number[] | null;
  confidence: number | null;
  attributes: Record<string, unknown>;
  observed: boolean;
  scope: string;
  provenance: {
    module: string;
    method: string;
    version: string;
    produced_at: string;
    params?: Record<string, unknown>;
  };
}

export interface VerificationMeasurement {
  name: string;
  subject: string;
  value: unknown;
  expected: unknown | null;
  delta: number | null;
  unit: string;
  tolerance: number | null;
}

export interface Verification {
  claim: string;
  status: "verified" | "contradicted" | "inconclusive";
  confidence: number;
  explanation: string;
  measurements: VerificationMeasurement[];
  evidence_ids: string[];
  method: string;
}

export interface ToolPayload {
  ok: boolean;
  tool: string;
  image_id?: string;
  session_id?: string;
  summary?: string;
  data?: Record<string, any>;
  evidence?: EvidenceItem[];
  evidence_total?: number;
  evidence_returned?: number;
  truncated?: boolean;
  cached?: boolean;
  warnings?: string[];
  next_actions?: string[];
  timings_ms?: Record<string, number>;
  verification?: Verification;
  error?: string;
}

export interface Health {
  status: string;
  version: string;
  images: number;
  data_dir: string;
  ocr: { enabled: boolean; available: boolean };
  semantic_provider: string;
  coordinate_space: string;
}

export interface ConfigInfo {
  version: string;
  host: string;
  port: number;
  data_dir: string;
  limits: Record<string, number>;
  allowed_roots: string[];
  ocr: { enabled: boolean; min_confidence: number };
  semantic: { provider: string; model: string | null; remote_enabled: boolean };
  coordinate_space: string;
}

export interface EvidenceResponse {
  image_id: string;
  evidence: EvidenceItem[];
  total: number;
  kind_counts: Record<string, number>;
}

export interface ToolDefinition {
  name: string;
  description: string;
  arguments: Record<string, unknown>;
}
