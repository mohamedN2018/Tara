import { ref, type Ref, watchEffect } from "vue";

import { mediaService } from "@/services/media";

// Every call below goes through mediaService.resolveUrl, which gathers the
// lookups of one render into a single `POST /media/resolve/` (lib/batchLoader.ts)
// and caches the answers, so a page of 200 images makes one or two requests.

/** Resolve a single media id to a presigned display URL (reactive, cached, batched). */
export function useMediaUrl(getId: () => string | null | undefined): Ref<string | null> {
  const url = ref<string | null>(null);
  watchEffect(async (onCleanup) => {
    const id = getId();
    // An id that changed while the previous one resolved must not show its URL.
    let stale = false;
    onCleanup(() => (stale = true));
    // A cached URL shows at once (no blank frame when a tile remounts).
    const cached = id ? mediaService.cachedUrl(id) : null;
    if (cached) {
      url.value = cached;
      return;
    }
    const resolved = id ? await mediaService.resolveUrl(id) : null;
    if (!stale) url.value = resolved;
  });
  return url;
}

/** Resolve a list of media ids to URLs (drops the ones that aren't ready). */
export function useMediaUrls(getIds: () => string[]): Ref<string[]> {
  const urls = ref<string[]>([]);
  watchEffect(async (onCleanup) => {
    const ids = getIds();
    let stale = false;
    onCleanup(() => (stale = true));
    const resolved = await Promise.all(ids.map((id) => mediaService.resolveUrl(id)));
    if (!stale) urls.value = resolved.filter((u): u is string => !!u);
  });
  return urls;
}
