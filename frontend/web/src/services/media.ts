import { api } from "@/lib/api";

export interface MediaVariant {
  kind: string;
  url: string;
  width?: number;
  height?: number;
  duration_ms?: number | null;
}

export interface MediaAsset {
  id: string;
  kind: string;
  status: string; // uploading | processing | ready | failed
  mime?: string;
  bytes?: number;
  visibility?: string;
  url: string | null; // presigned GET url, present only once status === "ready"
  variants?: MediaVariant[];
}

interface SignResult {
  media_id: string;
  storage_key: string;
  upload_url: string;
  method: string;
  expires_in: number;
}

// Cache resolved display URLs by media id. Presigned URLs expire (~15 min), so
// entries carry a timestamp and are re-resolved after a TTL safely below that.
const urlCache = new Map<string, { url: string; at: number }>();
const URL_TTL_MS = 10 * 60 * 1000;

// Presigned storage URLs are signed for the internal host `minio:9000`, which
// the browser can't resolve. In dev, route them through the Vite proxy (/__s3)
// which forwards to localhost:9000 with the signed Host header preserved. In a
// production build the absolute URL is returned unchanged, unless the build is
// for local e2e (`VITE_STORAGE_PROXY=true`, served by `vite preview`, which
// shares the dev proxy).
const STORAGE_PROXY = import.meta.env.DEV || import.meta.env.VITE_STORAGE_PROXY === "true";
export function viaStorageProxy(url: string | null): string | null {
  if (!url || !STORAGE_PROXY || url.startsWith("/")) return url;
  try {
    const u = new URL(url);
    return `/__s3${u.pathname}${u.search}`;
  } catch {
    return url;
  }
}

export const mediaService = {
  /**
   * Presigned upload: sign → PUT bytes straight to object storage → complete.
   * Returns the asset (status will be "processing" until the worker finishes).
   */
  async upload(file: File, kind = "image", visibility = "public"): Promise<MediaAsset> {
    const mime = file.type || "application/octet-stream";
    const { data: signed } = await api.post<{ data: SignResult }>("/media/uploads/sign/", {
      kind,
      mime,
      size: file.size,
      visibility,
    });
    const s = signed.data;

    // The presigned URL carries its own auth — use bare fetch so the gateway
    // JWT/baseURL are NOT attached. Route through the storage proxy in dev.
    const put = await fetch(viaStorageProxy(s.upload_url) ?? s.upload_url, {
      method: "PUT",
      headers: { "Content-Type": mime },
      body: file,
    });
    if (!put.ok) throw new Error(`Upload failed (${put.status})`);

    const { data: done } = await api.post<{ data: MediaAsset }>(
      `/media/uploads/${s.media_id}/complete/`,
    );
    return done.data;
  },

  async detail(id: string): Promise<MediaAsset> {
    const { data } = await api.get<{ data: MediaAsset }>(`/media/${id}/`);
    return data.data;
  },

  /** Resolve a media id to a displayable URL (cached with TTL). null while not ready. */
  async resolveUrl(id: string): Promise<string | null> {
    const cached = urlCache.get(id);
    if (cached && Date.now() - cached.at < URL_TTL_MS) return cached.url;
    try {
      const asset = await this.detail(id);
      const url = viaStorageProxy(asset.url);
      if (url) urlCache.set(id, { url, at: Date.now() });
      return url ?? cached?.url ?? null;
    } catch {
      return cached?.url ?? null;
    }
  },
};
