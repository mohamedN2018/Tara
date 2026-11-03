<script setup lang="ts">
import { ArrowLeft, ArrowRight, Info, SlidersHorizontal } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import AppShell from "@/components/layout/AppShell.vue";
import MarketplaceCard from "@/components/marketplace/MarketplaceCard.vue";
import PostCard from "@/components/post/PostCard.vue";
import EventResult from "@/components/search/EventResult.vue";
import GroupResult from "@/components/search/GroupResult.vue";
import HashtagResult from "@/components/search/HashtagResult.vue";
import PageResult from "@/components/search/PageResult.vue";
import PersonResult from "@/components/search/PersonResult.vue";
import PhotoResult from "@/components/search/PhotoResult.vue";
import SearchBar from "@/components/search/SearchBar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import {
  ALL_SECTIONS,
  type SearchState,
  filtersFor,
  filtersOf,
  mergeResults,
  queryFromState,
  resultToListing,
  stateFromQuery,
} from "@/lib/search";
import { GROUP_CATEGORIES } from "@/services/groups";
import { marketplaceService } from "@/services/marketplace";
import { postService } from "@/services/post";
import { SEARCH_TABS, type SearchResult, type SearchTab, searchService } from "@/services/search";
import type { ListingCategory, Post } from "@/types";

const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();

