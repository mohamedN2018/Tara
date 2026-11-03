<script setup lang="ts">
import { ImageIcon } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useMediaUrl } from "@/lib/useMediaUrl";
import type { SearchResult } from "@/services/search";

const props = defineProps<{ result: SearchResult }>();
const { t } = useI18n();

const url = useMediaUrl(() => props.result.media_ids?.[0]);
const alt = computed(() =>
  props.result.snippet ? t("search.photoAlt", { text: props.result.snippet.slice(0, 80) }) : t("search.photoAltEmpty"),
);
</script>

<template>
  <RouterLink
    :to="{ name: 'post', params: { id: result.id } }"
    class="group relative block aspect-square overflow-hidden rounded-xl bg-gray-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:bg-gray-800"
    data-testid="photo-result"
  >
    <img v-if="url" :src="url" :alt="alt" class="h-full w-full object-cover transition group-hover:scale-105" loading="lazy" />
    <span v-else class="flex h-full w-full items-center justify-center text-gray-400" role="img" :aria-label="alt">
      <ImageIcon class="h-8 w-8" aria-hidden="true" />
    </span>
  </RouterLink>
</template>
