<script setup lang="ts">
import { Clock, Hash, Search, TrendingUp, UsersRound, X } from "lucide-vue-next";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { groupSuggestions, nextActive } from "@/lib/search";
import {
  type RecentSearch,
  type SearchResult,
  type TrendingTag,
  searchService,
} from "@/services/search";
import { useDirectoryStore } from "@/stores/directory";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const directory = useDirectoryStore();

const LISTBOX_ID = "global-search-listbox";
const DEBOUNCE_MS = 220;

const input = ref<HTMLInputElement | null>(null);
const q = ref(route.name === "search" ? String(route.query.q ?? "") : "");
const open = ref(false);
const active = ref(-1);
const suggestions = ref<SearchResult[]>([]);
const recent = ref<RecentSearch[]>([]);
const trending = ref<TrendingTag[]>([]);

const typing = computed(() => q.value.trim().length >= 2);

type Row =
  | { key: string; kind: "recent"; item: RecentSearch }
  | { key: string; kind: "trending"; tag: TrendingTag }
  | { key: string; kind: "suggestion"; item: SearchResult }
  | { key: string; kind: "submit"; q: string };

interface Section {
  id: string;
  label: string;
  rows: Row[];
}

const sections = computed<Section[]>(() => {
  if (typing.value) {
    const out: Section[] = groupSuggestions(suggestions.value).map((g) => ({
      id: `gs-group-${g.type}`,
      label: t(`search.groupLabels.${g.type}`),
      rows: g.items.map((item) => ({ key: `s:${item.type}:${item.id}`, kind: "suggestion", item })),
    }));
    out.push({ id: "gs-submit", label: "", rows: [{ key: "submit", kind: "submit", q: q.value.trim() }] });
    return out;
  }
  const out: Section[] = [];
  if (recent.value.length) {
    out.push({
      id: "gs-recent",
      label: t("search.recent"),
      rows: recent.value.map((item) => ({ key: `r:${item.id}`, kind: "recent", item })),
    });
  }
  if (trending.value.length) {
    out.push({
      id: "gs-trending",
      label: t("search.trending"),
      rows: trending.value.map((tag) => ({ key: `t:${tag.tag}`, kind: "trending", tag })),
    });
  }
  return out;
});

const rows = computed(() => sections.value.flatMap((s) => s.rows));
const indexOf = (row: Row) => rows.value.indexOf(row);
const optionId = (i: number) => `gs-option-${i}`;
const activeId = computed(() => (open.value && active.value >= 0 ? optionId(active.value) : undefined));

watch(rows, () => (active.value = -1));

// ---- data ---------------------------------------------------------------------

let loadedExtras = false;
async function loadExtras() {
  try {
    recent.value = await searchService.recent();
  } catch {
    recent.value = [];
  }
  if (loadedExtras) return;
  loadedExtras = true;
  try {
    trending.value = (await searchService.trending("week")).slice(0, 5);
  } catch {
    trending.value = [];
  }
}

let timer: number | undefined;
let generation = 0;
watch(q, (value) => {
  window.clearTimeout(timer);
  const term = value.trim();
  const current = ++generation;
  if (term.length < 2) {
    suggestions.value = [];
    return;
  }
  timer = window.setTimeout(async () => {
    try {
      const hits = await searchService.suggest(term);
      if (current === generation) suggestions.value = hits;
    } catch {
      if (current === generation) suggestions.value = [];
    }
  }, DEBOUNCE_MS);
});
onBeforeUnmount(() => window.clearTimeout(timer));

// The field mirrors the results page's query.
watch(
  () => [route.name, route.query.q] as const,
  ([name, value]) => {
    if (name === "search") q.value = String(value ?? "");
  },
);

// ---- actions ------------------------------------------------------------------

function openPanel() {
  if (!open.value) {
    open.value = true;
    loadExtras();
  }
}
function close() {
  open.value = false;
  active.value = -1;
}

function go(term: string) {
  const value = term.trim();
  if (!value) return;
  q.value = value;
  close();
  searchService.rememberQuery(value).catch(() => undefined); // history is best-effort
  router.push({ name: "search", query: { q: value } });
}

