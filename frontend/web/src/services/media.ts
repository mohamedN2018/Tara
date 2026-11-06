import { api } from "@/lib/api";
import { createBatchLoader } from "@/lib/batchLoader";
import { delivery } from "@/lib/delivery";
import { uploadMime } from "@/lib/heic";

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
  /** Image size in pixels (08 §7.8); null or absent on older assets. */
  width?: number | null;
  height?: number | null;
  /** When the signed URLs of this answer stop working (epoch seconds; 08 §7.8). */
  urls_expire_at?: number | null;
}

/** What an <img> needs for one media id (08 §7.8): never a size the server did not send. */
export interface MediaView {
  src: string;
  srcset?: string;
  width?: number;
  height?: number;
}

// The variants a feed image may use, in srcset order (08 §7.8).
const SRCSET_KINDS = ["thumb", "display_640", "display_1280"] as const;

interface SignResult {
  media_id: string;
  storage_key: string;
  upload_url: string;
  method: string;
  expires_in: number;
}

// Cache resolved display URLs by media id, with the asset's variants and size.
// An answer that says when its signed URLs expire (`urls_expire_at`, hour
// buckets on the server) is kept until then minus a safety margin; an older
// server's answer is kept for URL_TTL_MS, safely below its ~15 min signature.
interface CachedMedia {
  url: string;
  until: number;
  variants: Record<string, { url: string; width?: number; height?: number }>;
  width?: number;
  height?: number;
}
const urlCache = new Map<string, CachedMedia>();
const URL_TTL_MS = 10 * 60 * 1000;
const EXPIRY_MARGIN_MS = 2 * 60 * 1000;
const fresh = (c: CachedMedia | undefined): c is CachedMedia => !!c && Date.now() < c.until;
const size = (n: unknown): number | undefined => (typeof n === "number" && Number.isFinite(n) && n > 0 ? Math.round(n) : undefined);

function remember(id: string, asset: MediaAsset): CachedMedia | null {
  const url = viaStorageProxy(asset.url);
  if (!url) return null;
  const expires = typeof asset.urls_expire_at === "number" && asset.urls_expire_at > 0 ? asset.urls_expire_at * 1000 : null;
  const until = expires ? Math.max(Date.now(), expires - EXPIRY_MARGIN_MS) : Date.now() + URL_TTL_MS;
  const variants: CachedMedia["variants"] = {};
  for (const v of asset.variants ?? []) {
    const vurl = viaStorageProxy(v.url);
    if (v.kind && vurl) variants[v.kind] = { url: vurl, width: size(v.width), height: size(v.height) };
  }
  const entry: CachedMedia = { url, until, variants, width: size(asset.width), height: size(asset.height) };
  urlCache.set(id, entry);
  return entry;
}

// Ids media left out (unknown, deleted, not visible to this viewer): not asked
// again for a short while, so every remount of a tile does not repeat the call.
const missCache = new Map<string, number>();
const MISS_TTL_MS = 60 * 1000;

// Every lookup made while a page renders goes out in one `POST /media/resolve/`
// (at most 100 ids), with 429s retried; see lib/batchLoader.ts.
// The gathering window is the server's `delivery.media_resolve_window_ms` (08 §7.8),
// so one page's mounts make one or two calls.
const assets = createBatchLoader<MediaAsset>({
  label: "media",
  fetch: async (ids) => (await api.post<{ data: MediaAsset[] }>("/media/resolve/", { ids })).data.data,
  idOf: (a) => a.id,
  windowMs: () => delivery("home").media_resolve_window_ms,
});

