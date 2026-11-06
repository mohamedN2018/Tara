import { ref, type Ref, watch } from "vue";

import { type MediaView, mediaService } from "@/services/media";

/**
 * Display URLs for a post's media, one slot per id in the same order (null
 * while a photo is still processing or is not available to this viewer), so
 * grid tiles and viewer indexes always match the post's photo order. Media
 * still asks post whether the viewer may see a restricted photo.
 *
 * Only the ids are watched. Reading `urls` inside the effect would make every
 * write re-run it: with cached URLs that loop never yields and freezes the tab.
 */
export function useMediaList(getIds: () => string[]): Ref<(string | null)[]> {
  const urls = ref<(string | null)[]>([]);
  let run = 0;
  watch(
    () => getIds().join(","),
    async () => {
      const ids = getIds();
      const mine = ++run;
      if (urls.value.length !== ids.length) urls.value = ids.map(() => null);
      const resolved = await Promise.all(ids.map((id) => mediaService.resolveUrl(id)));
      if (mine === run) urls.value = resolved;
    },
    { immediate: true },
  );
  return urls;
}

/**
 * What each tile of a post's photos shows (08 §7.8), one slot per id in order:
 * `"thumb"` for grid tiles (2+ photos: the 320 px thumbnail), `"srcset"` for a
 * single photo (thumb / display_640 / display_1280 with their real widths, and
 * the image's size when the server knows it). null while not ready or not visible.
 */
export function useMediaViews(getIds: () => string[], mode: () => "thumb" | "srcset"): Ref<(MediaView | null)[]> {
  const views = ref<(MediaView | null)[]>([]);
  let run = 0;
  watch(
    () => `${mode()}|${getIds().join(",")}`,
    async () => {
      const ids = getIds();
      const how = mode();
      const mine = ++run;
      if (views.value.length !== ids.length) views.value = ids.map(() => null);
      const resolved = await Promise.all(
        ids.map(async (id): Promise<MediaView | null> => {
          if (how === "srcset") return mediaService.resolveSrcset(id);
          const src = await mediaService.resolveThumb(id);
          return src ? { src } : null;
        }),
      );
      if (mine === run) views.value = resolved;
    },
    { immediate: true },
  );
  return views;
}

/** One media id as its thumbnail (avatars): cached at once, else resolved in the batch. */
export function useMediaThumb(getId: () => string | null | undefined): Ref<string | null> {
  const url = ref<string | null>(null);
  watch(
    getId,
    async (id, _old, onCleanup) => {
      let stale = false;
      onCleanup(() => (stale = true));
      const cached = id ? mediaService.cachedThumb(id) : null;
      if (cached) {
        url.value = cached;
        return;
      }
      const resolved = id ? await mediaService.resolveThumb(id) : null;
      if (!stale) url.value = resolved;
    },
    { immediate: true },
  );
  return url;
}

/** The `sizes` of an image cropped to cover a `boxW` × `boxH` CSS px tile: the width it is drawn at. */
export function coverSizes(view: Pick<MediaView, "width" | "height">, boxW: number, boxH: number): string {
  const aspect = view.width && view.height ? view.width / view.height : 1;
  return `${Math.ceil(Math.max(boxW, boxH * aspect))}px`;
}

/**
 * One media id cropped to cover a fixed tile (story cards): the variants' srcset with
 * a `sizes` of the width the crop is drawn at, so the browser takes the smallest copy
 * that stays sharp, never the original when a display size exists (08 §7.8).
 */
export function useMediaCover(
  getId: () => string | null | undefined,
  boxW: number,
  boxH: number,
): Ref<(MediaView & { sizes?: string }) | null> {
  const views = useMediaViews(
    () => {
      const id = getId();
      return id ? [id] : [];
    },
    () => "srcset",
  );
  const cover = ref<(MediaView & { sizes?: string }) | null>(null);
  watch(
    views,
    (list) => {
      const v = list[0] ?? null;
      cover.value = v ? { ...v, sizes: v.srcset ? coverSizes(v, boxW, boxH) : undefined } : null;
    },
    { immediate: true },
  );
  return cover;
}
