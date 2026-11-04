<script setup lang="ts">
import { Bookmark, Compass, EyeOff, Flag, Plus, Search, Settings, UserCheck } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import AppShell from "@/components/layout/AppShell.vue";
import PageCreateDialog from "@/components/pages/PageCreateDialog.vue";
import PageListItem from "@/components/pages/PageListItem.vue";
import PageManageCard from "@/components/pages/PageManageCard.vue";
import PagePostComposer from "@/components/pages/PagePostComposer.vue";
import PageSuggestionsRow from "@/components/pages/PageSuggestionsRow.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { canManagePage, type Page, pageService } from "@/services/pages";
import { useToastStore } from "@/stores/toasts";

// /pages — the Pages manager in the reference layout: a start column with
// "Create page" and the sections (Pages you manage, Discover, Followed pages,
// Saved pages), the managed pages as cards with their actions, and a side card
// with the team's hidden (draft) pages. Everything listed comes from the
// server; nothing is shown for a section without data.
type Tab = "manage" | "discover" | "followed" | "saved";
const TABS: { id: Tab; icon: typeof Flag; label: string }[] = [
  { id: "manage", icon: Flag, label: "pageHub.manager.manage" },
  { id: "discover", icon: Compass, label: "pageHub.manager.discover" },
  { id: "followed", icon: UserCheck, label: "pageHub.manager.followed" },
  { id: "saved", icon: Bookmark, label: "pageHub.manager.saved" },
];
// Older links: ?tab=mine (main menu "My pages") and ?tab=browse.
const ALIASES: Record<string, Tab> = { mine: "manage", browse: "discover", following: "followed" };
const toTab = (v: unknown): Tab => {
  const s = typeof v === "string" ? (ALIASES[v] ?? v) : "";
  return TABS.some((x) => x.id === s) ? (s as Tab) : "manage";
};

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const toasts = useToastStore();

const tab = computed<Tab>(() => toTab(route.query.tab));
const title = computed(() => t(TABS.find((x) => x.id === tab.value)?.label ?? "pageHub.manager.title"));
function pick(next: Tab) {
  router.replace({ query: { ...route.query, tab: next === "manage" ? undefined : next } });
}

const pages = ref<Page[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);
const query = ref("");
let generation = 0;

// "Pages you manage": published pages in the main column, hidden ones aside.
const managed = computed(() => pages.value.filter((p) => p.status === "published"));
const hidden = computed(() => (tab.value === "manage" ? pages.value.filter((p) => p.status !== "published") : []));

async function fetchPage(more: boolean): Promise<{ data: Page[]; next: string | null }> {
  const c = more ? cursor.value : null;
  if (tab.value === "manage") {
    const r = await pageService.list({ mine: true, cursor: c ?? undefined });
    return { data: r.data, next: r.page.next_cursor };
  }
  if (tab.value === "discover") {
    const r = await pageService.list({ q: query.value.trim(), cursor: c ?? undefined });
    return { data: r.data, next: r.page.next_cursor };
  }
  if (tab.value === "saved") {
    const r = await pageService.savedPage(c);
    return { data: r.pages, next: r.nextCursor };
  }
  return { data: await pageService.byIds(await pageService.followedIds()), next: null };
}

async function load() {
  const run = ++generation;
  loading.value = true;
  error.value = false;
  try {
    const r = await fetchPage(false);
    if (run !== generation) return;
    pages.value = r.data;
    cursor.value = r.next;
  } catch {
    if (run === generation) error.value = true;
  } finally {
    if (run === generation) loading.value = false;
  }
}

