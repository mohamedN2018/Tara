<script setup lang="ts">
import { ImageOff } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { gridLayout } from "@/lib/mediaGrid";
import { useMediaViews } from "@/lib/useMediaList";

// A post's photos as a 1/2/3/4+ grid. Each tile opens the viewer at its index.
// Images (08 §7.8): grid tiles (2+ photos) load the 320 px thumbnail; a single
// photo gets a srcset of the variants the server has, with its real width and
// height so the layout is reserved before it loads. `eager`: the first card's
// first image, fetched at high priority; every other image is lazy.
const props = withDefaults(defineProps<{ mediaIds: string[]; authorName: string; compact?: boolean; eager?: boolean }>(), {
  compact: false,
  eager: false,
});
const emit = defineEmits<{ open: [index: number] }>();
const { t } = useI18n();

const layout = computed(() => gridLayout(props.mediaIds.length));
const total = computed(() => props.mediaIds.length);
const views = useMediaViews(
  () => props.mediaIds,
  () => (layout.value.kind === "single" ? "srcset" : "thumb"),
);
// One photo fills the column: up to 600 px wide (the feed's max width), the viewport on phones.
const SIZES = "(max-width: 600px) 100vw, 600px";

function label(index: number, overflow: number): string {
  const open = t("post.openPhoto", { n: index + 1, total: total.value });
  return overflow ? `${open}. ${t("post.morePhotos", overflow)}` : open;
}
const ratio = (i: number) => {
  const v = views.value[i];
  return layout.value.kind === "single" && v?.width && v.height ? `${v.width} / ${v.height}` : undefined;
};
</script>

<template>
  <div
    v-if="layout.tiles.length"
    class="mt-3 grid gap-0.5 overflow-hidden rounded-2xl bg-gray-100 dark:bg-gray-950"
    :class="[layout.container, compact ? 'rounded-none' : '']"
    data-testid="media-grid"
    :data-layout="layout.kind"
  >
    <button
      v-for="tile in layout.tiles"
      :key="mediaIds[tile.index]"
      type="button"
      class="group relative block w-full cursor-zoom-in overflow-hidden focus:outline-none focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-brand-400"
      :class="tile.cell"
      :aria-label="label(tile.index, tile.overflow)"
      @click="emit('open', tile.index)"
    >
      <img
        v-if="views[tile.index]"
        :src="views[tile.index]?.src"
        :srcset="views[tile.index]?.srcset"
        :sizes="views[tile.index]?.srcset ? SIZES : undefined"
        :width="views[tile.index]?.width"
        :height="views[tile.index]?.height"
        :style="ratio(tile.index) ? { aspectRatio: ratio(tile.index) } : undefined"
        class="h-full w-full object-cover transition duration-200 group-hover:opacity-95"
        :class="layout.kind === 'single' ? 'max-h-[32rem]' : ''"
        :loading="eager && tile.index === 0 ? 'eager' : 'lazy'"
        :fetchpriority="eager && tile.index === 0 ? 'high' : 'auto'"
        decoding="async"
        :alt="t('post.imageAlt', { n: tile.index + 1, name: authorName })"
      />
      <span
        v-else
        class="skeleton flex h-full min-h-40 w-full items-center justify-center rounded-none"
        aria-hidden="true"
      >
        <ImageOff class="relative h-6 w-6 text-gray-400 dark:text-gray-600" />
      </span>
      <span
        v-if="tile.overflow"
        class="absolute inset-0 flex items-center justify-center bg-gray-950/55 text-3xl font-extrabold text-white"
        dir="ltr"
        aria-hidden="true"
      >+{{ tile.overflow }}</span>
    </button>
  </div>
</template>
