<script setup lang="ts">
import { Info, Plus, SlidersHorizontal } from "lucide-vue-next";
import { computed, defineAsyncComponent, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import AppShell from "@/components/layout/AppShell.vue";
import CompareBar from "@/components/marketplace/CompareBar.vue";
import FilterChip from "@/components/marketplace/FilterChip.vue";
import {
  activeCount,
  type BrowseFilters,
  fromRouteQuery,
  SORTS,
  toApiQuery,
  toRouteQuery,
} from "@/components/marketplace/filters";
import MarketplaceCard from "@/components/marketplace/MarketplaceCard.vue";
import MarketplaceFilters from "@/components/marketplace/MarketplaceFilters.vue";
import SortSheet from "@/components/marketplace/SortSheet.vue";
import SearchBar from "@/components/search/SearchBar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { type ListingFacets, marketplaceService } from "@/services/marketplace";
import { useToastStore } from "@/stores/toasts";
import type { Listing, ListingCategory } from "@/types";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const toasts = useToastStore();

const CreateListingModal = defineAsyncComponent(
  () => import("@/components/marketplace/CreateListingModal.vue"),
);

type Tab = "browse" | "mine" | "saved";
const TABS: Tab[] = ["browse", "mine", "saved"];
const tab = ref<Tab>(TABS.includes(route.query.tab as Tab) ? (route.query.tab as Tab) : "browse");
const categories = ref<ListingCategory[]>([]);
const filters = ref<BrowseFilters>(fromRouteQuery(route.query));
const query = ref(filters.value.q);
const facets = ref<ListingFacets | null>(null);
const showFilters = ref(activeCount(filters.value) > 0);

const listings = ref<Listing[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);
const showCreate = ref(false);

const sortOptions = computed(() => SORTS.map((key) => ({ key, label: t(`market.sort.${key}`) })));
const filterCount = computed(() => activeCount(filters.value));
// Top-level categories as chips; counts come from the facets (which ignore the
// category filter itself, so the other chips keep their numbers).
const categoryChips = computed(() => {
  const counts = new Map((facets.value?.category ?? []).map((c) => [c.slug, c.count]));
  return categories.value
    .filter((c) => !c.parent_id)
    .map((c) => ({ ...c, count: facets.value ? (counts.get(c.slug) ?? 0) : null }))
    .filter((c) => c.count !== 0 || c.slug === filters.value.category);
});

let requestId = 0;
async function fetchPage(more = false) {
  const cur = more ? (cursor.value ?? undefined) : undefined;
  if (tab.value === "mine") return marketplaceService.myListings(cur);
  if (tab.value === "saved") return marketplaceService.savedList(cur);
  return marketplaceService.list(toApiQuery(filters.value, cur));
}

async function loadFacets() {
  if (tab.value !== "browse") return;
  try {
    facets.value = await marketplaceService.facets(toApiQuery(filters.value));
  } catch {
    facets.value = null; // chips just lose their counts
  }
}

async function load() {
  const id = ++requestId;
  loading.value = true;
  error.value = false;
  void loadFacets();
  try {
    const page = await fetchPage(false);
    if (id !== requestId) return; // a newer filter change won
    listings.value = page.data;
    cursor.value = page.page.next_cursor;
    hasMore.value = page.page.has_more;
  } catch {
    if (id === requestId) error.value = true;
  } finally {
    if (id === requestId) loading.value = false;
  }
}

async function loadMore() {
  if (!hasMore.value || loadingMore.value) return;
  loadingMore.value = true;
  try {
    const page = await fetchPage(true);
    listings.value.push(...page.data);
    cursor.value = page.page.next_cursor;
    hasMore.value = page.page.has_more;
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

// Filters live in the URL, so a search can be shared and back/forward restore it.
function syncUrl() {
  const q = tab.value === "browse" ? toRouteQuery(filters.value) : { tab: tab.value };
  router.replace({ query: q });
}

function setFilters(next: BrowseFilters) {
  filters.value = next;
  syncUrl();
  load();
}

function search(q: string) {
  setFilters({ ...filters.value, q });
}

function selectCat(slug: string) {
  setFilters({ ...filters.value, category: filters.value.category === slug ? "" : slug });
}

function setSort(sort: string) {
  setFilters({ ...filters.value, sort: sort as BrowseFilters["sort"] });
}

function switchTab(next: Tab) {
  if (tab.value === next) return;
  tab.value = next;
  syncUrl();
  load();
}

function onUnsaved(id: string) {
  if (tab.value === "saved") listings.value = listings.value.filter((l) => l.id !== id);
}

function onCreated(listing: Listing) {
  showCreate.value = false;
  toasts.success(listing.status === "active" ? t("market.posted") : t("market.pendingReview"));
  // Surface it immediately under "My listings".
  tab.value = "mine";
  listings.value = [listing, ...listings.value.filter((l) => l.id !== listing.id)];
  syncUrl();
  load();
}

watch(
  () => route.query,
  (q) => {
    // Back/forward: only react when the URL no longer matches the state.
    if (tab.value !== "browse" || q.tab) return;
    const next = fromRouteQuery(q);
    if (JSON.stringify(toRouteQuery(next)) === JSON.stringify(toRouteQuery(filters.value))) return;
    filters.value = next;
    query.value = next.q;
    load();
  },
);

onMounted(async () => {
  try {
    categories.value = await marketplaceService.categories();
  } catch (e) {
    categories.value = [];
    toasts.error(e);
  }
  // Opened via the navbar "Create → Listing" shortcut.
  if (route.query.create === "1") {
    showCreate.value = true;
    router.replace({ query: {} });
  }
  await load();
});
</script>

<template>
  <AppShell>
    <div class="mb-4 flex items-center justify-between gap-3">
      <h1 class="text-xl font-bold">{{ t("market.title") }}</h1>
      <button class="btn-primary" @click="showCreate = true">
        <Plus class="h-4 w-4" /> {{ t("market.sell") }}
      </button>
    </div>

    <!-- Tabs -->
    <div class="mb-3 flex gap-1 rounded-xl bg-gray-100 p-1 text-sm dark:bg-gray-800" role="tablist">
      <button
        v-for="tb in TABS"
        :key="tb"
        role="tab"
        :aria-selected="tab === tb"
        class="flex-1 rounded-lg py-1.5 font-medium transition"
        :class="tab === tb ? 'bg-white shadow-sm text-brand-600 dark:bg-gray-900 dark:text-brand-300' : 'text-gray-500 dark:text-gray-400'"
        @click="switchTab(tb)"
      >
        {{ tb === "browse" ? t("market.browse") : tb === "mine" ? t("market.myListings") : t("market.savedTab") }}
      </button>
    </div>

    <!-- Browse: search, category chips, filters, sort -->
    <template v-if="tab === 'browse'">
      <div class="mb-3">
        <SearchBar v-model="query" @submit="search" />
      </div>
      <div class="mb-3 flex items-center gap-2">
        <div class="-mx-1 flex min-w-0 flex-1 gap-2 overflow-x-auto px-1 pb-1">
          <FilterChip
            :label="t('market.allCategories')"
            :active="!filters.category"
            :count="facets && !filters.category ? facets.total : null"
            @toggle="selectCat('')"
          />
          <FilterChip
            v-for="c in categoryChips"
            :key="c.id"
            :label="c.name"
            :count="c.count"
            :active="filters.category === c.slug"
            @toggle="selectCat(c.slug)"
          />
        </div>
      </div>
      <div class="mb-4 flex items-center justify-between gap-2">
        <button
          type="button"
          class="chip min-h-9 text-xs"
          :class="{ 'chip-active': showFilters }"
          :aria-expanded="showFilters"
          aria-controls="market-filters"
          @click="showFilters = !showFilters"
        >
          <SlidersHorizontal class="h-3.5 w-3.5" aria-hidden="true" />
          {{ t("market.filters.title") }}
          <span v-if="filterCount" class="badge">{{ filterCount }}</span>
        </button>
        <p v-if="facets" class="text-xs text-gray-500 dark:text-gray-400" aria-live="polite">
          {{ t("market.filters.results", facets.total) }}
        </p>
        <SortSheet :options="sortOptions" :model-value="filters.sort" @update:model-value="setSort" />
      </div>
      <div v-if="showFilters" id="market-filters">
        <MarketplaceFilters :model-value="filters" :facets="facets" @update:model-value="setFilters" />
      </div>
    </template>

    <p
      class="mb-4 flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-950/40 dark:text-amber-300"
    >
      <Info class="h-4 w-4 shrink-0" />
      {{ t("market.paymentsNote") }}
    </p>

    <LoadingSkeleton v-if="loading" :rows="3" />
    <ErrorState v-else-if="error" @retry="load" />
    <EmptyState v-else-if="listings.length === 0">
      {{ tab === "mine" ? t("market.noMine") : tab === "saved" ? t("market.noSaved") : t("market.empty") }}
    </EmptyState>
    <template v-else>
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <MarketplaceCard v-for="l in listings" :key="l.id" :listing="l" @unsaved="onUnsaved" />
      </div>
      <div v-if="hasMore" class="mt-4 flex justify-center">
        <button class="btn-ghost" :disabled="loadingMore" @click="loadMore">
          {{ loadingMore ? t("states.loading") : t("feed.loadMore") }}
        </button>
      </div>
    </template>

    <!-- room for the floating compare bar -->
    <div class="h-20" aria-hidden="true" />
    <CompareBar />

    <CreateListingModal
      v-if="showCreate"
      :categories="categories"
      @close="showCreate = false"
      @created="onCreated"
    />
  </AppShell>
</template>
