<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import AppShell from "@/components/layout/AppShell.vue";
import MarketplaceCard from "@/components/marketplace/MarketplaceCard.vue";
import PostCard from "@/components/post/PostCard.vue";
import SearchBar from "@/components/search/SearchBar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { type SearchResults, searchService } from "@/services/search";

const { t } = useI18n();

const query = ref("");
const results = ref<SearchResults | null>(null);
const loading = ref(false);
const searched = ref(false);

async function run() {
  const q = query.value.trim();
  if (!q) return;
  loading.value = true;
  searched.value = true;
  try {
    results.value = await searchService.query(q);
  } catch {
    results.value = { people: [], posts: [], listings: [] };
  } finally {
    loading.value = false;
  }
}

function isEmpty(r: SearchResults) {
  return r.people.length === 0 && r.posts.length === 0 && r.listings.length === 0;
}
</script>

<template>
  <AppShell>
    <h1 class="mb-4 text-xl font-bold">{{ t("search.title") }}</h1>
    <SearchBar v-model="query" autofocus @submit="run" />

    <div class="mt-4">
      <LoadingSkeleton v-if="loading" :rows="3" />
      <template v-else-if="results">
        <EmptyState v-if="isEmpty(results)">{{ t("search.noResults", { q: query }) }}</EmptyState>
        <template v-else>
          <section v-if="results.people.length" class="mb-6">
            <h2 class="mb-2 text-sm font-semibold text-gray-500">{{ t("search.people") }}</h2>
            <ul class="space-y-2">
              <li v-for="p in results.people" :key="p.handle">
                <RouterLink :to="`/u/${p.handle}`" class="card flex items-center gap-3 p-3">
                  <UserAvatar :name="p.display_name" :media-id="p.avatar_media_id" />
                  <span>
                    <span class="block text-sm font-medium">{{ p.display_name }}</span>
                    <span class="block text-xs text-gray-500">@{{ p.handle }}</span>
                  </span>
                </RouterLink>
              </li>
            </ul>
          </section>

          <section v-if="results.listings.length" class="mb-6">
            <h2 class="mb-2 text-sm font-semibold text-gray-500">{{ t("search.listings") }}</h2>
            <div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <MarketplaceCard v-for="l in results.listings" :key="l.id" :listing="l" />
            </div>
          </section>

          <section v-if="results.posts.length">
            <h2 class="mb-2 text-sm font-semibold text-gray-500">{{ t("search.posts") }}</h2>
            <div class="space-y-4">
              <PostCard v-for="post in results.posts" :key="post.id" :post="post" />
            </div>
          </section>
        </template>
      </template>
    </div>
  </AppShell>
</template>
