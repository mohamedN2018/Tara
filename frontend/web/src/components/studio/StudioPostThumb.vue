<script setup lang="ts">
import { BarChart3, Film, Image as ImageIcon, Link2, Repeat2, Type } from "lucide-vue-next";
import { computed } from "vue";

import { useMediaUrl } from "@/lib/useMediaUrl";

// A post's small square: its first photo, or an icon for its kind (decorative:
// the row next to it always says what the post is).
const props = withDefaults(defineProps<{ type: string; mediaIds?: string[]; size?: number }>(), {
  mediaIds: () => [],
  size: 24,
});

const photoId = computed(() => (props.type === "image" ? (props.mediaIds[0] ?? null) : null));
const url = useMediaUrl(() => photoId.value);
const icon = computed(() => {
  switch (props.type) {
    case "video":
      return Film;
    case "poll":
      return BarChart3;
    case "link":
      return Link2;
    case "share":
      return Repeat2;
    case "image":
      return ImageIcon; // a photo post whose picture isn't loaded (or a type row)
    default:
      return Type;
  }
});
</script>

<template>
  <span
    class="inline-flex shrink-0 items-center justify-center overflow-hidden rounded-md bg-tara-gradient-soft text-brand-700 ring-1 ring-brand-200/60 dark:text-brand-200 dark:ring-brand-900"
    :style="{ width: `${size}px`, height: `${size}px` }"
    aria-hidden="true"
  >
    <img v-if="url" :src="url" alt="" class="h-full w-full object-cover" loading="lazy" />
    <component :is="icon" v-else class="h-[60%] w-[60%]" />
  </span>
</template>
