<script setup lang="ts">
// A seller's shop: their summary, their public listings and their buyer
// reviews (read-only). Used by the /marketplace/sellers/:id page and meant for
// the profile's "Marketplace" tab (export for the profile track).
import { onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { marketplaceService } from "@/services/marketplace";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";
import type { Listing } from "@/types";

import MarketplaceCard from "./MarketplaceCard.vue";
import SellerCard from "./SellerCard.vue";
import SellerReviews from "./SellerReviews.vue";

const props = withDefaults(defineProps<{ sellerId: string; summary?: boolean }>(), { summary: true });
const { t } = useI18n();
const auth = useAuthStore();
const toasts = useToastStore();

const listings = ref<Listing[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);

async function load() {
  loading.value = true;
  error.value = false;
  try {
    // Available and reserved: what a buyer can still ask about.
    const page = await marketplaceService.list({ seller_id: props.sellerId, availability: "available,reserved" });
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
    const page = await marketplaceService.list({
      seller_id: props.sellerId,
      availability: "available,reserved",
      cursor: cursor.value ?? undefined,
    });
    listings.value.push(...page.data);
    cursor.value = page.page.next_cursor;
    hasMore.value = page.page.has_more;
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

onMounted(load);
watch(() => props.sellerId, load);
</script>

<template>
  <div class="space-y-4" data-testid="seller-shop">
    <div v-if="summary" class="card p-4">
      <SellerCard :seller-id="sellerId" :shop-link="false" class="!mt-0" />
      <RouterLink
        v-if="auth.account?.id === sellerId"
        :to="{ path: '/marketplace', query: { tab: 'selling' } }"
        class="btn-ghost mt-3 w-full text-sm"
      >
        {{ t("commerce.shop.manage") }}
      </RouterLink>
    </div>

    <section class="card p-4" :aria-labelledby="`shop-listings-${sellerId}`">
      <h2 :id="`shop-listings-${sellerId}`" class="mb-3 text-lg font-bold">{{ t("commerce.shop.listings") }}</h2>
      <LoadingSkeleton v-if="loading" :rows="2" />
      <ErrorState v-else-if="error" @retry="load" />
      <EmptyState v-else-if="!listings.length">{{ t("commerce.shop.empty") }}</EmptyState>
      <template v-else>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
          <MarketplaceCard v-for="l in listings" :key="l.id" :listing="l" />
        </div>
        <div v-if="hasMore" class="mt-4 flex justify-center">
          <button class="btn-ghost" :disabled="loadingMore" @click="loadMore">
            {{ loadingMore ? t("states.loading") : t("feed.loadMore") }}
          </button>
        </div>
      </template>
    </section>

    <section class="card p-4">
      <SellerReviews :seller-id="sellerId" />
    </section>
  </div>
</template>