const state = computed<SearchState>(() => stateFromQuery(route.query));
const draft = ref(state.value.q);
const isHashtag = computed(() => /^#\S/.test(state.value.q) && ["all", "posts", "hashtags"].includes(state.value.type));

const loading = ref(false);
const loadingMore = ref(false);
const error = ref(false);
const degraded = ref(false);
const results = ref<SearchResult[]>([]);
const posts = ref<Record<string, Post>>({});
const hashtagPosts = ref<Post[]>([]);
const types = ref<string[]>([...SEARCH_TABS]);
const nextCursor = ref<string | null>(null);
const showFilters = ref(false);

const tabs = computed(() => SEARCH_TABS.filter((tab) => tab === "all" || types.value.includes(tab)));
const applies = computed(() => filtersFor(state.value.type));
// "See all" points forward: left in Arabic (RTL), right in English.
const ForwardIcon = computed(() => (locale.value === "ar" ? ArrowLeft : ArrowRight));
const TAB_ACTIVE = "border-brand-600 bg-brand-600 text-white shadow-glow";
const TAB_IDLE =
  "border-gray-200 bg-white text-gray-700 hover:border-brand-300 hover:text-brand-700 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-200 md:bg-transparent md:hover:bg-gray-100 md:dark:bg-transparent md:dark:hover:bg-gray-800";

// ---- loading -------------------------------------------------------------------

let generation = 0;

async function hydratePosts(hits: SearchResult[], current: number) {
  const ids = hits.filter((h) => h.type === "post" && !posts.value[h.id]).map((h) => h.id);
  const loaded = await Promise.all(ids.map((id) => postService.get(id).catch(() => null)));
  if (current !== generation) return;
  const next = { ...posts.value };
  for (const p of loaded) if (p) next[p.id] = p;
  posts.value = next;
}

async function load() {
  const current = ++generation;
  const s = state.value;
  results.value = [];
  posts.value = {};
  hashtagPosts.value = [];
  nextCursor.value = null;
  error.value = false;
  degraded.value = false;
  if (!s.q) {
    loading.value = false;
    return;
  }
  loading.value = true;
  try {
    if (isHashtag.value) {
      const found = await postService.byHashtag(s.q.slice(1));
      if (current === generation) hashtagPosts.value = found;
      return;
    }
    const page = await searchService.search(s.q, s.type, filtersOf(s), null, s.type === "all" ? 30 : 20);
    if (current !== generation) return;
    results.value = page.results;
    types.value = page.types;
    degraded.value = page.degraded;
    nextCursor.value = page.hasMore ? page.nextCursor : null;
    if (s.type === "all" || s.type === "posts") await hydratePosts(page.results, current);
  } catch {
    if (current === generation) error.value = true;
  } finally {
    if (current === generation) loading.value = false;
  }
}

async function loadMore() {
  if (!nextCursor.value || loadingMore.value) return;
  const current = generation;
  const s = state.value;
  loadingMore.value = true;
  try {
    const page = await searchService.search(s.q, s.type, filtersOf(s), nextCursor.value);
    if (current !== generation) return;
    results.value = mergeResults(results.value, page.results);
    nextCursor.value = page.hasMore ? page.nextCursor : null;
    if (s.type === "posts") await hydratePosts(page.results, current);
  } catch {
    if (current === generation) error.value = true;
  } finally {
    loadingMore.value = false;
  }
}

watch(
  () => route.fullPath,
  () => {
    if (route.name !== "search") return;
    draft.value = state.value.q;
    load();
  },
);
onMounted(load);

// ---- navigation ------------------------------------------------------------------

function update(patch: Partial<SearchState>) {
  router.replace({ name: "search", query: queryFromState({ ...state.value, ...patch }) });
}
function tabTo(tab: SearchTab) {
  return { name: "search", query: queryFromState({ ...state.value, type: tab }) };
}
function submit(value: string) {
  const q = value.trim();
  if (!q) return;
  searchService.rememberQuery(q).catch(() => undefined);
  router.push({ name: "search", query: queryFromState({ ...state.value, q }) });
}
function resetFilters() {
  router.replace({ name: "search", query: queryFromState({ q: state.value.q, type: state.value.type }) });
}

// ---- filters ---------------------------------------------------------------------

const listingCategories = ref<ListingCategory[]>([]);
watch(
  () => state.value.type,
  async (tab) => {
    if (tab === "marketplace" && !listingCategories.value.length) {
      try {
        listingCategories.value = await marketplaceService.categories();
      } catch {
        listingCategories.value = [];
      }
    }
  },
  { immediate: true },
);
const categoryOptions = computed(() => {
  if (state.value.type === "marketplace") return listingCategories.value.map((c) => ({ value: c.slug, label: c.name }));
  if (state.value.type === "groups") return GROUP_CATEGORIES.map((c) => ({ value: c, label: t(`groups.categories.${c}`) }));
  return [];
});
const DATE_PRESETS = ["any", "day", "week", "month", "year"] as const;
const locationDraft = ref(state.value.location ?? "");
const categoryDraft = ref(state.value.category ?? "");
watch(state, (s) => {
  locationDraft.value = s.location ?? "";
  categoryDraft.value = s.category ?? "";
});
const hasFilters = computed(() => {
  const s = state.value;
  return s.sort === "recent" || (s.date && s.date !== "any") || !!s.from || !!s.to || !!s.category || !!s.location;
});

// ---- rendering ---------------------------------------------------------------------

const byType = (type: string) => results.value.filter((r) => r.type === type);
const SECTION_LIMIT: Record<string, number> = { user: 4, page: 3, group: 3, post: 3, listing: 6, gathering: 3, hashtag: 6 };
const sections = computed(() =>
  ALL_SECTIONS.filter((s) => types.value.includes(s.tab))
    .map((s) => ({ ...s, items: byType(s.type).slice(0, SECTION_LIMIT[s.type]) }))
    .filter((s) => s.items.length > 0),
);
const hydrated = (items: SearchResult[]) => items.map((r) => posts.value[r.id]).filter((p): p is Post => !!p);
const isEmpty = computed(
  () =>
    !loading.value &&
    !error.value &&
    !!state.value.q &&
    (isHashtag.value ? !hashtagPosts.value.length : !results.value.length),
);
const TYPE_OF_TAB: Record<string, string> = {
  people: "user",
  posts: "post",
  photos: "post",
  pages: "page",
  groups: "group",
  marketplace: "listing",
  events: "gathering",
  hashtags: "hashtag",
};
const tabItems = computed(() => byType(TYPE_OF_TAB[state.value.type] ?? ""));
</script>

<template>
  <AppShell :right="false">
    <div class="flex min-w-0 flex-col gap-4 md:flex-row md:items-start">
      <!-- Filters column (start side on desktop; chips on phones) -->
      <aside class="min-w-0 md:sticky md:top-20 md:w-64 md:shrink-0 lg:w-72">
        <div class="card p-3 md:p-4">
          <h1 class="mb-3 text-xl font-bold">{{ t("search.title") }}</h1>
          <div class="sm:hidden">
            <SearchBar v-model="draft" @submit="submit" />
          </div>

          <nav :aria-label="t('search.categories')" class="mt-3 sm:mt-0">
            <ul class="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1 md:mx-0 md:flex-col md:overflow-visible md:px-0 md:pb-0">
              <li v-for="tab in tabs" :key="tab" class="shrink-0">
                <RouterLink
                  :to="tabTo(tab)"
                  replace
                  :aria-current="state.type === tab ? 'page' : undefined"
                  class="inline-flex items-center whitespace-nowrap rounded-full border px-3 py-1.5 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 md:flex md:w-full md:rounded-xl md:border-transparent md:py-2.5 md:font-semibold"
                  :class="state.type === tab ? TAB_ACTIVE : TAB_IDLE"
                  :data-testid="`search-tab-${tab}`"
                >
                  {{ t(`search.${tab}`) }}
                </RouterLink>
              </li>
            </ul>
          </nav>

          <template v-if="state.q && !isHashtag">
            <button
              type="button"
              class="btn-ghost mt-3 w-full justify-between px-2 md:hidden"
              :aria-expanded="showFilters"
              aria-controls="search-filters"
              @click="showFilters = !showFilters"
            >
              <span class="inline-flex items-center gap-2">
                <SlidersHorizontal class="h-4 w-4" aria-hidden="true" />
                {{ t("search.showFilters") }}
              </span>
              <span v-if="hasFilters" class="badge">•</span>
            </button>

            <form
              id="search-filters"
              class="mt-3 space-y-3 border-t border-gray-200 pt-3 dark:border-gray-800 md:block"
              :class="showFilters ? 'block' : 'hidden'"
              @submit.prevent="update({ location: locationDraft.trim() || undefined, category: categoryDraft.trim() || undefined })"
            >
              <h2 class="text-sm font-bold text-gray-700 dark:text-gray-200">{{ t("search.filters") }}</h2>

              <div>
                <label class="label" for="search-sort">{{ t("search.sort") }}</label>
                <select
                  id="search-sort"
                  class="input"
                  :value="state.sort"
                  @change="update({ sort: ($event.target as HTMLSelectElement).value as SearchState['sort'] })"
                >
                  <option value="relevance">{{ t("search.sortRelevance") }}</option>
                  <option value="recent">{{ t("search.sortRecent") }}</option>
                </select>
              </div>

              <template v-if="applies.date">
                <div>
                  <label class="label" for="search-date">{{ t("search.date") }}</label>
                  <select
                    id="search-date"
                    class="input"
                    :value="state.date"
                    @change="update({ date: ($event.target as HTMLSelectElement).value as SearchState['date'] })"
                  >
                    <option v-for="d in DATE_PRESETS" :key="d" :value="d">{{ t(`search.dates.${d}`) }}</option>
                  </select>
                </div>
                <div class="grid grid-cols-2 gap-2">
                  <div class="min-w-0">
                    <label class="label" for="search-from">{{ t("search.from") }}</label>
                    <input
                      id="search-from"
                      type="date"
                      class="input px-2"
                      dir="ltr"
                      :value="state.from ?? ''"
                      @change="update({ from: ($event.target as HTMLInputElement).value || undefined })"
                    />
                  </div>
                  <div class="min-w-0">
                    <label class="label" for="search-to">{{ t("search.to") }}</label>
                    <input
                      id="search-to"
                      type="date"
                      class="input px-2"
                      dir="ltr"
                      :value="state.to ?? ''"
                      @change="update({ to: ($event.target as HTMLInputElement).value || undefined })"
                    />
                  </div>
                </div>
              </template>

              <div v-if="applies.category">
                <label class="label" for="search-category">{{ t("search.category") }}</label>
                <select
                  v-if="categoryOptions.length"
                  id="search-category"
                  class="input"
                  :value="state.category ?? ''"
                  @change="update({ category: ($event.target as HTMLSelectElement).value || undefined })"
                >
                  <option value="">{{ t("search.anyCategory") }}</option>
                  <option v-for="c in categoryOptions" :key="c.value" :value="c.value">{{ c.label }}</option>
                </select>
                <input v-else id="search-category" v-model="categoryDraft" class="input" dir="auto" @change="update({ category: categoryDraft.trim() || undefined })" />
              </div>

              <div v-if="applies.location">
                <label class="label" for="search-location">{{ t("search.location") }}</label>
                <input
                  id="search-location"
                  v-model="locationDraft"
                  class="input"
                  dir="auto"
                  :placeholder="t('search.locationPlaceholder')"
                  @change="update({ location: locationDraft.trim() || undefined })"
                />
              </div>

              <button v-if="hasFilters" type="button" class="btn-ghost w-full" @click="resetFilters">{{ t("search.reset") }}</button>
            </form>
          </template>
        </div>
      </aside>

      <!-- Results -->
      <section class="min-w-0 flex-1" :aria-busy="loading">
        <h2 v-if="state.q" class="mb-3 truncate text-lg font-bold" dir="auto">{{ t("search.resultsFor", { q: state.q }) }}</h2>
        <p v-if="degraded" class="mb-3 flex items-center gap-2 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          <Info class="h-4 w-4 shrink-0" aria-hidden="true" />
          {{ t("search.degraded") }}
        </p>

        <EmptyState v-if="!state.q">{{ t("search.start") }}</EmptyState>
        <LoadingSkeleton v-else-if="loading" :rows="3" />
        <ErrorState v-else-if="error && !results.length" @retry="load" />
        <EmptyState v-else-if="isEmpty">{{ t("search.noResults", { q: state.q }) }}</EmptyState>

        <!-- #tag: posts carrying the hashtag (existing behaviour) -->
        <div v-else-if="isHashtag" class="space-y-4">
          <PostCard v-for="post in hashtagPosts" :key="post.id" :post="post" />
        </div>

        <!-- All: one section per type -->
        <div v-else-if="state.type === 'all'" class="space-y-6">
          <section v-for="section in sections" :key="section.type" :aria-labelledby="`search-section-${section.type}`">
            <div class="mb-2 flex items-center justify-between">
              <h3 :id="`search-section-${section.type}`" class="section-title">{{ t(`search.${section.tab}`) }}</h3>
              <RouterLink :to="tabTo(section.tab)" class="inline-flex items-center gap-1 rounded text-sm font-semibold text-brand-600 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:text-brand-300">
                {{ t("search.seeAll") }}
                <component :is="ForwardIcon" class="h-4 w-4" aria-hidden="true" />
              </RouterLink>
            </div>
            <div v-if="section.type === 'listing'" class="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <MarketplaceCard v-for="r in section.items" :key="r.id" :listing="resultToListing(r)" />
            </div>
            <div v-else-if="section.type === 'post'" class="space-y-4">
              <PostCard v-for="post in hydrated(section.items)" :key="post.id" :post="post" />
            </div>
            <div v-else-if="section.type === 'hashtag'" class="grid gap-2 sm:grid-cols-2">
              <HashtagResult v-for="r in section.items" :key="r.id" :result="r" />
            </div>
            <div v-else class="space-y-2">
              <template v-for="r in section.items" :key="r.id">
                <PersonResult v-if="r.type === 'user'" :result="r" />
                <PageResult v-else-if="r.type === 'page'" :result="r" />
                <GroupResult v-else-if="r.type === 'group'" :result="r" />
                <EventResult v-else-if="r.type === 'gathering'" :result="r" />
              </template>
            </div>
          </section>
        </div>

        <!-- One type -->
        <template v-else>
          <div v-if="state.type === 'photos'" class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            <PhotoResult v-for="r in tabItems" :key="r.id" :result="r" />
          </div>
          <div v-else-if="state.type === 'marketplace'" class="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <MarketplaceCard v-for="r in tabItems" :key="r.id" :listing="resultToListing(r)" />
          </div>
          <div v-else-if="state.type === 'posts'" class="space-y-4">
            <PostCard v-for="post in hydrated(tabItems)" :key="post.id" :post="post" />
          </div>
          <div v-else-if="state.type === 'hashtags'" class="grid gap-2 sm:grid-cols-2">
            <HashtagResult v-for="r in tabItems" :key="r.id" :result="r" />
          </div>
          <div v-else class="space-y-2">
            <template v-for="r in tabItems" :key="r.id">
              <PersonResult v-if="r.type === 'user'" :result="r" />
              <PageResult v-else-if="r.type === 'page'" :result="r" />
              <GroupResult v-else-if="r.type === 'group'" :result="r" />
              <EventResult v-else-if="r.type === 'gathering'" :result="r" />
            </template>
          </div>

          <div v-if="nextCursor" class="mt-4 flex justify-center">
            <button type="button" class="btn-outline" :disabled="loadingMore" data-testid="search-load-more" @click="loadMore">
              {{ t("search.loadMore") }}
            </button>
          </div>
          <ErrorState v-if="error && results.length" @retry="loadMore" />
        </template>
      </section>
    </div>
  </AppShell>
</template>