function openEntity(type: string, id: string, title: string, handle?: string) {
  close();
  if (type === "user") router.push({ name: "profile-by-id", params: { id } });
  else if (type === "page" && handle) router.push({ name: "page", params: { handle } });
  else if (type === "group") router.push(`/groups/${encodeURIComponent(handle || id)}`);
  else if (type === "hashtag") router.push({ name: "search", query: { q: title.startsWith("#") ? title : `#${title}` } });
  else router.push({ name: "search", query: { q: title, type: type === "page" ? "pages" : type === "group" ? "groups" : undefined } });
}

function activate(row: Row) {
  if (row.kind === "submit") return go(row.q);
  if (row.kind === "trending") return go(`#${row.tag.tag}`);
  if (row.kind === "recent") {
    const r = row.item;
    if (r.kind === "query" || !r.doc_type || !r.doc_id) return go(r.query || r.title);
    return openEntity(r.doc_type, r.doc_id, r.title, r.handle ?? undefined);
  }
  const s = row.item;
  q.value = "";
  searchService.rememberEntity(s.type, s.id).catch(() => undefined);
  openEntity(s.type, s.id, s.title, s.handle);
}

async function removeRecent(item: RecentSearch) {
  recent.value = recent.value.filter((r) => r.id !== item.id);
  try {
    await searchService.forget(item.id);
  } catch {
    loadExtras(); // put it back as the server has it
  }
}
async function clearRecent() {
  recent.value = [];
  try {
    await searchService.clearRecent();
  } catch {
    loadExtras();
  }
  input.value?.focus();
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") {
    if (open.value) {
      e.preventDefault();
      close();
    }
    return; // focus stays in the field
  }
  if (e.key === "Enter") {
    e.preventDefault();
    const row = active.value >= 0 ? rows.value[active.value] : undefined;
    if (row) activate(row);
    else go(q.value);
    return;
  }
  if (e.key === "Delete" && open.value && active.value >= 0) {
    const row = rows.value[active.value];
    if (row?.kind === "recent") {
      e.preventDefault();
      removeRecent(row.item);
    }
    return;
  }
  // Home/End keep their caret meaning in a text field.
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  e.preventDefault();
  if (!open.value) {
    openPanel();
    return;
  }
  const next = nextActive(active.value, rows.value.length, e.key);
  if (next !== null) {
    active.value = next;
    document.getElementById(optionId(next))?.scrollIntoView({ block: "nearest" });
  }
}

function resultAvatarName(s: SearchResult): string {
  return s.display_name || s.name || s.title;
}
function subtitle(s: SearchResult): string {
  if (s.type === "user") return s.handle ? `@${s.handle}` : "";
  if (s.type === "hashtag") return s.post_count ? t("search.hashtagPosts", s.post_count) : "";
  if (s.type === "group") return s.privacy ? t(`search.privacy.${s.privacy}`) : "";
  if (s.type === "page") return typeof s.category === "string" ? s.category : "";
  return s.snippet ?? "";
}
function recentTitle(r: RecentSearch): string {
  return r.title || r.query;
}
</script>

