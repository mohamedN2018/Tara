<script setup lang="ts">
import { Info, Plus } from "lucide-vue-next";
import { defineAsyncComponent, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import AppShell from "@/components/layout/AppShell.vue";
import MarketplaceCard from "@/components/marketplace/MarketplaceCard.vue";
import SearchBar from "@/components/search/SearchBar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { marketplaceService } from "@/services/marketplace";
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
const tab = ref<Tab>("browse");
const categories = ref<ListingCategory[]>([]);
const selectedCat = ref(""); // slug, "" = all
const query = ref("");

const listings = ref<Listing[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);
const showCreate = ref(false);

async function fetchPage(more = false) {
  const cur = more ? (cursor.value ?? undefined) : undefined;
  if (tab.value === "mine") return marketplaceService.myListings(cur);
  if (tab.value === "saved") return marketplaceService.savedList(cur);
  return marketplaceService.list({
    q: query.value || undefined,
    category: selectedCat.value || undefined,
    cursor: cur,
  });
}

async function load() {
  loading.value = true;
  error.value = false;
  try {
    const page = await fetchPage(false);
    listings.value = page.data;
    cursor.value = page.page.next_cursor;
    hasMore.value = page.page.has_more;
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
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

function switchTab(next: Tab) {
  if (tab.value === next) return;
  tab.value = next;
  load();
}

function selectCat(slug: string) {
  selectedCat.value = selectedCat.value === slug ? "" : slug;
  load();
}

function onCreated(listing: Listing) {
  showCreate.value = false;
  toasts.success(t("market.posted"));
  // Surface it immediately under "My listings".
  tab.value = "mine";
  listings.value = [listing, ...listings.value.filter((l) => l.id !== listing.id)];
  load();
}

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
    <div class="mb-3 flex gap-1 rounded-xl bg-gray-100 p-1 text-sm dark:bg-gray-800">
      <button
        v-for="tb in (['browse', 'mine', 'saved'] as Tab[])"
        :key="tb"
        class="flex-1 rounded-lg py-1.5 font-medium transition"
        :class="tab === tb ? 'bg-white shadow-sm text-brand-600 dark:bg-gray-900' : 'text-gray-500'"
        @click="switchTab(tb)"
      >
        {{ tb === "browse" ? t("market.browse") : tb === "mine" ? t("market.myListings") : t("market.savedTab") }}
      </button>
    </div>

    <!-- Browse filters -->
    <template v-if="tab === 'browse'">
      <div class="mb-3">
        <SearchBar v-model="query" @submit="load" />
      </div>
      <div class="mb-4 flex flex-wrap gap-2">
        <button
          class="rounded-full border px-3 py-1 text-xs font-medium transition"
          :class="!selectedCat ? 'border-brand-600 bg-brand-50 text-brand-600 dark:bg-brand-950/40' : 'border-gray-200 text-gray-500 hover:bg-gray-100 dark:border-gray-700 dark:hover:bg-gray-800'"
          @click="selectCat('')"
        >
          {{ t("market.allCategories") }}
        </button>
        <button
          v-for="c in categories"
          :key="c.id"
          class="rounded-full border px-3 py-1 text-xs font-medium transition"
          :class="selectedCat === c.slug ? 'border-brand-600 bg-brand-50 text-brand-600 dark:bg-brand-950/40' : 'border-gray-200 text-gray-500 hover:bg-gray-100 dark:border-gray-700 dark:hover:bg-gray-800'"
          @click="selectCat(c.slug)"
        >
          {{ c.name }}
        </button>
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
        <MarketplaceCard v-for="l in listings" :key="l.id" :listing="l" />
      </div>
      <div v-if="hasMore" class="mt-4 flex justify-center">
        <button class="btn-ghost" :disabled="loadingMore" @click="loadMore">
          {{ loadingMore ? t("states.loading") : t("feed.loadMore") }}
        </button>
      </div>
    </template>

    <CreateListingModal
      v-if="showCreate"
      :categories="categories"
      @close="showCreate = false"
      @created="onCreated"
    />
  </AppShell>
</template>
