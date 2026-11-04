<script setup lang="ts">
import { Compass, Mail, Newspaper, Plus, Search, Send, Settings2, ShieldCheck, UsersRound } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import GroupCard from "@/components/groups/GroupCard.vue";
import JoinButton from "@/components/groups/JoinButton.vue";
import AppShell from "@/components/layout/AppShell.vue";
import PostCard from "@/components/post/PostCard.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import {
  GROUP_CATEGORIES,
  type Group,
  groupPath,
  type GroupScope,
  groupsService,
  isStaff,
  myGroupsFeed,
} from "@/services/groups";
import { useToastStore } from "@/stores/toasts";
import type { Post } from "@/types";

// /groups: the newest posts of my groups, discovery (suggestions and browse),
// my groups, the groups I manage (each opens its dashboard), my invitations and
// the join requests I sent, with a side panel like the reference layout.
type Tab = "feed" | "discover" | "mine" | "manage" | "invites" | "requests";
const TABS: { id: Tab; icon: typeof Compass; label: string }[] = [
  { id: "feed", icon: Newspaper, label: "groups.tabs.feed" },
  { id: "discover", icon: Compass, label: "groups.tabs.discover" },
  { id: "mine", icon: UsersRound, label: "groups.tabs.mine" },
  { id: "manage", icon: ShieldCheck, label: "groups.tabs.manage" },
  { id: "invites", icon: Mail, label: "groups.tabs.invites" },
  { id: "requests", icon: Send, label: "groups.tabs.requests" },
];
const SCOPES: Record<"mine" | "manage" | "invites" | "requests", GroupScope> = {
  mine: "mine",
  manage: "managed",
  invites: "invited",
  requests: "requested",
};
const listScope = (x: Tab): GroupScope => (x === "discover" || x === "feed" ? "discover" : SCOPES[x]);

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const toasts = useToastStore();

const isTab = (v: unknown): v is Tab => TABS.some((x) => x.id === v);
const tab = ref<Tab>(isTab(route.query.tab) ? route.query.tab : "feed");

const mine = ref<Group[]>([]);
const mineLoaded = ref(false);
const items = ref<Group[]>([]);
const cursor = ref<string | null>(null);
const feed = ref<{ post: Post; group: Group }[]>([]);
const suggestions = ref<Group[]>([]);
const query = ref("");
const category = ref("");
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);
let generation = 0;

const panelTitle = computed(() => t(TABS.find((x) => x.id === tab.value)?.label ?? "groups.title"));

async function loadMine() {
  try {
    mine.value = (await groupsService.list("mine")).data;
  } catch {
    mine.value = [];
  } finally {
    mineLoaded.value = true;
  }
}

