<script setup lang="ts">
import { useI18n } from "vue-i18n";

import type { SponsoredSlot } from "@/types";

const { ad } = defineProps<{ ad: SponsoredSlot }>();
const { t } = useI18n();
</script>

<template>
  <article class="card border-brand-200 p-4 dark:border-brand-900">
    <span class="text-[10px] font-semibold uppercase tracking-wide text-brand-500">
      {{ t("feed.sponsored") }}
    </span>
    <h3 class="mt-1 text-sm font-bold">{{ ad.headline }}</h3>
    <p v-if="ad.body" class="mt-1 text-sm text-gray-600 dark:text-gray-300">{{ ad.body }}</p>
    <button v-if="ad.cta" class="btn-primary mt-3 w-full">{{ ad.cta }}</button>
  </article>
</template>
