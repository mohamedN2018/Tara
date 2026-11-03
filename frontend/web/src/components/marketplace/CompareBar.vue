<script setup lang="ts">
// Floating bar shown while listings are picked for comparison.
import { Scale, X } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

import { MAX_COMPARE, useCompare } from "./useCompare";

const { t } = useI18n();
const compare = useCompare();
</script>

<template>
  <div
    v-if="compare.selected.value.length"
    class="fixed inset-x-0 bottom-[calc(4.5rem+env(safe-area-inset-bottom,0px))] z-30 flex justify-center px-4 lg:bottom-6"
    role="region"
    :aria-label="t('market.compare.title')"
  >
    <div class="card flex w-full max-w-md items-center gap-3 px-4 py-2.5 shadow-pop">
      <Scale class="h-5 w-5 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden="true" />
      <p class="min-w-0 flex-1 truncate text-sm font-semibold" aria-live="polite">
        {{ t("market.compare.selected", { n: compare.selected.value.length, max: MAX_COMPARE }) }}
      </p>
      <button type="button" class="icon-btn h-8 w-8" :aria-label="t('market.compare.clear')" @click="compare.clear()">
        <X class="h-4 w-4" />
      </button>
      <RouterLink
        :to="{ name: 'marketplace-compare' }"
        class="btn-primary px-3 py-1.5"
        :class="{ 'pointer-events-none opacity-50': compare.selected.value.length < 2 }"
        :aria-disabled="compare.selected.value.length < 2"
      >
        {{ t("market.compare.open") }}
      </RouterLink>
    </div>
  </div>
</template>
