<script setup lang="ts">
import { ImageOff } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { gridLayout } from "@/lib/mediaGrid";
import { useMediaList } from "@/lib/useMediaList";

// A post's photos as a 1/2/3/4+ grid. Each tile opens the viewer at its index.
const props = withDefaults(defineProps<{ mediaIds: string[]; authorName: string; compact?: boolean }>(), {
  compact: false,
});
const emit = defineEmits<{ open: [index: number] }>();
const { t } = useI18n();

const urls = useMediaList(() => props.mediaIds);
const layout = computed(() => gridLayout(props.mediaIds.length));
const total = computed(() => props.mediaIds.length);

function label(index: number, overflow: number): string {
  const open = t("post.openPhoto", { n: index + 1, total: total.value });
  return overflow ? `${open}. ${t("post.morePhotos", overflow)}` : open;
}
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
        v-if="urls[tile.index]"
        :src="urls[tile.index] ?? undefined"
        class="h-full w-full object-cover transition duration-200 group-hover:opacity-95"
        :class="layout.kind === 'single' ? 'max-h-[32rem]' : ''"
        loading="lazy"
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
