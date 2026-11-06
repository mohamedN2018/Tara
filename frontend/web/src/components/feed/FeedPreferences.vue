<script setup lang="ts">
import { Clock, SlidersHorizontal, Star } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { FEED_MODES, feedService, type Snooze } from "@/services/feed";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

// Feed preferences: how Home is sorted (links into /home?mode=…), who is
// snoozed (GET /feed/snoozes/, Unsnooze) and where favorites/mutes live.
// Self-contained so Settings can mount it as a section as well.
withDefaults(defineProps<{ showSort?: boolean }>(), { showSort: true });

const { t, locale } = useI18n();
const directory = useDirectoryStore();
const toasts = useToastStore();

const snoozes = ref<Snooze[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const failed = ref(false);
const busy = ref<string | null>(null);

async function load(initial = false) {
  if (initial) {
    loading.value = true;
    failed.value = false;
  } else {
    if (loadingMore.value || !hasMore.value) return;
    loadingMore.value = true;
  }
  try {
    const page = await feedService.snoozes(initial ? null : cursor.value);
    snoozes.value = initial ? page.data : [...snoozes.value, ...page.data];
    cursor.value = page.page.next_cursor;
    hasMore.value = !!page.page.has_more && !!page.page.next_cursor;
  } catch (e) {
    if (initial) failed.value = true;
    else toasts.error(e);
  } finally {
    loading.value = false;
    loadingMore.value = false;
  }
}

async function unsnooze(s: Snooze) {
  if (busy.value) return;
  busy.value = s.author_id;
  try {
    await feedService.unsnooze(s.author_id);
    snoozes.value = snoozes.value.filter((x) => x.author_id !== s.author_id);
    toasts.success(t("postsFeed.manage.unsnoozed", { name: directory.label(s.author_id) }));
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = null;
  }
}

function until(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(locale.value, { day: "numeric", month: "long", year: "numeric" });
  } catch {
    return iso.slice(0, 10);
  }
}

onMounted(() => load(true));
</script>

<template>
  <div class="space-y-4" data-testid="feed-preferences">
    <!-- R4 (04 WP 8.2): the full controls live in My Algorithm. -->
    <RouterLink
      to="/settings/my-algorithm"
      class="card flex items-center gap-3 p-4 transition hover:bg-gray-50 dark:hover:bg-gray-800/60"
      data-testid="my-algorithm-link"
    >
      <SlidersHorizontal class="h-6 w-6 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden="true" />
      <span class="min-w-0">
        <span class="block text-[15px] font-bold">{{ t("myAlgorithm.page.link") }}</span>
        <span class="block text-sm text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.page.linkHint") }}</span>
      </span>
    </RouterLink>
    <section v-if="showSort" class="card p-4 sm:p-5" aria-labelledby="feed-sort-title">
      <h2 id="feed-sort-title" class="text-[15px] font-bold">{{ t("postsFeed.manage.sortTitle") }}</h2>
      <ul class="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <li v-for="m in FEED_MODES" :key="m">
          <RouterLink
            :to="{ path: '/home', query: { mode: m } }"
            class="block rounded-lg bg-gray-100 px-3 py-2 text-center text-sm font-semibold transition hover:bg-brand-50 hover:text-brand-700 dark:bg-gray-800 dark:hover:bg-brand-950/60 dark:hover:text-brand-200"
          >
            {{ t(`homeFeed.modes.${m}`) }}
          </RouterLink>
        </li>
      </ul>
    </section>

    <section class="card p-4 sm:p-5" aria-labelledby="feed-snoozed-title" data-testid="snoozed-list">
      <h2 id="feed-snoozed-title" class="flex items-center gap-2 text-[15px] font-bold">
        <Clock class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("postsFeed.manage.snoozedTitle") }}
      </h2>
      <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t("postsFeed.manage.snoozedHint") }}</p>

      <p v-if="loading" class="mt-3 text-sm text-gray-500 dark:text-gray-400" role="status">{{ t("states.loading") }}</p>
      <p v-else-if="failed" class="mt-3 text-sm text-red-600 dark:text-red-400" role="alert">
        {{ t("states.error") }}
        <button type="button" class="ms-2 font-semibold underline" @click="load(true)">{{ t("states.retry") }}</button>
      </p>
      <p v-else-if="!snoozes.length" class="mt-3 text-sm text-gray-500 dark:text-gray-400" data-testid="snoozed-empty">
        {{ t("postsFeed.manage.empty") }}
      </p>
      <ul v-else class="mt-3 divide-y divide-gray-100 dark:divide-gray-800">
        <li v-for="s in snoozes" :key="s.author_id" class="flex items-center gap-3 py-2.5" data-testid="snoozed-row">
          <RouterLink :to="{ name: 'profile-by-id', params: { id: s.author_id } }" tabindex="-1" aria-hidden="true">
            <UserAvatar :name="directory.label(s.author_id)" :media-id="directory.avatarOf(s.author_id)" :size="40" />
          </RouterLink>
          <div class="min-w-0 flex-1">
            <RouterLink :to="{ name: 'profile-by-id', params: { id: s.author_id } }" class="block truncate font-semibold hover:underline" dir="auto">
              {{ directory.label(s.author_id) }}
            </RouterLink>
            <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("postsFeed.manage.until", { date: until(s.until) }) }}</p>
          </div>
          <button type="button" class="btn-ghost shrink-0" :disabled="busy === s.author_id" @click="unsnooze(s)">
            {{ t("postsFeed.manage.unsnooze") }}
          </button>
        </li>
      </ul>
      <button v-if="hasMore" type="button" class="btn-ghost mt-2 w-full justify-center" :disabled="loadingMore" @click="load(false)">
        {{ t("postsFeed.manage.loadMore") }}
      </button>
    </section>

    <section class="card p-4 sm:p-5" aria-labelledby="feed-people-title">
      <h2 id="feed-people-title" class="flex items-center gap-2 text-[15px] font-bold">
        <Star class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("postsFeed.manage.peopleTitle") }}
      </h2>
      <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t("postsFeed.manage.peopleHint") }}</p>
      <RouterLink to="/connections" class="btn-ghost mt-2 inline-flex">{{ t("postsFeed.manage.peopleLink") }}</RouterLink>
    </section>
  </div>
</template>
