<script setup lang="ts">
import { Info } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import AppShell from "@/components/layout/AppShell.vue";
import MarketplaceCard from "@/components/marketplace/MarketplaceCard.vue";
import SearchBar from "@/components/search/SearchBar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { marketplaceService } from "@/services/marketplace";
import type { Listing } from "@/types";

const { t } = useI18n();

const listings = ref<Listing[]>([]);
const query = ref("");
const loading = ref(true);
const error = ref(false);

async function load() {
  loading.value = true;
  error.value = false;
  try {
    const page = await marketplaceService.list({ q: query.value || undefined });
    listings.value = page.data;
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <AppShell>
    <div class="mb-4 flex items-center justify-between gap-3">
      <h1 class="text-xl font-bold">{{ t("market.title") }}</h1>
    </div>

    <div class="mb-3">
      <SearchBar v-model="query" @submit="load" />
    </div>

    <p
      class="mb-4 flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-950/40 dark:text-amber-300"
    >
      <Info class="h-4 w-4 shrink-0" />
      {{ t("market.paymentsNote") }}
    </p>

    <LoadingSkeleton v-if="loading" :rows="3" />
    <ErrorState v-else-if="error" @retry="load" />
    <EmptyState v-else-if="listings.length === 0">{{ t("market.empty") }}</EmptyState>
    <div v-else class="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <MarketplaceCard v-for="l in listings" :key="l.id" :listing="l" />
    </div>
  </AppShell>
</template>
