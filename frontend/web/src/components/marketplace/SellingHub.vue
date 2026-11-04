<script setup lang="ts">
// Selling: the seller's overview (listings per status, views, saves,
// inquiries) and their listings, filtered by status, each with the "..."
// menu (edit, publish, reserve, mark sold, archive).
import { Bookmark, Eye, MessageCircle, Plus } from "lucide-vue-next";
import { computed, defineAsyncComponent, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { type ListingDetail, marketplaceService, type SellingSummary } from "@/services/marketplace";
import { useToastStore } from "@/stores/toasts";
import type { Listing } from "@/types";

import FilterChip from "./FilterChip.vue";
import MarketplaceCard from "./MarketplaceCard.vue";
import { useCategories } from "./useCategories";

const emit = defineEmits<{ create: [] }>();
const CreateListingModal = defineAsyncComponent(() => import("./CreateListingModal.vue"));

const { t } = useI18n();
const toasts = useToastStore();
const { categories } = useCategories();

// Chip order: what needs the seller first.
const STATUSES = ["active", "reserved", "pending_review", "draft", "rejected", "sold", "archived", "removed"] as const;
const status = ref<string>("");
const summary = ref<SellingSummary | null>(null);
const listings = ref<Listing[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);
const editing = ref<ListingDetail | null>(null);

const total = computed(() => (summary.value ? Object.values(summary.value.counts).reduce((a, b) => a + b, 0) : null));
const chips = computed(() =>
  STATUSES.map((s) => ({ s, count: summary.value?.counts[s] ?? null })).filter(
    (c) => c.count !== 0 || c.s === status.value,
  ),
);

async function loadSummary() {
  try {
    summary.value = await marketplaceService.sellingSummary();
  } catch {
    summary.value = null; // the numbers just stay hidden
  }
}

let requestId = 0;
async function load() {
  const id = ++requestId;
  loading.value = true;
  error.value = false;
  try {
    const page = await marketplaceService.myListings(undefined, status.value);
    if (id !== requestId) return;
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
    const page = await marketplaceService.myListings(cursor.value ?? undefined, status.value);
    listings.value.push(...page.data);
    cursor.value = page.page.next_cursor;
    hasMore.value = page.page.has_more;
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

function pick(next: string) {
  status.value = status.value === next ? "" : next;
  load();
}

function onUpdated(next: Listing) {
  // Left in place even when it no longer matches the chip, until the next load.
  listings.value = listings.value.map((l) => (l.id === next.id ? { ...l, ...next } : l));
  void loadSummary();
}

async function edit(listing: Listing) {
  try {
    editing.value = await marketplaceService.get(listing.id);
  } catch (e) {
    toasts.error(e);
  }
}

function onSaved(next: ListingDetail) {
  editing.value = null;
  toasts.success(t("commerce.listing.saved"));
  onUpdated(next);
}

onMounted(() => {
  void loadSummary();
  void load();
});
defineExpose({ reload: () => (loadSummary(), load()) });
</script>

<template>
  <div class="space-y-4" data-testid="selling-hub">
    <section class="card p-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-lg font-bold">{{ t("commerce.selling.title") }}</h2>
        <button type="button" class="btn-primary text-sm" @click="emit('create')">
          <Plus class="h-4 w-4" aria-hidden="true" /> {{ t("commerce.nav.create") }}
        </button>
      </div>
      <dl v-if="summary" class="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="selling-summary">
        <div class="rounded-xl bg-gray-50 p-3 dark:bg-gray-800/60">
          <dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("commerce.selling.live") }}</dt>
          <dd class="text-xl font-bold tabular-nums">{{ summary.counts.active + summary.counts.reserved }}</dd>
        </div>
        <div class="rounded-xl bg-gray-50 p-3 dark:bg-gray-800/60">
          <dt class="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400"><Eye class="h-3.5 w-3.5" aria-hidden="true" /> {{ t("commerce.selling.views") }}</dt>
          <dd class="text-xl font-bold tabular-nums">{{ summary.views }}</dd>
        </div>
        <div class="rounded-xl bg-gray-50 p-3 dark:bg-gray-800/60">
          <dt class="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400"><Bookmark class="h-3.5 w-3.5" aria-hidden="true" /> {{ t("commerce.selling.saves") }}</dt>
          <dd class="text-xl font-bold tabular-nums">{{ summary.saves }}</dd>
        </div>
        <div class="rounded-xl bg-gray-50 p-3 dark:bg-gray-800/60">
          <dt class="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400"><MessageCircle class="h-3.5 w-3.5" aria-hidden="true" /> {{ t("commerce.selling.inquiries") }}</dt>
          <dd class="text-xl font-bold tabular-nums">{{ summary.inquiries }}</dd>
        </div>
      </dl>
      <p v-if="summary && (summary.counts.rejected || summary.counts.removed)" class="mt-3 text-xs text-amber-700 dark:text-amber-300">
        {{ t("commerce.selling.needsAttention", summary.counts.rejected + summary.counts.removed) }}
      </p>
    </section>

    <section class="card p-4">
      <h2 class="mb-3 text-base font-semibold">{{ t("commerce.selling.yourListings") }}</h2>
      <div class="-mx-1 mb-4 flex gap-2 overflow-x-auto px-1 pb-1" role="group" :aria-label="t('commerce.selling.filter')">
        <FilterChip :label="t('market.allCategories')" :active="!status" :count="total" @toggle="pick('')" />
        <FilterChip
          v-for="c in chips"
          :key="c.s"
          :label="t(`market.statuses.${c.s}`)"
          :count="c.count"
          :active="status === c.s"
          @toggle="pick(c.s)"
        />
      </div>

      <LoadingSkeleton v-if="loading" :rows="2" />
      <ErrorState v-else-if="error" @retry="load" />
      <EmptyState v-else-if="!listings.length">{{ status ? t("commerce.selling.emptyStatus") : t("market.noMine") }}</EmptyState>
      <template v-else>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
          <MarketplaceCard v-for="l in listings" :key="l.id" :listing="l" manage @updated="onUpdated" @edit="edit" />
        </div>
        <div v-if="hasMore" class="mt-4 flex justify-center">
          <button class="btn-ghost" :disabled="loadingMore" @click="loadMore">
            {{ loadingMore ? t("states.loading") : t("feed.loadMore") }}
          </button>
        </div>
      </template>
    </section>

    <CreateListingModal
      v-if="editing"
      :categories="categories"
      :listing="editing"
      @close="editing = null"
      @saved="onSaved"
    />
  </div>
</template>
