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

// Cache resolved display URLs by media id (they are presigned but long-lived).
const urlCache = new Map<string, string>();

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
    // JWT/baseURL are NOT attached.
    const put = await fetch(s.upload_url, {
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

  /** Resolve a media id to a displayable URL (cached). null while not ready. */
  async resolveUrl(id: string): Promise<string | null> {
    const cached = urlCache.get(id);
    if (cached) return cached;
    try {
      const asset = await this.detail(id);
      if (asset.url) urlCache.set(id, asset.url);
      return asset.url;
    } catch {
      return null;
    }
  },
};
