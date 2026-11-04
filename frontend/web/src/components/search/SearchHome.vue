<script setup lang="ts">
import { Clock, X } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import TrendingList from "@/components/search/TrendingList.vue";
import { entityRoute } from "@/lib/searchRoutes";
import { type RecentSearch, searchService } from "@/services/search";
import { useToastStore } from "@/stores/toasts";

// The search page before a query (also the phone's search screen): recent
// searches (open, remove one, clear all) and what's trending.
const { t } = useI18n();
const router = useRouter();
const toasts = useToastStore();

const recent = ref<RecentSearch[]>([]);
const loaded = ref(false);

async function load() {
  try {
    recent.value = await searchService.recent();
  } catch {
    recent.value = [];
  } finally {
    loaded.value = true;
  }
}

const title = (r: RecentSearch) => r.title || r.query;

function open(r: RecentSearch) {
  if (r.kind === "query" || !r.doc_type || !r.doc_id) {
    void router.push({ name: "search", query: { q: r.query || r.title } });
    return;
  }
  void router.push(entityRoute(r.doc_type, r.doc_id, r.title, r.handle));
}

async function remove(r: RecentSearch) {
  recent.value = recent.value.filter((x) => x.id !== r.id);
  try {
    await searchService.forget(r.id);
  } catch (e) {
    toasts.error(e);
    void load();
  }
}
async function clearAll() {
  const before = recent.value;
  recent.value = [];
  try {
    await searchService.clearRecent();
  } catch (e) {
    recent.value = before;
    toasts.error(e);
  }
}

onMounted(load);
</script>

<template>
  <div class="space-y-4" data-testid="search-home">
    <section class="card p-3 sm:p-4" aria-labelledby="search-recent-title" data-testid="search-recent">
      <div class="mb-2 flex items-center justify-between">
        <h2 id="search-recent-title" class="section-title">{{ t("postsFeed.search.recent") }}</h2>
        <button
          v-if="recent.length"
          type="button"
          class="rounded text-sm font-semibold text-brand-600 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:text-brand-300"
          data-testid="search-recent-clear"
          @click="clearAll"
        >
          {{ t("postsFeed.search.edit") }}
        </button>
      </div>
      <p v-if="loaded && !recent.length" class="text-sm text-gray-500 dark:text-gray-400">{{ t("postsFeed.search.noRecent") }}</p>
      <ul v-else class="space-y-0.5">
        <li v-for="r in recent" :key="r.id" class="flex items-center gap-1" data-testid="search-recent-row">
          <button
            type="button"
            class="flex min-w-0 flex-1 items-center gap-3 rounded-xl px-2 py-2 text-start transition hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:hover:bg-gray-800"
            @click="open(r)"
          >
            <UserAvatar v-if="r.kind === 'entity' && r.doc_type !== 'hashtag'" :name="title(r)" :media-id="r.avatar_media_id" :size="36" />
            <span v-else class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-300">
              <Clock class="h-4 w-4" aria-hidden="true" />
            </span>
            <span class="min-w-0 flex-1 truncate text-sm font-medium text-start"><bdi>{{ title(r) }}</bdi></span>
          </button>
          <button
            type="button"
            class="rounded-full p-2 text-gray-400 transition hover:bg-gray-200 hover:text-gray-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:hover:bg-gray-700 dark:hover:text-gray-100"
            :aria-label="t('search.removeRecent', { name: title(r) })"
            @click="remove(r)"
          >
            <X class="h-4 w-4" aria-hidden="true" />
          </button>
        </li>
      </ul>
    </section>

    <div class="card p-3 sm:p-4">
      <TrendingList />
    </div>
  </div>
</template>
