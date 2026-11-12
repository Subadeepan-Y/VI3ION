import type {
  ConfigInfo,
  EvidenceResponse,
  Health,
  RemoteImage,
  ToolDefinition,
  ToolPayload,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
  });
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!response.ok) {
    const message =
      body && typeof body === "object" && "error" in body
        ? String((body as { error: unknown }).error)
        : `${response.status} ${response.statusText}`;
    throw new Error(message);
  }
  return body as T;
}

export const api = {
  health: () => request<Health>("/api/health"),
  config: () => request<ConfigInfo>("/api/config"),

  listImages: () =>
    request<{ images: RemoteImage[]; total: number }>("/api/images?limit=200"),

  image: (imageId: string) =>
    request<{ image: RemoteImage; sessions: unknown[]; jobs: unknown[] }>(`/api/images/${imageId}`),

  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return request<{ image: RemoteImage; deduplicated: boolean; analysis?: ToolPayload }>(
      "/api/images?analyze=true&detail=standard",
      { method: "POST", body: form },
    );
  },

  remove: (imageId: string) =>
    request<{ ok: boolean; deleted: string }>(`/api/images/${imageId}`, { method: "DELETE" }),

  evidence: (imageId: string) =>
    request<EvidenceResponse>(`/api/images/${imageId}/evidence?limit=500`),

  analyze: (imageId: string, force = false) =>
    request<ToolPayload>(`/api/images/${imageId}/analyze`, {
      method: "POST",
      body: JSON.stringify({ image_id: imageId, detail: "standard", force }),
    }),

  inspectRegion: (imageId: string, region: number[], detail = "standard") =>
    request<ToolPayload>(`/api/images/${imageId}/regions/inspect`, {
      method: "POST",
      body: JSON.stringify({ image_id: imageId, region, detail }),
    }),

  verify: (imageId: string, claim: string) =>
    request<ToolPayload>(`/api/images/${imageId}/verify`, {
      method: "POST",
      body: JSON.stringify({ claim }),
    }),

  tools: () => request<{ tools: ToolDefinition[] }>("/api/tools"),
  runTool: (tool: string, args: Record<string, unknown>) =>
    request<ToolPayload>(`/api/tools/${tool}`, {
      method: "POST",
      body: JSON.stringify(args),
    }),
};

export function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export function bboxLabel(bbox: number[] | null | undefined): string {
  if (!bbox || bbox.length !== 4) return "—";
  return bbox.map((v) => Math.round(v)).join(", ");
}
