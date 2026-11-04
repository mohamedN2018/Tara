<script setup lang="ts">
// Side-by-side comparison of up to 4 listings picked with the compare toggle.
import { ArrowLeft, X } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import AppShell from "@/components/layout/AppShell.vue";
import ListingThumb from "@/components/marketplace/ListingThumb.vue";
import PriceTag from "@/components/marketplace/PriceTag.vue";
import { categoryLabel } from "@/components/marketplace/useCategories";
import { useCompare } from "@/components/marketplace/useCompare";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { relativeTime } from "@/lib/format";
import { marketplaceService } from "@/services/marketplace";
import { useDirectoryStore } from "@/stores/directory";
import type { Listing } from "@/types";

const { t, te } = useI18n();
const compare = useCompare();
const directory = useDirectoryStore();

const listings = ref<Listing[]>([]);
const loading = ref(true);
const error = ref(false);

async function load() {
  loading.value = true;
  error.value = false;
  try {
    const ids = [...compare.selected.value];
    listings.value = await marketplaceService.compare(ids);
    // Drop picks the viewer can no longer open (removed, blocked, deleted).
    const found = new Set(listings.value.map((l) => l.id));
    ids.filter((id) => !found.has(id)).forEach((id) => compare.remove(id));
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(
  () => compare.selected.value.length,
  (n, old) => {
    if (n < old) listings.value = listings.value.filter((l) => compare.has(l.id));
  },
);

type Row = { key: string; label: string; value: (l: Listing) => string };
const rows = computed<Row[]>(() => [
  { key: "price_type", label: t("market.priceType"), value: (l) => t(`market.priceTypes.${l.price_type ?? "fixed"}`) },
  { key: "condition", label: t("market.condition"), value: (l) => t(`market.conditions.${l.condition}`) },
  { key: "category", label: t("market.category"), value: (l) => categoryLabel(l.category, t, te) || "—" },
  { key: "location", label: t("market.location"), value: (l) => l.location || "—" },
  {
    key: "availability",
    label: t("market.availabilityLabel"),
    value: (l) => (l.availability ? t(`market.availability.${l.availability}`) : t(`market.statuses.${l.status}`)),
  },
  { key: "seller", label: t("market.listedBy"), value: (l) => directory.label(l.seller_id) },
  { key: "saves", label: t("market.savesLabel"), value: (l) => String(l.save_count) },
  { key: "listed", label: t("market.listed"), value: (l) => relativeTime(l.created_at) },
]);

// Highlight the lowest price a buyer would pay, when at least two have one.
const cheapestId = computed(() => {
  const priced = listings.value.filter((l) => l.effective_price !== null && l.effective_price !== undefined);
  if (priced.length < 2 || new Set(priced.map((l) => l.currency)).size > 1) return null;
  return priced.reduce((a, b) => (Number(b.effective_price) < Number(a.effective_price) ? b : a)).id;
});
</script>

<template>
  <AppShell>
    <div class="mb-4 flex items-center gap-3">
      <RouterLink :to="{ name: 'marketplace' }" class="icon-btn" :aria-label="t('states.back')">
        <ArrowLeft class="h-5 w-5 rtl:rotate-180" />
      </RouterLink>
      <h1 class="text-xl font-bold">{{ t("market.compare.title") }}</h1>
      <button v-if="listings.length" type="button" class="btn-ghost ms-auto" @click="compare.clear()">
        {{ t("market.compare.clear") }}
      </button>
    </div>

    <LoadingSkeleton v-if="loading" :rows="2" />
    <ErrorState v-else-if="error" @retry="load" />
    <EmptyState v-else-if="listings.length === 0">{{ t("market.compare.empty") }}</EmptyState>

    <div v-else class="card overflow-x-auto">
      <table class="w-full min-w-[34rem] table-fixed border-collapse text-sm">
        <caption class="sr-only">{{ t("market.compare.title") }}</caption>
        <thead>
          <tr>
            <th scope="col" class="w-28 p-3 text-start text-xs font-semibold text-gray-500 dark:text-gray-400">
              <span class="sr-only">{{ t("market.compare.attribute") }}</span>
            </th>
            <th v-for="l in listings" :key="l.id" scope="col" class="p-3 align-top text-start font-normal">
              <div class="relative">
                <button
                  type="button"
                  class="icon-btn absolute -top-1 end-0 h-7 w-7"
                  :aria-label="t('market.compare.removeNamed', { title: l.title })"
                  @click="compare.remove(l.id)"
                >
                  <X class="h-3.5 w-3.5" />
                </button>
                <RouterLink :to="`/marketplace/${l.id}`" class="block pe-8">
                  <ListingThumb :listing="l" class="mb-2" />
                  <p class="line-clamp-2 font-semibold" dir="auto">{{ l.title }}</p>
                </RouterLink>
                <div class="mt-1">
                  <PriceTag :listing="l" />
                  <span
                    v-if="cheapestId === l.id"
                    class="mt-1 inline-block rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300"
                  >
                    {{ t("market.compare.lowest") }}
                  </span>
                </div>
              </div>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.key" class="border-t border-gray-100 dark:border-gray-800">
            <th scope="row" class="p-3 text-start text-xs font-semibold text-gray-500 dark:text-gray-400">
              {{ row.label }}
            </th>
            <td v-for="l in listings" :key="l.id" class="p-3 align-top" dir="auto">{{ row.value(l) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </AppShell>
</template>
