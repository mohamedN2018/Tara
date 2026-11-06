<script setup lang="ts">
// "You're all caught up" (Tara Intelligence 06 §6.2, 07 WP 4b.7) at the server's
// `meta.caught_up_index`: in the chronological modes the first row older than the
// last visit, in For You where the viewer's own circle ends. The end-of-feed card
// (FeedEndCard) stays the marker for "nothing more at all"; this one never repeats it.
import { CheckCircle2 } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

const { t } = useI18n();
</script>

<template>
  <div class="flex items-center gap-3 px-1 py-1" role="status" data-testid="caught-up-marker">
    <span class="h-px flex-1 bg-gray-200 dark:bg-gray-700" aria-hidden="true" />
    <span class="inline-flex shrink-0 items-center gap-1.5 text-sm font-semibold text-gray-700 dark:text-gray-200">
      <CheckCircle2 class="h-4 w-4 text-brand-600 dark:text-brand-300" aria-hidden="true" />
      {{ t("homeRefresh.caughtUp") }}
    </span>
    <span class="h-px flex-1 bg-gray-200 dark:bg-gray-700" aria-hidden="true" />
  </div>
</template>
