import { ref, type Ref, watchEffect } from "vue";

import { mediaService } from "@/services/media";

/** Resolve a single media id to a presigned display URL (reactive, cached). */
export function useMediaUrl(getId: () => string | null | undefined): Ref<string | null> {
  const url = ref<string | null>(null);
  watchEffect(async () => {
    const id = getId();
    url.value = id ? await mediaService.resolveUrl(id) : null;
  });
  return url;
}

/** Resolve a list of media ids to URLs (drops the ones that aren't ready). */
export function useMediaUrls(getIds: () => string[]): Ref<string[]> {
  const urls = ref<string[]>([]);
  watchEffect(async () => {
    const ids = getIds();
    const resolved = await Promise.all(ids.map((id) => mediaService.resolveUrl(id)));
    urls.value = resolved.filter((u): u is string => !!u);
  });
  return urls;
}
