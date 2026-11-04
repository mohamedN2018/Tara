<script setup lang="ts">
import { Info, SlidersHorizontal } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

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
import { type MarketTab, tabFromQuery } from "@/components/marketplace/hubs";
import MarketplaceCard from "@/components/marketplace/MarketplaceCard.vue";
import MarketplaceFilters from "@/components/marketplace/MarketplaceFilters.vue";
import MarketplaceInbox from "@/components/marketplace/MarketplaceInbox.vue";
import MarketplaceLayout from "@/components/marketplace/MarketplaceLayout.vue";
import MarketplaceNotifications from "@/components/marketplace/MarketplaceNotifications.vue";
import SellingHub from "@/components/marketplace/SellingHub.vue";
import SortSheet from "@/components/marketplace/SortSheet.vue";
import { categoryLabel, useCategories } from "@/components/marketplace/useCategories";
import SponsoredCard from "@/components/post/SponsoredCard.vue";
import SearchBar from "@/components/search/SearchBar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { adsService } from "@/services/ads";
import { type ListingFacets, marketplaceService } from "@/services/marketplace";
import { useToastStore } from "@/stores/toasts";
import type { Listing, SponsoredSlot } from "@/types";

const { t, te } = useI18n();
const route = useRoute();
const router = useRouter();
const toasts = useToastStore();
const { categories } = useCategories();

const layout = ref<InstanceType<typeof MarketplaceLayout> | null>(null);
const selling = ref<InstanceType<typeof SellingHub> | null>(null);
const tab = ref<MarketTab>(tabFromQuery(route.query.tab));
const filters = ref<BrowseFilters>(fromRouteQuery(route.query));
const query = ref(filters.value.q);
const facets = ref<ListingFacets | null>(null);
const showFilters = ref(activeCount(filters.value) > 0);
// Buying: what I saved, or the sellers I messaged.
const buying = ref<"saved" | "messaged">(route.query.view === "messaged" ? "messaged" : "saved");

const listings = ref<Listing[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);
// One sponsored cell in the browse grid, when ads serves one (ADS_SERVING_ENABLED).
const sponsored = ref<SponsoredSlot | null>(null);
const SPONSORED_AT = 4;

const sortOptions = computed(() => SORTS.map((key) => ({ key, label: t(`market.sort.${key}`) })));
const filterCount = computed(() => activeCount(filters.value));
const showsGrid = computed(() => tab.value === "browse" || (tab.value === "buying" && buying.value === "saved"));
const heading = computed(() => {
  if (tab.value !== "browse") return "";
  if (filters.value.q) return t("commerce.browse.resultsFor", { q: filters.value.q });
  const cat = categories.value.find((c) => c.slug === filters.value.category);
  return cat ? categoryLabel(cat, t, te) : t("commerce.browse.picks");
});
// Top-level categories as chips (phones; desktop has them in the column).
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
  if (tab.value === "buying") return marketplaceService.savedList(cur);
  return marketplaceService.list(toApiQuery(filters.value, cur));
}

async function loadFacets() {
  try {
    facets.value = await marketplaceService.facets(toApiQuery(filters.value));
  } catch {
    facets.value = null; // chips just lose their counts
  }
}

async function loadSponsored() {
  try {
    sponsored.value = await adsService.slot("marketplace");
  } catch {
    sponsored.value = null; // an ad never disturbs the marketplace
  }
}

