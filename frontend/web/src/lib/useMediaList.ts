import { ref, type Ref, watchEffect } from "vue";

import { mediaService } from "@/services/media";

/**
 * Display URLs for a post's media, one slot per id in the same order (null
 * while a photo is still processing or is not available to this viewer), so
 * grid tiles and viewer indexes always match the post's photo order. Media
 * still asks post whether the viewer may see a restricted photo.
 */
export function useMediaList(getIds: () => string[]): Ref<(string | null)[]> {
  const urls = ref<(string | null)[]>([]);
  let run = 0;
  watchEffect(async () => {
    const ids = getIds();
    const mine = ++run;
    if (urls.value.length !== ids.length) urls.value = ids.map(() => null);
    const resolved = await Promise.all(ids.map((id) => mediaService.resolveUrl(id)));
    if (mine === run) urls.value = resolved;
  });
  return urls;
}