async function loadMore() {
  if (!cursor.value || loadingMore.value) return;
  loadingMore.value = true;
  const run = generation;
  try {
    const r = await fetchPage(true);
    if (run !== generation) return;
    pages.value = [...pages.value, ...r.data];
    cursor.value = r.next;
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

function followChanged(page: Page, following: boolean) {
  pages.value = pages.value.map((p) =>
    p.id === page.id
      ? { ...p, viewer_following: following, followers_count: p.followers_count === null ? null : Math.max(0, p.followers_count + (following ? 1 : -1)) }
      : p,
  );
}

const publishing = ref<string | null>(null);
async function publish(page: Page) {
  if (publishing.value) return;
  publishing.value = page.id;
  try {
    const updated = await pageService.update(page.id, { status: "published" });
    pages.value = pages.value.map((p) => (p.id === page.id ? { ...p, ...updated } : p));
    toasts.success(t("pageHub.manager.published", { name: page.name }));
  } catch (e) {
    toasts.error(e);
  } finally {
    publishing.value = null;
  }
}

const creating = ref(false);
const composeFor = ref<Page | null>(null);
// The main menu's "Create > Page" lands here as ?create=1: open the dialog once.
watch(
  () => route.query.create,
  (value) => {
    if (value !== "1") return;
    creating.value = true;
    router.replace({ query: { ...route.query, create: undefined } });
  },
  { immediate: true },
);

let searchTimer: number | undefined;
watch(query, () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(load, 300);
});
watch(tab, () => {
  query.value = "";
  load();
}, { immediate: true });
</script>

<template>
  <AppShell :left="false" :right="false">
    <div class="-mx-2 -mt-4 grid min-h-[calc(100vh-4rem)] grid-cols-[minmax(0,1fr)] sm:-mx-4 lg:grid-cols-[22rem_minmax(0,1fr)] xl:-mx-6">
      <!-- Start column: the manager's navigation -->
      <aside
        class="border-gray-200 bg-white px-3 pb-3 pt-4 dark:border-gray-800 dark:bg-gray-900 lg:sticky lg:top-16 lg:h-[calc(100vh-4rem)] lg:overflow-y-auto lg:border-e"
        :aria-label="t('pageHub.manager.nav')"
      >
        <div class="flex items-center justify-between px-2">
          <h1 class="text-2xl font-extrabold">{{ t("pageHub.manager.title") }}</h1>
          <RouterLink to="/settings" class="icon-btn bg-gray-100 dark:bg-gray-800" :aria-label="t('nav.settings')" :title="t('nav.settings')">
            <Settings class="h-5 w-5" aria-hidden="true" />
          </RouterLink>
        </div>
        <button type="button" class="btn-soft mt-3 w-full bg-brand-50 text-brand-700 dark:bg-brand-950/60 dark:text-brand-200" data-testid="pages-create" @click="creating = true">
          <Plus class="h-4 w-4" aria-hidden="true" /> {{ t("pages.create") }}
        </button>
        <hr class="my-3 border-gray-200 dark:border-gray-800" />
        <nav class="flex gap-1 overflow-x-auto lg:flex-col" role="tablist" :aria-label="t('pageHub.manager.nav')">
          <button
            v-for="x in TABS"
            :id="`pages-tab-${x.id}`"
            :key="x.id"
            type="button"
            role="tab"
            :aria-selected="tab === x.id"
            aria-controls="pages-panel"
            class="nav-item shrink-0 whitespace-nowrap"
            :class="tab === x.id ? 'nav-item-active' : ''"
            :data-testid="`pages-tab-${x.id}`"
            @click="pick(x.id)"
          >
            <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gray-100 dark:bg-gray-800" aria-hidden="true">
              <component :is="x.icon" class="h-5 w-5" />
            </span>
            {{ t(x.label) }}
          </button>
        </nav>
      </aside>

      <!-- Panel -->
      <section
        id="pages-panel"
        role="tabpanel"
        :aria-labelledby="`pages-tab-${tab}`"
        class="min-w-0 px-2 py-4 sm:px-4 xl:px-6"
      >
        <div class="mx-auto grid w-full max-w-[1180px] gap-5" :class="tab === 'manage' && hidden.length ? 'xl:grid-cols-[minmax(0,1fr)_24rem]' : ''">
          <div class="min-w-0 space-y-4">
            <h2 class="text-xl font-bold" data-testid="pages-panel-title">{{ title }}</h2>

            <label v-if="tab === 'discover'" class="relative block">
              <span class="sr-only">{{ t("pages.search") }}</span>
              <Search class="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" aria-hidden="true" />
              <input v-model="query" type="search" class="input ps-9" dir="auto" maxlength="100" :placeholder="t('pages.search')" />
            </label>

            <PageSuggestionsRow v-if="tab === 'discover' && !query.trim()" />

            <LoadingSkeleton v-if="loading" :rows="3" />
            <ErrorState v-else-if="error" @retry="load" />

            <template v-else-if="tab === 'manage'">
              <EmptyState v-if="!managed.length && !hidden.length">
                {{ t("pageHub.manager.noneManaged") }}
                <template #action>
                  <button type="button" class="btn-primary" @click="creating = true"><Plus class="h-4 w-4" aria-hidden="true" /> {{ t("pages.create") }}</button>
                </template>
              </EmptyState>
              <div v-else class="max-w-[46rem] space-y-4" data-testid="pages-managed">
                <PageManageCard v-for="p in managed" :key="p.id" :page="p" @compose="composeFor = $event" />
              </div>
            </template>

            <template v-else>
              <EmptyState v-if="!pages.length">
                {{ tab === "followed" ? t("pageHub.manager.noneFollowed") : tab === "saved" ? t("pageHub.manager.noneSaved") : t("pageHub.manager.noneFound") }}
                <template v-if="tab !== 'discover'" #action>
                  <button type="button" class="btn-soft" @click="pick('discover')">{{ t("pageHub.manager.discover") }}</button>
                </template>
              </EmptyState>
              <div v-else class="grid gap-3 md:grid-cols-2" :data-testid="`pages-list-${tab}`">
                <PageListItem v-for="p in pages" :key="p.id" :page="p" @follow-changed="followChanged" />
              </div>
            </template>

            <button v-if="!loading && cursor" type="button" class="btn-ghost mx-auto block" :disabled="loadingMore" @click="loadMore">
              {{ loadingMore ? t("states.loading") : t("states.loadMore") }}
            </button>
          </div>

          <!-- Side card: hidden pages (the reference's deactivated pages) -->
          <aside v-if="tab === 'manage' && hidden.length" class="card h-fit space-y-3 p-4 xl:sticky xl:top-20" aria-labelledby="pages-hidden-title" data-testid="pages-hidden">
            <div>
              <h2 id="pages-hidden-title" class="flex items-center gap-2 text-lg font-bold">
                <EyeOff class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("pageHub.manager.drafts") }}
              </h2>
              <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t("pageHub.manager.draftsHint") }}</p>
            </div>
            <ul class="space-y-2">
              <li v-for="p in hidden" :key="p.id" class="flex items-center gap-3">
                <UserAvatar :name="p.name" :media-id="p.avatar_media_id" :size="44" />
                <RouterLink :to="{ name: 'page', params: { handle: p.handle } }" class="min-w-0 flex-1 truncate text-sm font-semibold hover:underline"><bdi>{{ p.name }}</bdi></RouterLink>
                <button
                  v-if="canManagePage(p) && p.status === 'draft'"
                  type="button"
                  class="btn-soft px-3 py-1.5 text-sm"
                  :disabled="publishing === p.id"
                  :aria-label="`${t('pageHub.manager.publish')}: ${p.name}`"
                  @click="publish(p)"
                >
                  {{ t("pageHub.manager.publish") }}
                </button>
                <span v-else class="text-xs text-gray-500 dark:text-gray-400">{{ t(`pages.status.${p.status}`) }}</span>
              </li>
            </ul>
          </aside>
        </div>
      </section>
    </div>

    <PageCreateDialog v-if="creating" @close="creating = false" />
    <PagePostComposer v-if="composeFor" :page="composeFor" @close="composeFor = null" />
  </AppShell>
</template>
