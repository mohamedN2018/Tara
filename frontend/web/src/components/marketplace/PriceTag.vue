<script setup lang="ts">
// Three-state price tag: free, "make an offer" (negotiable with no price), or an
// amount with an optional struck-through original price when on sale.
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { Listing } from "@/types";

import { priceView } from "./money";

const props = withDefaults(
  defineProps<{
    listing: Pick<Listing, "price" | "price_type" | "sale_price" | "currency">;
    size?: "sm" | "lg";
  }>(),
  { size: "sm" },
);
const { t, locale } = useI18n();
const view = computed(() => priceView(props.listing, locale.value));
</script>

<template>
  <p class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5" :class="size === 'lg' ? 'text-2xl' : 'text-base'">
    <template v-if="view.kind === 'free'">
      <span class="font-bold text-emerald-700 dark:text-emerald-400">{{ t("market.priceTypes.free") }}</span>
    </template>
    <template v-else-if="view.kind === 'offer'">
      <span class="font-bold text-brand-600 dark:text-brand-300">{{ t("market.makeOffer") }}</span>
    </template>
    <template v-else>
      <bdi class="font-bold text-brand-600 dark:text-brand-300">{{ view.amount }}</bdi>
      <s v-if="view.was" class="text-xs font-medium text-gray-400 dark:text-gray-500">
        <span class="sr-only">{{ t("market.wasPrice") }}</span><bdi>{{ view.was }}</bdi>
      </s>
      <span
        v-if="view.negotiable"
        class="rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-semibold text-brand-700 dark:bg-brand-950/60 dark:text-brand-300"
      >
        {{ t("market.priceTypes.negotiable") }}
      </span>
    </template>
  </p>
</template>