async function load() {
  const run = ++generation;
  loading.value = true;
  error.value = false;
  try {
    if (tab.value === "feed") {
      if (!mineLoaded.value) await loadMine();
      const merged = await myGroupsFeed(mine.value.filter((g) => g.content_visible).slice(0, 10));
      if (run === generation) feed.value = merged;
    } else if (tab.value === "discover") {
      const [page, suggested] = await Promise.all([
        groupsService.list("discover", null, query.value.trim(), category.value),
        query.value || category.value ? Promise.resolve(suggestions.value) : groupsService.suggestions().catch(() => []),
      ]);
      if (run !== generation) return;
      items.value = page.data;
      cursor.value = page.page.next_cursor;
      suggestions.value = suggested;
    } else {
      const page = await groupsService.list(listScope(tab.value));
      if (run !== generation) return;
      items.value = page.data;
      cursor.value = page.page.next_cursor;
    }
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
    const page = await groupsService.list(listScope(tab.value), cursor.value, query.value.trim(), category.value);
    if (run !== generation) return;
    items.value = [...items.value, ...page.data];
    cursor.value = page.page.next_cursor;
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

async function dismiss(id: string) {
  const before = suggestions.value;
  suggestions.value = before.filter((g) => g.id !== id);
  try {
    await groupsService.dismissSuggestion(id);
  } catch (e) {
    suggestions.value = before;
    toasts.error(e);
  }
}

function pick(next: Tab) {
  if (tab.value === next) return;
  tab.value = next;
  router.replace({ query: { ...route.query, tab: next === "feed" ? undefined : next } });
}

function removed(id: string) {
  feed.value = feed.value.filter((x) => x.post.id !== id);
}

let searchTimer: number | undefined;
watch([query, category], () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(load, 300);
});
watch(tab, load);
onMounted(async () => {
  await loadMine();
  load();
});
</script>

<template>
  <AppShell :right="false">
    <div class="mx-auto grid w-full max-w-[1100px] gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <!-- Side panel -->
      <aside class="card h-fit space-y-3 p-3 lg:sticky lg:top-20" :aria-label="t('groups.title')">
        <h1 class="px-2 text-xl font-bold">{{ t("groups.title") }}</h1>
        <nav class="flex gap-1 overflow-x-auto lg:flex-col" role="tablist" :aria-label="t('groups.title')">
          <button
            v-for="x in TABS"
            :id="`groups-tab-${x.id}`"
            :key="x.id"
            type="button"
            role="tab"
            :aria-selected="tab === x.id"
            aria-controls="groups-panel"
            class="nav-item shrink-0 whitespace-nowrap"
            :class="tab === x.id ? 'nav-item-active' : ''"
            @click="pick(x.id)"
          >
            <component :is="x.icon" class="h-5 w-5 shrink-0" aria-hidden="true" />
            {{ t(x.label) }}
          </button>
        </nav>
        <RouterLink to="/groups/new" class="btn-gradient w-full">
          <Plus class="h-4 w-4" aria-hidden="true" /> {{ t("groups.create") }}
        </RouterLink>
        <div v-if="mine.length" class="hidden border-t border-gray-100 pt-3 dark:border-gray-800 lg:block">
          <h2 class="px-2 pb-1 text-sm font-bold text-gray-600 dark:text-gray-300">{{ t("groups.sidebar.yours") }}</h2>
          <ul class="space-y-0.5">
            <li v-for="g in mine.slice(0, 12)" :key="g.id">
              <RouterLink :to="groupPath(g)" class="nav-item">
                <UsersRound class="h-4 w-4 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden="true" />
                <span class="min-w-0 flex-1 truncate"><bdi>{{ g.name }}</bdi></span>
                <span v-if="isStaff(g.viewer.role)" class="text-[10px] text-gray-500 dark:text-gray-400">{{ t(`groups.roles.${g.viewer.role}`) }}</span>
              </RouterLink>
            </li>
          </ul>
        </div>
      </aside>

      <!-- Panel -->
      <section id="groups-panel" role="tabpanel" :aria-labelledby="`groups-tab-${tab}`" class="min-w-0 space-y-4">
        <h2 class="px-1 text-lg font-bold">{{ panelTitle }}</h2>

        <template v-if="tab === 'discover'">
          <div class="flex flex-wrap gap-2">
            <label class="relative min-w-48 flex-1">
              <span class="sr-only">{{ t("groups.search") }}</span>
              <Search class="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" aria-hidden="true" />
              <input v-model="query" type="search" class="input ps-9" :placeholder="t('groups.search')" dir="auto" maxlength="100" />
            </label>
            <label>
              <span class="sr-only">{{ t("groups.form.category") }}</span>
              <select v-model="category" class="input w-auto">
                <option value="">{{ t("groups.allCategories") }}</option>
                <option v-for="c in GROUP_CATEGORIES" :key="c" :value="c">{{ t(`groups.categories.${c}`) }}</option>
              </select>
            </label>
          </div>
        </template>

        <LoadingSkeleton v-if="loading" :rows="3" />
        <ErrorState v-else-if="error" @retry="load" />

        <template v-else-if="tab === 'feed'">
          <EmptyState v-if="!feed.length">
            {{ mine.length ? t("groups.empty.feed") : t("groups.empty.noGroups") }}
            <template #action>
              <button type="button" class="btn-soft" @click="pick('discover')">{{ t("groups.tabs.discover") }}</button>
            </template>
          </EmptyState>
          <div v-for="item in feed" :key="item.post.id" class="space-y-1">
            <RouterLink :to="groupPath(item.group)" class="flex items-center gap-1 px-1 text-sm font-semibold text-brand-700 hover:underline dark:text-brand-300">
              <UsersRound class="h-4 w-4" aria-hidden="true" /> <bdi>{{ item.group.name }}</bdi>
            </RouterLink>
            <PostCard
              :post="item.post"
              :group-moderator="!!item.group.viewer.can.moderate"
              :group-can-pin="!!item.group.viewer.can.pin"
              @removed="removed"
            />
          </div>
        </template>

        <template v-else>
          <section v-if="tab === 'discover' && suggestions.length" aria-labelledby="groups-suggested" class="space-y-2">
            <h3 id="groups-suggested" class="section-title px-1">{{ t("groups.suggestions.title") }}</h3>
            <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              <GroupCard v-for="g in suggestions" :key="g.id" :group="g" dismissible @dismiss="dismiss" />
            </div>
          </section>
          <h3 v-if="tab === 'discover'" class="section-title px-1">{{ t("groups.browse") }}</h3>
          <EmptyState v-if="!items.length">{{ t(`groups.empty.${tab}`) }}</EmptyState>
          <div v-else class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" :data-testid="`groups-list-${tab}`">
            <GroupCard v-for="g in items" :key="g.id" :group="g">
              <template v-if="tab === 'manage'" #actions>
                <span class="text-xs font-semibold text-brand-700 dark:text-brand-300">{{ t(`groups.roles.${g.viewer.role}`) }}</span>
                <RouterLink :to="`${groupPath(g)}/manage`" class="btn-soft ms-auto px-3 py-1.5 text-sm" data-testid="group-manage-link">
                  <Settings2 class="h-4 w-4" aria-hidden="true" /> {{ t("groups.manage.link") }}
                </RouterLink>
              </template>
              <template v-else-if="tab === 'requests' || tab === 'invites'" #actions>
                <JoinButton :group="g" @changed="load" />
              </template>
            </GroupCard>
          </div>
          <button v-if="cursor" class="btn-ghost mx-auto mt-3 block" :disabled="loadingMore" @click="loadMore">
            {{ loadingMore ? t("states.loading") : t("states.loadMore") }}
          </button>
        </template>
      </section>
    </div>
  </AppShell>
</template>
