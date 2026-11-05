<script setup lang="ts">
import { Hash } from "lucide-vue-next";
import { onMounted, ref, useId, watch } from "vue";
import { useI18n } from "vue-i18n";

import { tagRoute } from "@/lib/searchRoutes";
import { searchService, type TrendingTag } from "@/services/search";

// "Trending on Tara" with a Last 24 h / Last 7 days toggle (GET /search/trending/).
// `compact` (the right rail) hides itself when nothing is trending.
// Counts (4b.20-B3): the server sends only `posts_floor` (20, 50, 100, 500, 1K,
// 5K, 10K) or null; null shows no count line, and the window is always named.
const props = withDefaults(defineProps<{ compact?: boolean; limit?: number }>(), { compact: false, limit: 10 });

const { t } = useI18n();
const headingId = useId();
type Window = "day" | "week";
const win = ref<Window>("week");
const tags = ref<TrendingTag[]>([]);
const loading = ref(true);
let generation = 0;

// 1000 -> "1K", 5000 -> "5K", 10000 -> "10K"; the floors below 1000 as they are.
function floorText(n: number): string {
  return n >= 1000 && n % 1000 === 0 ? `${n / 1000}K` : String(n);
}

function countLine(tag: TrendingTag): string | null {
  if (tag.posts_floor == null) return null;
  const key = tag.window === "day" ? "postsFeed.search.postsFloorDay" : "postsFeed.search.postsFloorWeek";
  return t(key, { n: floorText(tag.posts_floor) });
}

async function load() {
  const run = ++generation;
  loading.value = true;
  try {
    const rows = await searchService.trending(win.value);
    if (run === generation) tags.value = rows.slice(0, props.limit);
  } catch {
    if (run === generation) tags.value = [];
  } finally {
    if (run === generation) loading.value = false;
  }
}
watch(win, load);
onMounted(load);
</script>

<template>
  <section
    v-if="!compact || tags.length || win === 'day'"
    :aria-labelledby="headingId"
    :data-testid="compact ? 'rail-trending' : 'search-trending'"
  >
    <div class="flex items-center justify-between gap-2" :class="compact ? 'px-2 pb-2' : 'mb-2'">
      <h2 :id="headingId" :class="compact ? 'text-[15px] font-semibold text-gray-600 dark:text-gray-400' : 'section-title'">
        {{ compact ? t("postsFeed.search.trendingCard") : t("postsFeed.search.trendingTitle") }}
      </h2>
      <div class="flex gap-1 rounded-lg bg-gray-100 p-0.5 text-xs dark:bg-gray-800" role="group" :aria-label="t('postsFeed.search.trendingWindow')">
        <button
          v-for="w in (['day', 'week'] as Window[])"
          :key="w"
          type="button"
          class="rounded-md px-2 py-1 font-semibold transition"
          :class="win === w ? 'bg-white text-brand-700 shadow-sm dark:bg-gray-900 dark:text-brand-200' : 'text-gray-600 dark:text-gray-300'"
          :aria-pressed="win === w"
          @click="win = w"
        >
          {{ w === "day" ? t("postsFeed.search.today") : t("postsFeed.search.week") }}
        </button>
      </div>
    </div>
    <p v-if="!loading && !tags.length" class="px-2 text-sm text-gray-600 dark:text-gray-400">{{ t("postsFeed.search.noTrending") }}</p>
    <ul v-else class="space-y-0.5">
      <li v-for="tag in tags" :key="tag.tag">
        <RouterLink
          :to="tagRoute(tag.tag)"
          class="flex items-center gap-3 rounded-xl px-2 py-2 transition hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:hover:bg-gray-800"
        >
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-600 dark:bg-brand-950/60 dark:text-brand-300">
            <Hash class="h-4 w-4" aria-hidden="true" />
          </span>
          <!-- The row follows the page direction; only the tag text is isolated, so an Arabic tag in an
               English layout (or the reverse) doesn't pull its line to the other side. -->
          <span class="min-w-0 flex-1 text-start">
            <span class="block truncate text-start text-sm font-semibold" data-testid="trending-tag">#<bdi>{{ tag.tag }}</bdi></span>
            <span v-if="countLine(tag)" class="block text-start text-xs text-gray-600 dark:text-gray-400" data-testid="trending-count">{{ countLine(tag) }}</span>
          </span>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
