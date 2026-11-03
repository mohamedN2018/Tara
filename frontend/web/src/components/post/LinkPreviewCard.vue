<script setup lang="ts">
import { ExternalLink } from "lucide-vue-next";

import type { LinkPreview } from "@/types";

defineProps<{ preview: LinkPreview }>();
</script>

<template>
  <a
    :href="preview.url"
    target="_blank"
    rel="noopener noreferrer nofollow ugc"
    class="mt-3 block rounded-xl border border-gray-200 p-3 transition hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-800/50"
    data-testid="link-preview"
  >
    <span class="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
      <ExternalLink class="h-3 w-3" /> <span dir="ltr">{{ preview.site }}</span>
    </span>
    <span class="mt-0.5 block text-sm font-semibold" dir="auto">{{ preview.title }}</span>
    <span v-if="preview.description" class="mt-0.5 line-clamp-2 block text-xs text-gray-500 dark:text-gray-400" dir="auto">{{ preview.description }}</span>
  </a>
</template>