/** Forget cached URLs and misses (sign-out, tests). */
export function clearMediaCache(): void {
  urlCache.clear();
  missCache.clear();
}

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
  /** A short-lived signed URL for the original file (404 for a transcoded video, 409 while processing). */
  async downloadUrl(id: string): Promise<string> {
    const { data } = await api.get<{ data: { download_url: string } }>(`/media/${id}/download-url/`);
    return data.data.download_url;
  },

  /**
   * Presigned upload: sign → PUT bytes straight to object storage → complete.
   * Returns the asset (status will be "processing" until the worker finishes).
   */
  async upload(
    file: File,
    kind = "image",
    visibility = "public",
    // `purpose: "post"` sends a video to the transcoder (HLS, see services/video.ts).
    options: { purpose?: string; mime?: string } = {},
  ): Promise<MediaAsset> {
    const mime = options.mime || uploadMime(file);
    const { data: signed } = await api.post<{ data: SignResult }>("/media/uploads/sign/", {
      kind,
      mime,
      size: file.size,
      visibility,
      ...(options.purpose ? { purpose: options.purpose } : {}),
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

  /** A still-fresh cached URL, synchronously (no request); null otherwise. */
  cachedUrl(id: string): string | null {
    const cached = urlCache.get(id);
    return fresh(cached) ? cached.url : null;
  },

  /**
   * The asset as the viewer may see it, batched with every other lookup of the
   * same tick; null when media leaves it out (unknown or not visible).
   */
  resolveAsset(id: string): Promise<MediaAsset | null> {
    return assets.load(id);
  },

  /**
   * Resolve a media id to a displayable URL (cached with TTL). null while not
   * ready or not visible. A failed lookup (after retries) is logged once by the
   * batch loader and falls back to the last good URL.
   */
  async resolveUrl(id: string): Promise<string | null> {
    return (await this.resolveCached(id))?.url ?? null;
  },

  /** The cache entry for `id`, resolving it when missing or expired; the last good one on failure. */
  async resolveCached(id: string): Promise<CachedMedia | null> {
    const cached = urlCache.get(id);
    if (fresh(cached)) return cached;
    const missed = missCache.get(id);
    if (missed && Date.now() - missed < MISS_TTL_MS) return cached ?? null;
    try {
      const asset = await this.resolveAsset(id);
      if (!asset) {
        missCache.set(id, Date.now());
        return null;
      }
      missCache.delete(id);
      return remember(id, asset) ?? cached ?? null;
    } catch {
      return cached ?? null;
    }
  },

  /** The 320 px thumbnail (grid tiles, avatars); the display URL when there is none. */
  async resolveThumb(id: string): Promise<string | null> {
    const entry = await this.resolveCached(id);
    return entry ? (entry.variants.thumb?.url ?? entry.url) : null;
  },

  /** A cached thumbnail, synchronously (no request); null otherwise. */
  cachedThumb(id: string): string | null {
    const entry = urlCache.get(id);
    return fresh(entry) ? (entry.variants.thumb?.url ?? entry.url) : null;
  },

  /**
   * A single image's src, srcset and size (08 §7.8): `thumb 320w, display_640 640w,
   * display_1280 1280w` from the widths the server sent; a variant without a width
   * is left out, and no srcset is made from nothing.
   */
  async resolveSrcset(id: string): Promise<MediaView | null> {
    const entry = await this.resolveCached(id);
    return entry ? srcsetOf(entry) : null;
  },

  /** Warm the URLs of these ids in one batched call (08 §7.5); thumbs load at low priority. */
  warm(ids: string[]): Promise<void> {
    return Promise.all(ids.map((id) => this.resolveCached(id))).then(() => undefined);
  },
};

/** The <img> attributes for a cache entry (exported for tests). */
export function srcsetOf(entry: Pick<CachedMedia, "url" | "variants" | "width" | "height">): MediaView {
  const parts: string[] = [];
  for (const kind of SRCSET_KINDS) {
    const v = entry.variants[kind];
    if (v?.url && v.width) parts.push(`${v.url} ${v.width}w`);
  }
  const src = entry.variants.display_640?.url ?? entry.url;
  const view: MediaView = { src };
  if (parts.length > 1) view.srcset = parts.join(", ");
  if (entry.width && entry.height) {
    view.width = entry.width;
    view.height = entry.height;
  }
  return view;
}
