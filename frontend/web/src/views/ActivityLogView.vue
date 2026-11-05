<script setup lang="ts">
// The activity log (/settings/activity-log): what I did, newest first, by day.
// Posts, comments, reactions, saves and poll votes come from the post service
// (GET /posts/activity/, my own rows only); searches from the search service's
// recent searches, which I can remove one by one or clear. Only the signed-in
// account can read either: neither endpoint takes an account id.
import { ArrowLeft, Bookmark, FileText, History, MessageCircle, Search, SmilePlus, ThumbsUp, Trash2, Vote } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import AppShell from "@/components/layout/AppShell.vue";
import SettingsNav from "@/components/settings/SettingsNav.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { groupByDay, rowLink, sentenceKey } from "@/lib/activityLog";
import { reactionByKey } from "@/lib/reactions";
import { entityRoute } from "@/lib/searchRoutes";
import { type ActivityKind, type ActivityRow, activityService } from "@/services/activity";
import { type RecentSearch, searchService } from "@/services/search";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { usePageDirectoryStore } from "@/stores/pageDirectory";
import { useToastStore } from "@/stores/toasts";

defineOptions({ name: "ActivityLogView" });

type Filter = "all" | ActivityKind | "searches";
const FILTERS: Filter[] = ["all", "post", "comment", "reaction", "comment_reaction", "save", "vote", "searches"];
const ICON = {
  all: History,
  post: FileText,
  comment: MessageCircle,
  reaction: ThumbsUp,
  comment_reaction: SmilePlus,
  save: Bookmark,
  vote: Vote,
  searches: Search,
} as const;

const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const directory = useDirectoryStore();
const pages = usePageDirectoryStore();
const toasts = useToastStore();

