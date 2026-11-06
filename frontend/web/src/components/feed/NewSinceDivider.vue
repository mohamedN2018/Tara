<script setup lang="ts">
// "New since your last visit" (Tara Intelligence 06 §6.2, 07 WP 4b.7): a divider
// drawn where the rows newer than the viewer's last visit end (`meta.visit.
// anchor_index`), only when there are at least `meta.visit.min_to_show` of them.
// The arrow points up, at the new rows above it; it reads the same in RTL.
import { ArrowUp } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

const { t } = useI18n();
</script>

<template>
  <div class="flex items-center gap-3 px-1 py-1" role="separator" :aria-label="t('homeRefresh.newSince')" data-testid="new-since-divider">
    <span class="h-px flex-1 bg-brand-200 dark:bg-brand-800" aria-hidden="true" />
    <span class="inline-flex shrink-0 items-center gap-1.5 text-xs font-semibold text-brand-700 dark:text-brand-200">
      <ArrowUp class="h-3.5 w-3.5" aria-hidden="true" />
      {{ t("homeRefresh.newSince") }}
    </span>
    <span class="h-px flex-1 bg-brand-200 dark:bg-brand-800" aria-hidden="true" />
  </div>
</template>
