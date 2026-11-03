<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import AppShell from "@/components/layout/AppShell.vue";
import MarketplaceCard from "@/components/marketplace/MarketplaceCard.vue";
import PostCard from "@/components/post/PostCard.vue";
import SearchBar from "@/components/search/SearchBar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { marketplaceService } from "@/services/marketplace";
import { postService } from "@/services/post";
import { type Suggestion, searchService } from "@/services/search";
import { useDirectoryStore } from "@/stores/directory";
import type { Listing, Post } from "@/types";

const directory = useDirectoryStore();

const { t } = useI18n();
const route = useRoute();
const router = useRouter();

const TABS = ["all", "people", "posts", "listings"] as const;
type Tab = (typeof TABS)[number];

const query = ref("");
const tab = ref<Tab>("all");
const loading = ref(false);
const searched = ref(false);
const error = ref(false);

const people = ref<Suggestion[]>([]);
const posts = ref<Post[]>([]);
const listings = ref<Listing[]>([]);

async function run() {
  const q = query.value.trim();
  if (!q) return;
  if (route.query.q !== q) router.replace({ name: "search", query: { q } });
  loading.value = true;
  searched.value = true;
  error.value = false;
  try {
    if (q.startsWith("#") && q.length > 1) {
      people.value = [];
      listings.value = [];
      posts.value = await postService.byHashtag(q.slice(1));
      return;
    }
    const hits = await searchService.query(q, "all");
    people.value = hits.filter((h) => h.type === "user");
    // Resolve full objects so posts/listings render as real cards.
    const postHits = hits.filter((h) => h.type === "post");
    const listingHits = hits.filter((h) => h.type === "listing");
    [posts.value, listings.value] = await Promise.all([
      Promise.all(postHits.map((h) => postService.get(h.id).catch(() => null))).then((r) =>
        r.filter((p): p is Post => !!p),
      ),
      Promise.all(listingHits.map((h) => marketplaceService.get(h.id).catch(() => null))).then((r) =>
        r.filter((l): l is Listing => !!l),
      ),
    ]);
  } catch {
    people.value = [];
    posts.value = [];
    listings.value = [];
    error.value = true;
  } finally {
    loading.value = false;
  }
}

function syncFromRoute() {
  const q = (route.query.q as string) ?? "";
  query.value = q;
  if (q.trim()) run();
}

watch(() => route.query.q, syncFromRoute);
onMounted(syncFromRoute);

const isEmpty = computed(
  () => searched.value && !people.value.length && !posts.value.length && !listings.value.length,
);
const show = (section: Tab) => tab.value === "all" || tab.value === section;
</script>

<template>
  <AppShell>
    <h1 class="mb-4 text-xl font-bold">{{ t("search.title") }}</h1>
    <SearchBar v-model="query" autofocus @submit="run" />

    <div class="mt-3 flex gap-1 overflow-x-auto rounded-xl bg-gray-100 p-1 text-sm dark:bg-gray-800">
      <button
        v-for="tb in TABS"
        :key="tb"
        class="flex-1 whitespace-nowrap rounded-lg px-3 py-1.5 font-medium transition"
        :class="tab === tb ? 'bg-white text-brand-600 shadow-sm dark:bg-gray-900' : 'text-gray-500'"
        @click="tab = tb"
      >
        {{ t(`search.${tb}`) }}
      </button>
    </div>

    <div class="mt-4">
      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="error" @retry="run" />
      <template v-else-if="searched">
        <EmptyState v-if="isEmpty">{{ t("search.noResults", { q: query }) }}</EmptyState>
        <template v-else>
          <section v-if="show('people') && people.length" class="mb-6">
            <h2 class="mb-2 text-sm font-semibold text-gray-500">{{ t("search.people") }}</h2>
            <ul class="space-y-2">
              <li v-for="p in people" :key="p.id">
                <RouterLink
                  :to="{ name: 'profile-by-id', params: { id: p.id } }"
                  class="card flex items-center gap-3 p-3 transition hover:shadow-sm"
                >
                  <UserAvatar :name="directory.label(p.id)" :media-id="directory.avatarOf(p.id)" />
                  <span class="min-w-0">
                    <span class="block truncate text-sm font-medium" dir="auto">{{ directory.label(p.id) }}</span>
                    <span v-if="p.snippet" class="block truncate text-xs text-gray-500" dir="auto">{{ p.snippet }}</span>
                  </span>
                </RouterLink>
              </li>
            </ul>
          </section>

          <section v-if="show('listings') && listings.length" class="mb-6">
            <h2 class="mb-2 text-sm font-semibold text-gray-500">{{ t("search.listings") }}</h2>
            <div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <MarketplaceCard v-for="l in listings" :key="l.id" :listing="l" />
            </div>
          </section>

          <section v-if="show('posts') && posts.length">
            <h2 class="mb-2 text-sm font-semibold text-gray-500">{{ t("search.posts") }}</h2>
            <div class="space-y-4">
              <PostCard v-for="post in posts" :key="post.id" :post="post" />
            </div>
          </section>
        </template>
      </template>
    </div>
  </AppShell>
</template>