<template>
  <div class="relative">
    <form role="search" @submit.prevent="go(q)">
      <Search class="pointer-events-none absolute inset-y-0 start-4 my-auto h-4 w-4 text-gray-500 dark:text-gray-400" aria-hidden="true" />
      <input
        ref="input"
        v-model="q"
        type="search"
        role="combobox"
        class="input h-11 rounded-full border-transparent bg-gray-100 ps-11 dark:border-transparent dark:bg-gray-900"
        dir="auto"
        :placeholder="t('search.placeholder')"
        :aria-label="t('nav.search')"
        aria-autocomplete="list"
        :aria-expanded="open"
        :aria-controls="LISTBOX_ID"
        :aria-activedescendant="activeId"
        autocomplete="off"
        data-testid="global-search"
        @focus="openPanel"
        @click="openPanel"
        @input="openPanel"
        @keydown="onKeydown"
      />
    </form>

    <template v-if="open">
      <div class="fixed inset-0 z-30" aria-hidden="true" @click="close" />
      <div class="popover absolute inset-x-0 z-40 mt-2 max-h-[70vh] overflow-y-auto p-2" data-testid="global-search-panel">
        <div v-if="!typing && recent.length" class="flex items-center justify-between px-3 py-1">
          <span class="text-xs font-bold text-gray-500 dark:text-gray-400">{{ t("search.recent") }}</span>
          <button
            type="button"
            class="rounded text-xs font-semibold text-brand-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:text-brand-300"
            @mousedown.prevent
            @click="clearRecent"
          >
            {{ t("search.clearAll") }}
          </button>
        </div>

        <div :id="LISTBOX_ID" role="listbox" :aria-label="t('search.suggestions')">
          <div
            v-for="section in sections"
            :key="section.id"
            :role="section.label ? 'group' : 'presentation'"
            :aria-labelledby="section.label && section.id !== 'gs-recent' ? `${section.id}-label` : undefined"
            :aria-label="section.id === 'gs-recent' ? section.label : undefined"
          >
            <div
              v-if="section.label && section.id !== 'gs-recent'"
              :id="`${section.id}-label`"
              class="px-3 pb-1 pt-2 text-xs font-bold text-gray-500 dark:text-gray-400"
            >
              {{ section.label }}
            </div>
            <div
              v-for="row in section.rows"
              :id="optionId(indexOf(row))"
              :key="row.key"
              role="option"
              :aria-selected="active === indexOf(row)"
              class="flex w-full cursor-pointer items-center gap-3 rounded-xl px-3 py-2 text-start text-sm transition"
              :class="active === indexOf(row) ? 'bg-brand-50 dark:bg-brand-950/60' : 'hover:bg-gray-100 dark:hover:bg-gray-800'"
              @mousedown.prevent
              @mousemove="active = indexOf(row)"
              @click="activate(row)"
            >
              <!-- recent -->
              <template v-if="row.kind === 'recent'">
                <UserAvatar
                  v-if="row.item.kind === 'entity' && row.item.doc_type !== 'hashtag'"
                  :name="recentTitle(row.item)"
                  :media-id="row.item.avatar_media_id"
                  :size="36"
                />
                <span v-else class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-300">
                  <Clock class="h-4 w-4" aria-hidden="true" />
                </span>
                <span class="min-w-0 flex-1 truncate font-medium" dir="auto">{{ recentTitle(row.item) }}</span>
                <span
                  aria-hidden="true"
                  class="rounded-full p-1 text-gray-400 hover:bg-gray-200 hover:text-gray-700 dark:hover:bg-gray-700 dark:hover:text-gray-100"
                  :title="t('search.removeRecent', { name: recentTitle(row.item) })"
                  data-testid="recent-remove"
                  @click.stop="removeRecent(row.item)"
                >
                  <X class="h-4 w-4" />
                </span>
              </template>

              <!-- trending -->
              <template v-else-if="row.kind === 'trending'">
                <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-50 text-accent-600 dark:bg-accent-900/30 dark:text-accent-300">
                  <TrendingUp class="h-4 w-4" aria-hidden="true" />
                </span>
                <span class="min-w-0 flex-1 truncate font-medium" dir="auto">#{{ row.tag.tag }}</span>
              </template>

              <!-- live suggestion -->
              <template v-else-if="row.kind === 'suggestion'">
                <UserAvatar
                  v-if="row.item.type === 'user' || row.item.type === 'page'"
                  :name="resultAvatarName(row.item)"
                  :media-id="row.item.avatar_media_id ?? (row.item.type === 'user' ? directory.avatarOf(row.item.id) : null)"
                  :size="36"
                />
                <span v-else class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-600 dark:bg-brand-950/70 dark:text-brand-300">
                  <Hash v-if="row.item.type === 'hashtag'" class="h-4 w-4" aria-hidden="true" />
                  <UsersRound v-else class="h-4 w-4" aria-hidden="true" />
                </span>
                <span class="min-w-0 flex-1">
                  <span class="block truncate font-semibold" dir="auto">{{ row.item.title }}</span>
                  <span v-if="subtitle(row.item)" class="block truncate text-xs text-gray-500 dark:text-gray-400" dir="auto">{{ subtitle(row.item) }}</span>
                </span>
              </template>

              <!-- search for q -->
              <template v-else>
                <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-tara-gradient text-white">
                  <Search class="h-4 w-4" aria-hidden="true" />
                </span>
                <span class="min-w-0 flex-1 truncate font-semibold text-brand-700 dark:text-brand-300" dir="auto">
                  {{ t("search.searchFor", { q: row.q }) }}
                </span>
              </template>
            </div>
          </div>
        </div>

        <p v-if="!typing && !recent.length" class="px-3 py-2 text-xs text-gray-500 dark:text-gray-400">
          {{ t("search.noRecent") }}
        </p>
      </div>
    </template>
  </div>
</template>