async function load() {
  const id = ++requestId;
  if (!showsGrid.value) return;
  loading.value = true;
  error.value = false;
  if (tab.value === "browse") {
    void loadFacets();
    if (!sponsored.value) void loadSponsored();
  }
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
function setFilters(next: BrowseFilters) {
  filters.value = next;
  router.replace({ query: toRouteQuery(next) });
  load();
}

const search = (q: string) => setFilters({ ...filters.value, q });
const selectCat = (slug: string) =>
  setFilters({ ...filters.value, category: filters.value.category === slug ? "" : slug });
const setSort = (sort: string) => setFilters({ ...filters.value, sort: sort as BrowseFilters["sort"] });

function setBuying(view: "saved" | "messaged") {
  buying.value = view;
  router.replace({ query: { tab: "buying", ...(view === "messaged" ? { view } : {}) } });
  load();
}

function onUnsaved(id: string) {
  if (tab.value === "buying") listings.value = listings.value.filter((l) => l.id !== id);
}

// What the page shows, as one comparable value.
const signature = (tb: MarketTab, f: BrowseFilters, b: string) =>
  JSON.stringify([tb, tb === "browse" ? toRouteQuery(f) : null, tb === "buying" ? b : null]);

// The navigation column and pills are links: the URL is the state (and
// back/forward restore it). Changes made here already loaded.
watch(
  () => route.query,
  (q) => {
    if (q.create === "1") openCreate();
    const nextTab = tabFromQuery(q.tab);
    const next = fromRouteQuery(q);
    const nextBuying = q.view === "messaged" ? "messaged" : "saved";
    if (signature(nextTab, next, nextBuying) === signature(tab.value, filters.value, buying.value)) return;
    tab.value = nextTab;
    filters.value = next;
    query.value = next.q;
    buying.value = nextBuying;
    load();
  },
);

// The layout moves to Selling after a create; when already there, refresh it.
function onCreated() {
  if (tab.value === "selling") selling.value?.reload();
}

function openCreate() {
  layout.value?.openCreate();
  if (route.query.create) router.replace({ query: { ...route.query, create: undefined } });
}

onMounted(async () => {
  // Opened via the top bar's "Create → Listing" shortcut.
  if (route.query.create === "1") openCreate();
  await load();
});
</script>

<template>
  <MarketplaceLayout ref="layout" :active="tab" :category="filters.category" :q="filters.q" @created="onCreated">
    <!-- Browse -->
    <template v-if="tab === 'browse'">
      <div class="mb-3 lg:hidden">
        <SearchBar v-model="query" @submit="search" />
      </div>
      <div class="-mx-1 mb-3 flex gap-2 overflow-x-auto px-1 pb-1 lg:hidden">
        <FilterChip
          :label="t('market.allCategories')"
          :active="!filters.category"
          :count="facets && !filters.category ? facets.total : null"
          @toggle="selectCat('')"
        />
        <FilterChip
          v-for="c in categoryChips"
          :key="c.id"
          :label="categoryLabel(c, t, te)"
          :count="c.count"
          :active="filters.category === c.slug"
          @toggle="selectCat(c.slug)"
        />
      </div>
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-lg font-bold" dir="auto" data-testid="browse-heading">{{ heading }}</h2>
        <div class="flex items-center gap-2">
          <p v-if="facets" class="text-xs text-gray-500 dark:text-gray-400" aria-live="polite">
            {{ t("market.filters.results", facets.total) }}
          </p>
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
          <SortSheet :options="sortOptions" :model-value="filters.sort" @update:model-value="setSort" />
        </div>
      </div>
      <div v-if="showFilters" id="market-filters">
        <MarketplaceFilters :model-value="filters" :facets="facets" @update:model-value="setFilters" />
      </div>
    </template>

    <!-- Buying: saved listings, or the sellers I messaged -->
    <div v-else-if="tab === 'buying'" class="mb-3">
      <h2 class="mb-3 text-lg font-bold">{{ t("commerce.nav.buying") }}</h2>
      <div class="flex gap-1 rounded-xl bg-gray-100 p-1 text-sm dark:bg-gray-800" role="tablist" :aria-label="t('commerce.nav.buying')">
        <button
          v-for="v in (['saved', 'messaged'] as const)"
          :key="v"
          role="tab"
          :aria-selected="buying === v"
          class="flex-1 rounded-lg py-1.5 font-medium transition"
          :class="buying === v ? 'bg-white text-brand-600 shadow-sm dark:bg-gray-900 dark:text-brand-300' : 'text-gray-500 dark:text-gray-400'"
          :data-testid="`buying-${v}`"
          @click="setBuying(v)"
        >
          {{ v === "saved" ? t("market.savedTab") : t("commerce.buying.messaged") }}
        </button>
      </div>
    </div>

    <MarketplaceNotifications v-if="tab === 'notifications'" />
    <div v-else-if="tab === 'inbox'">
      <h2 class="mb-3 text-lg font-bold">{{ t("commerce.inbox.title") }}</h2>
      <MarketplaceInbox />
    </div>
    <SellingHub v-else-if="tab === 'selling'" ref="selling" @create="layout?.openCreate()" />
    <MarketplaceInbox v-else-if="tab === 'buying' && buying === 'messaged'" role="buyer" :switchable="false" />

    <template v-else>
      <p
        class="mb-4 flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-950/40 dark:text-amber-300"
      >
        <Info class="h-4 w-4 shrink-0" aria-hidden="true" />
        {{ t("market.paymentsNote") }}
      </p>

      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="error" @retry="load" />
      <EmptyState v-else-if="listings.length === 0">
        {{ tab === "buying" ? t("market.noSaved") : t("market.empty") }}
      </EmptyState>
      <template v-else>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5" data-testid="listing-grid">
          <template v-for="(l, i) in listings" :key="l.id">
            <div v-if="tab === 'browse' && sponsored && i === SPONSORED_AT" class="col-span-2 sm:col-span-1">
              <SponsoredCard :ad="sponsored" />
            </div>
            <MarketplaceCard :listing="l" @unsaved="onUnsaved" />
          </template>
        </div>
        <div v-if="hasMore" class="mt-4 flex justify-center">
          <button class="btn-ghost" :disabled="loadingMore" @click="loadMore">
            {{ loadingMore ? t("states.loading") : t("feed.loadMore") }}
          </button>
        </div>
      </template>
    </template>

    <!-- room for the floating compare bar -->
    <div class="h-20" aria-hidden="true" />
    <CompareBar />
  </MarketplaceLayout>
</template>
