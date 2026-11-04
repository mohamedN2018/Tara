// Video in posts (roadmap 5.2 / 5.3). Uploads go through the shared presigned
// flow with `purpose: "post"`, so media's transcoder turns them into an HLS
// ladder; playback asks media for a short-lived, viewer-bound playlist token.
import { api } from "@/lib/api";
import { type MediaAsset, mediaService, viaStorageProxy } from "@/services/media";

/** For `<input type="file" accept>`: what the transcoder takes (iPhone .mov included). */
export const VIDEO_ACCEPT = "video/mp4,video/quicktime,video/webm,.mp4,.mov,.m4v,.webm";
const VIDEO_TYPES: Record<string, string> = {
  mp4: "video/mp4",
  m4v: "video/mp4",
  mov: "video/quicktime",
  webm: "video/webm",
};
/** The transcoder's per-post size cap (MEDIA_VIDEO_MAX_BYTES_POST); the server checks again. */
export const MAX_VIDEO_BYTES = 200 * 1024 * 1024;

/** The MIME to sign and PUT with: the browser's own, or one from the extension. */
export function videoMime(file: { name?: string; type?: string }): string | null {
  const type = (file.type || "").toLowerCase();
  if (Object.values(VIDEO_TYPES).includes(type)) return type;
  if (type && type !== "application/octet-stream") return null;
  const ext = /\.([a-z0-9]+)$/i.exec(file.name || "")?.[1]?.toLowerCase() ?? "";
  return VIDEO_TYPES[ext] ?? null;
}

/** The composer attachment (components/media/VideoComposerAttachment.vue). */
export type VideoAttachmentState = "idle" | "uploading" | "processing" | "ready" | "failed";

export type VideoStatus = "uploading" | "uploaded" | "processing" | "ready" | "failed";

export interface Playback {
  id: string;
  status: VideoStatus;
  failure_code: string | null;
  duration_ms: number | null;
  width: number | null;
  height: number | null;
  /** Absolute URL of the token-authorised master playlist (ready only). */
  hls_url: string | null;
  mp4_url: string | null;
  poster_url: string | null;
  expires_in: number;
}

/** Media returns the playlist path relative to the API root; resolve it against our API base. */
export function apiUrl(path: string): string {
  const base = String(api.defaults.baseURL ?? "/api/v1").replace(/\/+$/, "");
  return new URL(`${base}/${path.replace(/^\/+/, "")}`, window.location.href).toString();
}

export const isProcessing = (status: string) =>
  status === "uploading" || status === "uploaded" || status === "processing";

export const videoService = {
  async upload(file: File): Promise<MediaAsset> {
    const mime = videoMime(file);
    if (!mime) throw new Error("unsupported_video_type");
    return mediaService.upload(file, "video", "public", { purpose: "post", mime });
  },

  async playback(id: string): Promise<Playback> {
    const { data } = await api.get<{ data: Playback }>(`/media/${id}/playback/`);
    const p = data.data;
    return {
      ...p,
      hls_url: p.hls_url ? apiUrl(p.hls_url) : null,
      mp4_url: viaStorageProxy(p.mp4_url),
      poster_url: viaStorageProxy(p.poster_url),
    };
  },

  /**
   * Poll the owner's video until the transcoder is done ("ready" or "failed").
   * `onStatus` sees every status; stops early when `signal` aborts.
   */
  async waitUntilProcessed(
    id: string,
    { intervalMs = 2500, signal, onStatus }: { intervalMs?: number; signal?: AbortSignal; onStatus?: (s: string) => void } = {},
  ): Promise<MediaAsset> {
    for (;;) {
      if (signal?.aborted) throw new DOMException("aborted", "AbortError");
      const asset = await mediaService.detail(id);
      onStatus?.(asset.status);
      if (!isProcessing(asset.status)) return asset;
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
  },
};