const filter = computed<Filter>(() => (FILTERS.includes(route.query.type as Filter) ? (route.query.type as Filter) : "all"));
const rows = ref<ActivityRow[]>([]);
const searches = ref<RecentSearch[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(true);
const more = ref(false);
const failed = ref(false);
const busy = ref<string | null>(null);

let seq = 0;
async function load(reset = true) {
  const mine = ++seq;
  if (reset) loading.value = true;
  else more.value = true;
  failed.value = false;
  try {
    if (filter.value === "searches") {
      const list = await searchService.recent();
      if (mine !== seq) return;
      searches.value = list;
      cursor.value = null;
    } else {
      const kind = filter.value === "all" ? null : filter.value;
      const page = await activityService.list(kind, reset ? null : cursor.value);
      if (mine !== seq) return;
      rows.value = reset ? page.data : rows.value.concat(page.data);
      cursor.value = page.page.has_more ? page.page.next_cursor : null;
    }
  } catch {
    if (mine === seq) failed.value = true;
  } finally {
    if (mine === seq) {
      loading.value = false;
      more.value = false;
    }
  }
}
watch(filter, () => load());
onMounted(() => load());

function choose(f: Filter) {
  if (f !== filter.value) void router.replace({ query: { ...route.query, type: f === "all" ? undefined : f } });
}

// ---- rows ---------------------------------------------------------------------------------
const me = computed(() => auth.account?.id ?? "");
const days = computed(() => groupByDay(rows.value));
const authorName = (r: ActivityRow) => {
  const target = r.target;
  if (!target) return "";
  return target.author_type === "page" ? pages.label(target.author_id) : directory.label(target.author_id);
};
const reactionLabel = (key: string | null) => {
  const def = reactionByKey(key);
  return def ? t(def.labelKey) : "";
};
const rowIcon = (r: ActivityRow) => (r.kind === "reaction" || r.kind === "comment_reaction" ? reactionByKey(r.reaction)?.emoji : null);
const quote = (r: ActivityRow) => (r.kind === "comment_reaction" || r.kind === "vote" || r.kind === "comment" || r.kind === "post" ? r.text : "") || r.target?.excerpt || "";
const fmtDay = (ymd: string) => new Intl.DateTimeFormat(locale.value, { dateStyle: "full" }).format(new Date(`${ymd}T12:00:00`));
const fmtDate = (iso: string) => new Intl.DateTimeFormat(locale.value, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
const fmtTime = (iso: string) => new Intl.DateTimeFormat(locale.value, { timeStyle: "short" }).format(new Date(iso));

// ---- searches -----------------------------------------------------------------------------
const searchTo = (s: RecentSearch) =>
  s.kind === "entity" && s.doc_type && s.doc_id
    ? entityRoute(s.doc_type, s.doc_id, s.title, s.handle)
    : { name: "search", query: { q: s.query } };

async function forget(s: RecentSearch) {
  busy.value = s.id;
  try {
    await searchService.forget(s.id);
    searches.value = searches.value.filter((x) => x.id !== s.id);
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = null;
  }
}
async function clearAll() {
  busy.value = "all";
  try {
    await searchService.clearRecent();
    searches.value = [];
    toasts.success(t("polish.activity.searchesCleared"));
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = null;
  }
}
</script>

<template>
  <AppShell :left="false" :right="false">
    <div class="mx-auto flex w-full max-w-[1180px] gap-6">
      <aside
        class="sticky top-20 hidden max-h-[calc(100vh-6rem)] w-[340px] shrink-0 self-start overflow-y-auto rounded-2xl bg-white p-2 shadow-sm ring-1 ring-gray-200/70 lg:block xl:w-[360px] dark:bg-gray-900 dark:ring-gray-800"
      >
        <SettingsNav :active="null" activity-active />
      </aside>

      <div class="min-w-0 flex-1">
        <div class="mx-auto w-full max-w-[680px]" data-testid="activity-log">
          <div class="mb-4 flex items-center gap-2">
            <RouterLink to="/settings" class="icon-btn h-9 w-9 lg:hidden" :aria-label="t('settingsCenter.back')">
              <ArrowLeft class="h-5 w-5 rtl:rotate-180" aria-hidden="true" />
            </RouterLink>
            <History class="hidden h-6 w-6 text-brand-600 lg:block dark:text-brand-300" aria-hidden="true" />
            <div>
              <h1 class="text-xl font-bold">{{ t("polish.activity.title") }}</h1>
              <p class="text-sm text-gray-600 dark:text-gray-400">{{ t("polish.activity.lead") }}</p>
            </div>
          </div>

          <div class="mb-4 flex flex-wrap gap-2" role="group" :aria-label="t('polish.activity.filterLabel')">
            <button
              v-for="f in FILTERS"
              :key="f"
              type="button"
              class="inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-semibold transition"
              :class="filter === f ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-800 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700'"
              :aria-pressed="filter === f"
              :data-testid="`activity-filter-${f}`"
              @click="choose(f)"
            >
              <component :is="ICON[f]" class="h-4 w-4" aria-hidden="true" />{{ t(`polish.activity.filters.${f}`) }}
            </button>
          </div>

          <LoadingSkeleton v-if="loading" :rows="3" />
          <ErrorState v-else-if="failed" @retry="load()" />

          <!-- Searches (search service) -->
          <section v-else-if="filter === 'searches'" class="card p-2" data-testid="activity-searches">
            <div class="flex items-center justify-between gap-2 px-2 py-1">
              <h2 class="font-semibold">{{ t("polish.activity.filters.searches") }}</h2>
              <button v-if="searches.length" type="button" class="btn-ghost px-3 py-1.5 text-sm" :disabled="busy === 'all'" data-testid="activity-searches-clear" @click="clearAll">
                {{ t("polish.activity.clearSearches") }}
              </button>
            </div>
            <EmptyState v-if="!searches.length">{{ t("polish.activity.noSearches") }}</EmptyState>
            <ul v-else class="divide-y divide-gray-100 dark:divide-gray-800">
              <li v-for="s in searches" :key="s.id" class="flex items-center gap-3 px-2 py-2" data-testid="activity-search-row">
                <Search class="h-5 w-5 shrink-0 text-gray-500 dark:text-gray-400" aria-hidden="true" />
                <RouterLink :to="searchTo(s)" class="min-w-0 flex-1 hover:underline">
                  <span class="block truncate text-start text-sm font-semibold"><bdi>{{ s.kind === "entity" ? s.title : s.query }}</bdi></span>
                  <span class="block text-xs text-gray-600 dark:text-gray-400">{{ t("polish.activity.searchedAt", { time: fmtDate(s.created_at) }) }}</span>
                </RouterLink>
                <button
                  type="button"
                  class="icon-btn h-9 w-9 hover:!text-red-600"
                  :disabled="busy === s.id"
                  :aria-label="t('polish.activity.removeSearch', { query: s.kind === 'entity' ? s.title : s.query })"
                  data-testid="activity-search-remove"
                  @click="forget(s)"
                >
                  <Trash2 class="h-4 w-4" aria-hidden="true" />
                </button>
              </li>
            </ul>
          </section>

          <!-- Everything else (post service) -->
          <template v-else>
            <EmptyState v-if="!rows.length" class="card">{{ t("polish.activity.empty") }}</EmptyState>
            <section v-for="d in days" :key="d.day" class="card mb-4 p-2" :aria-label="fmtDay(d.day)">
              <h2 class="px-2 py-1 text-sm font-bold text-gray-700 dark:text-gray-300">{{ fmtDay(d.day) }}</h2>
              <ul class="divide-y divide-gray-100 dark:divide-gray-800">
                <li v-for="r in d.rows" :key="`${r.kind}-${r.id}`" class="flex items-start gap-3 px-2 py-2.5" data-testid="activity-row" :data-kind="r.kind">
                  <span class="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200" aria-hidden="true">
                    <span v-if="rowIcon(r)" class="text-lg leading-none">{{ rowIcon(r) }}</span>
                    <component :is="ICON[r.kind]" v-else class="h-5 w-5" />
                  </span>
                  <div class="min-w-0 flex-1">
                    <p class="text-start text-sm" data-testid="activity-sentence">
                      <i18n-t :keypath="`polish.activity.rows.${sentenceKey(r, me)}`" scope="global" tag="span">
                        <template #name><bdi class="font-semibold">{{ authorName(r) }}</bdi></template>
                        <template #reaction>{{ reactionLabel(r.reaction) }}</template>
                      </i18n-t>
                    </p>
                    <p v-if="quote(r)" class="mt-0.5 line-clamp-2 text-start text-sm text-gray-600 dark:text-gray-400"><bdi>“{{ quote(r) }}”</bdi></p>
                    <p class="mt-0.5 text-xs text-gray-600 dark:text-gray-400">{{ fmtTime(r.created_at) }}</p>
                  </div>
                  <RouterLink
                    v-if="rowLink(r)"
                    :to="rowLink(r)!"
                    class="btn-ghost shrink-0 px-3 py-1.5 text-sm"
                    :aria-label="t('polish.activity.viewLabel')"
                    data-testid="activity-view"
                  >
                    {{ t("polish.activity.view") }}
                  </RouterLink>
                </li>
              </ul>
            </section>
            <div v-if="cursor" class="flex justify-center">
              <button type="button" class="btn-outline" :disabled="more" data-testid="activity-more" @click="load(false)">{{ t("polish.activity.loadMore") }}</button>
            </div>
          </template>
        </div>
      </div>
    </div>
  </AppShell>
</template>
