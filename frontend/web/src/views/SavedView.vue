<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import AppShell from "@/components/layout/AppShell.vue";
import MarketplaceCard from "@/components/marketplace/MarketplaceCard.vue";
import PostCard from "@/components/post/PostCard.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { marketplaceService } from "@/services/marketplace";
import { postService } from "@/services/post";
import { useToastStore } from "@/stores/toasts";
import type { Listing, Post } from "@/types";

const { t } = useI18n();
const toasts = useToastStore();

type Tab = "posts" | "listings";
const tab = ref<Tab>("posts");
const posts = ref<Post[]>([]);
const listings = ref<Listing[]>([]);
const loaded = ref<Record<Tab, boolean>>({ posts: false, listings: false });
const cursors = ref<Record<Tab, string | null>>({ posts: null, listings: null });
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);

async function fetchPage(tb: Tab, cursor?: string) {
  if (tb === "posts") {
    const page = await postService.savedPage(cursor);
    posts.value = cursor ? [...posts.value, ...page.posts] : page.posts;
    cursors.value.posts = page.nextCursor;
  } else {
    const page = await marketplaceService.savedList(cursor);
    listings.value = cursor ? [...listings.value, ...page.data] : page.data;
    cursors.value.listings = page.page.next_cursor;
  }
}

async function load(tb: Tab) {
  loading.value = true;
  error.value = false;
  try {
    await fetchPage(tb);
    loaded.value[tb] = true;
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

async function loadMore() {
  const cursor = cursors.value[tab.value];
  if (!cursor || loadingMore.value) return;
  loadingMore.value = true;
  try {
    await fetchPage(tab.value, cursor);
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

function switchTab(tb: Tab) {
  if (tab.value === tb) return;
  tab.value = tb;
  if (!loaded.value[tb]) load(tb);
}

onMounted(() => load("posts"));
</script>

<template>
  <AppShell>
    <div class="mx-auto w-full max-w-[600px] space-y-4">
      <h1 class="px-1 text-xl font-bold">{{ t("saved.title") }}</h1>

      <div class="flex gap-1 rounded-xl bg-gray-100 p-1 text-sm dark:bg-gray-800">
        <button
          v-for="tb in (['posts', 'listings'] as Tab[])"
          :key="tb"
          class="flex-1 rounded-lg py-1.5 font-medium transition"
          :class="tab === tb ? 'bg-white text-brand-600 shadow-sm dark:bg-gray-900 dark:text-brand-300' : 'text-gray-500 dark:text-gray-400'"
          @click="switchTab(tb)"
        >
          {{ tb === "posts" ? t("saved.tabPosts") : t("saved.tabListings") }}
        </button>
      </div>

      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="error" @retry="load(tab)" />
      <template v-else-if="tab === 'posts'">
        <EmptyState v-if="posts.length === 0">{{ t("saved.empty") }}</EmptyState>
        <PostCard v-for="p in posts" v-else :key="p.id" :post="p" />
      </template>
      <template v-else>
        <EmptyState v-if="listings.length === 0">{{ t("market.noSaved") }}</EmptyState>
        <div v-else class="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <MarketplaceCard v-for="l in listings" :key="l.id" :listing="l" />
        </div>
      </template>
      <button v-if="!loading && !error && cursors[tab]" class="btn-ghost mx-auto block" :disabled="loadingMore" @click="loadMore">
        {{ loadingMore ? t("states.loading") : t("states.loadMore") }}
      </button>
    </div>
  </AppShell>
</template>
