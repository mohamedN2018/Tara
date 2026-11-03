<script setup lang="ts">
import { Hash } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { SearchResult } from "@/services/search";

const props = defineProps<{ result: SearchResult }>();
const { t } = useI18n();

const tag = computed(() => (props.result.tag || props.result.title || props.result.id).replace(/^#/, ""));
</script>

<template>
  <RouterLink
    :to="{ name: 'search', query: { q: `#${tag}` } }"
    class="card card-hover flex items-center gap-3 p-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
    data-testid="hashtag-result"
  >
    <span class="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-600 dark:bg-brand-950/70 dark:text-brand-300">
      <Hash class="h-5 w-5" aria-hidden="true" />
    </span>
    <span class="min-w-0 flex-1">
      <span class="block truncate font-semibold" dir="auto">#{{ tag }}</span>
      <span v-if="result.post_count" class="block text-xs text-gray-500 dark:text-gray-400">{{ t("search.hashtagPosts", result.post_count) }}</span>
    </span>
  </RouterLink>
</template>
