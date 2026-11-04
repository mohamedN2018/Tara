<script setup lang="ts">
import { Eye } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useMediaUrl } from "@/lib/useMediaUrl";
import { backgroundStyle, type Story } from "@/services/stories";

// One story in my archive: its photo or text, the day it was shared, whether it
// is still on the rail, and how many people saw it.
const props = defineProps<{ story: Story }>();
defineEmits<{ open: [] }>();

const { t, locale } = useI18n();
const photo = useMediaUrl(() => (props.story.kind === "photo" ? props.story.media_id : null));
const when = computed(() =>
  new Intl.DateTimeFormat(locale.value, { day: "numeric", month: "short", year: "numeric" }).format(new Date(props.story.created_at)),
);
</script>

<template>
  <button
    type="button"
    class="group relative block aspect-[9/16] w-full overflow-hidden rounded-xl bg-gray-900 text-start text-white shadow-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2"
    :style="story.kind === 'text' || !photo ? { backgroundImage: backgroundStyle(story.background) } : undefined"
    :aria-label="t('stories.archive.open', { time: when })"
    data-testid="story-archive-tile"
    @click="$emit('open')"
  >
    <img v-if="photo" :src="photo" alt="" class="absolute inset-0 h-full w-full object-cover transition duration-300 group-hover:scale-105" loading="lazy" />
    <p v-else-if="story.kind === 'text'" dir="auto" class="absolute inset-0 flex items-center justify-center p-3 text-center text-sm font-bold leading-snug">
      <span class="line-clamp-6">{{ story.text }}</span>
    </p>
    <span class="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/50 via-transparent to-black/60" />
    <!-- Date at the top, status and views at the bottom: nothing overlaps on a narrow tile. -->
    <span class="absolute start-2 top-2 max-w-[calc(100%-1rem)] truncate rounded-md bg-white/90 px-1.5 py-0.5 text-[11px] font-bold leading-tight text-gray-900">{{ when }}</span>
    <span
      class="absolute bottom-2 end-2 rounded-full px-2 py-0.5 text-[10px] font-semibold"
      :class="story.is_active ? 'bg-emerald-700 text-white' : 'bg-black/50 text-white'"
    >
      {{ story.is_active ? t("stories.archive.active") : t("stories.archive.expired") }}
    </span>
    <span class="absolute bottom-2 start-2 inline-flex items-center gap-1 text-xs font-semibold">
      <Eye class="h-3.5 w-3.5" aria-hidden="true" />{{ story.view_count ?? 0 }}
    </span>
  </button>
</template>
