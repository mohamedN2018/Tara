<script setup lang="ts">
import { CalendarClock, Download, Eye, Pencil, Search, Send, Trash2, UsersRound } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import StudioPostThumb from "@/components/studio/StudioPostThumb.vue";
import { useStudioComposer } from "@/components/studio/studioComposer";
import { zoneLabel } from "@/lib/planner";
import { dayEdge, spanDays, toCsv } from "@/lib/studioRange";
import { COMPOSER_ERRORS, type ComposerPost, composerService, timeZoneName } from "@/services/composer";
import { postService } from "@/services/post";
import { LIBRARY_TYPES, type LibraryType, studioService } from "@/services/studio";
import { useToastStore } from "@/stores/toasts";

defineOptions({ name: "StudioLibraryView" });

/**
 * The content library: published posts, scheduled posts and drafts, each with
 * its real actions (edit, publish now, delete; view a published post). A
 * `?edit=<id>` deep link opens the composer on that draft or scheduled post.
 */
type Tab = "published" | "scheduled" | "drafts";
const TABS: Tab[] = ["published", "scheduled", "drafts"];

const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const toasts = useToastStore();
const composer = useStudioComposer();

const tab = computed<Tab>(() => (TABS.includes(route.query.tab as Tab) ? (route.query.tab as Tab) : "published"));
const type = ref<LibraryType | "">("");
const rows = ref<ComposerPost[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(true);
const more = ref(false);
const failed = ref(false);
const confirming = ref<string | null>(null);
const busy = ref<string | null>(null);
const counts = ref<Record<Tab, number | null>>({ published: null, scheduled: null, drafts: null });
const zone = zoneLabel(locale.value, timeZoneName());

// ---- the published tab's filters: text, publication dates (local days) ----------------
const q = ref("");
const qApplied = ref("");
const fromDay = ref("");
const toDay = ref("");
const filtersError = computed(() => (fromDay.value && toDay.value && !spanDays(fromDay.value, toDay.value) ? t("polish.studio.rangeInvalid") : ""));
const filter = computed(() => ({
  type: type.value,
  q: qApplied.value,
  from: fromDay.value ? dayEdge(fromDay.value) : null,
  to: toDay.value ? dayEdge(toDay.value, true) : null,
}));
const filtered = computed(() => !!(qApplied.value || fromDay.value || toDay.value || type.value));
let qTimer: number | null = null;
watch(q, (v) => {
  if (qTimer) window.clearTimeout(qTimer);
  qTimer = window.setTimeout(() => (qApplied.value = v.trim()), 300);
});
function clearFilters() {
  q.value = qApplied.value = fromDay.value = toDay.value = "";
  type.value = "";
}

// ---- CSV export of the filtered published posts (every page, up to a cap) ------------------
const EXPORT_MAX = 2000;
const exporting = ref(false);
async function exportCsv() {
  if (exporting.value || filtersError.value) return;
  exporting.value = true;
  try {
    const all: ComposerPost[] = [];
    let next: string | null = null;
    do {
      const page = await studioService.published(filter.value, next, 100);
      all.push(...page.data);
      next = page.page.has_more ? page.page.next_cursor : null;
    } while (next && all.length < EXPORT_MAX);
    const rows = all.slice(0, EXPORT_MAX).map((p) => [
      p.created_at ?? "",
      t(`studio.library.types.${p.type}`),
      (p.body || "").replace(/\s+/g, " ").trim(),
      p.reaction_count,
      p.comment_count,
      p.share_count,
      `${window.location.origin}/posts/${p.id}`,
    ]);
    const csv = toCsv(
      ["published_at", "type", "text", "reactions", "comments", "shares", "url"].map((k) => t(`polish.studio.csv.${k}`)),
      rows,
    );
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `tara-content-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    toasts.success(t("polish.studio.exported", { count: rows.length }, rows.length));
  } catch (err) {
    toasts.error(err);
  } finally {
    exporting.value = false;
  }
}

async function fetchPage(next: string | null) {
  if (tab.value === "published") return studioService.published(filter.value, next);
  return composerService.drafts(tab.value === "drafts" ? "draft" : "scheduled", next);
}

let seq = 0;
async function load(reset = true) {
  const mine = ++seq;
  if (reset) {
    loading.value = true;
    confirming.value = null;
  } else more.value = true;
  failed.value = false;
  try {
    const page = await fetchPage(reset ? null : cursor.value);
    if (mine !== seq) return;
    rows.value = reset ? page.data : rows.value.concat(page.data);
    cursor.value = page.page.has_more ? page.page.next_cursor : null;
  } catch {
    if (mine === seq) failed.value = true;
  } finally {
    if (mine === seq) {
      loading.value = false;
      more.value = false;
    }
  }
}

async function loadCounts() {
  try {
    const s = await studioService.summary();
    counts.value = { published: s.posts, scheduled: s.scheduled, drafts: s.drafts };
  } catch {
    counts.value = { published: null, scheduled: null, drafts: null };
  }
}

function refresh() {
  void load();
  void loadCounts();
}

watch(
  () => [tab.value, type.value, qApplied.value, fromDay.value, toDay.value],
  () => {
    if (!filtersError.value) void load();
  },
);
watch(composer.version, refresh);

// ---- the deep link: /studio/library?edit=<id> -----------------------------------------
async function openDeepLink() {
  const id = typeof route.query.edit === "string" ? route.query.edit : "";
  if (!id) return;
  try {
    const draft = await composerService.draft(id);
    composer.open({ draft });
  } catch {
    toasts.push({ text: t("studio.library.notFound"), icon: "error" });
  }
  const rest = { ...route.query };
  delete rest.edit;
  void router.replace({ query: { ...rest, tab: rest.tab ?? "drafts" } });
}
watch(() => route.query.edit, openDeepLink);

onMounted(() => {
  refresh();
  void openDeepLink();
});

function selectTab(next: Tab) {
  if (next !== tab.value) void router.replace({ query: { ...route.query, tab: next } });
}
function onTabKey(e: KeyboardEvent, i: number) {
  const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
  if (!step) return;
  // In RTL the arrows follow the reading direction.
  const dir = document.documentElement.dir === "rtl" ? -step : step;
  const next = TABS[(i + dir + TABS.length) % TABS.length];
  selectTab(next);
  (document.getElementById(`library-tab-${next}`) as HTMLElement | null)?.focus();
}

// ---- actions ------------------------------------------------------------------------------
async function publishNow(p: ComposerPost) {
  busy.value = p.id;
  try {
    await composerService.publishDraft(p.id);
    toasts.success(t("studio.library.publishedToast"));
    composer.touch();
  } catch (err) {
    toasts.error(err, COMPOSER_ERRORS);
    refresh();
  } finally {
    busy.value = null;
  }
}

async function remove(p: ComposerPost) {
  busy.value = p.id;
  try {
    if (tab.value === "published") await postService.remove(p.id);
    else await composerService.deleteDraft(p.id);
    rows.value = rows.value.filter((r) => r.id !== p.id);
    confirming.value = null;
    toasts.success(t("studio.library.deletedToast"));
    composer.touch();
  } catch (err) {
    toasts.error(err);
  } finally {
    busy.value = null;
  }
}

// ---- formatting ---------------------------------------------------------------------------
const fmtNumber = (n: number) => new Intl.NumberFormat(locale.value).format(n);
const fmtTime = (iso?: string | null) =>
  iso ? new Intl.DateTimeFormat(locale.value, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso)) : "";
const excerpt = (p: ComposerPost) => (p.body || "").trim() || t("studio.library.noText");
function when(p: ComposerPost): string {
  if (tab.value === "scheduled") return fmtTime(p.publish_at);
  if (tab.value === "drafts") return fmtTime(p.updated_at);
  return fmtTime(p.created_at);
}
const whenLabel = computed(() =>
  tab.value === "scheduled" ? t("studio.library.cols.scheduledFor") : tab.value === "drafts" ? t("studio.library.cols.lastEdited") : t("studio.library.cols.published"),
);
</script>

<template>
  <div class="mx-auto max-w-6xl" data-testid="studio-library">
    <div class="card overflow-hidden">
      <header class="flex flex-wrap items-end justify-between gap-3 px-4 pt-4 sm:px-5">
        <div>
          <h1 class="text-2xl font-extrabold tracking-tight text-gray-900 dark:text-white">{{ t("studio.library.title") }}</h1>
          <p v-if="tab === 'scheduled'" class="mt-0.5 text-xs text-gray-500 dark:text-gray-400" dir="auto">{{ t("studio.library.zone", { zone }) }}</p>
        </div>
        <div v-if="tab === 'published'" class="flex flex-wrap items-end gap-2">
          <label class="relative block text-sm">
            <span class="sr-only">{{ t("polish.studio.searchLabel") }}</span>
            <Search class="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500 dark:text-gray-400" aria-hidden="true" />
            <input v-model="q" type="search" class="input w-56 py-1.5 ps-9" dir="auto" maxlength="100" :placeholder="t('polish.studio.searchPlaceholder')" data-testid="library-search" />
          </label>
          <label class="flex items-center gap-2 text-sm">
            <span class="font-semibold text-gray-600 dark:text-gray-300">{{ t("studio.library.type") }}</span>
            <select v-model="type" class="input w-auto py-1.5" data-testid="library-type">
              <option value="">{{ t("studio.library.allTypes") }}</option>
              <option v-for="k in LIBRARY_TYPES" :key="k" :value="k">{{ t(`studio.library.types.${k}`) }}</option>
            </select>
          </label>
          <label class="flex items-center gap-2 text-sm">
            <span class="font-semibold text-gray-600 dark:text-gray-300">{{ t("polish.studio.from") }}</span>
            <input v-model.lazy="fromDay" type="date" class="input w-auto py-1.5" dir="ltr" :max="toDay || undefined" data-testid="library-from" />
          </label>
          <label class="flex items-center gap-2 text-sm">
            <span class="font-semibold text-gray-600 dark:text-gray-300">{{ t("polish.studio.to") }}</span>
            <input v-model.lazy="toDay" type="date" class="input w-auto py-1.5" dir="ltr" :min="fromDay || undefined" data-testid="library-to" />
          </label>
          <button v-if="filtered" type="button" class="btn-ghost px-3 py-1.5 text-sm" data-testid="library-clear" @click="clearFilters">{{ t("polish.studio.clearFilters") }}</button>
          <button type="button" class="btn-outline px-3 py-1.5 text-sm" :disabled="exporting || !!filtersError" data-testid="library-export" @click="exportCsv">
            <Download class="h-4 w-4" aria-hidden="true" /> {{ exporting ? t("polish.studio.exporting") : t("polish.studio.exportCsv") }}
          </button>
        </div>
      </header>
      <p v-if="tab === 'published' && filtersError" class="px-4 pt-2 text-sm text-red-700 dark:text-red-400 sm:px-5" role="alert">{{ filtersError }}</p>

      <!-- Tabs: one row, like the reference's content library. -->
      <div role="tablist" :aria-label="t('studio.library.tabsLabel')" class="mt-3 flex gap-1 overflow-x-auto border-b border-gray-200 px-2 dark:border-gray-800 sm:px-3">
        <button
          v-for="(k, i) in TABS"
          :id="`library-tab-${k}`"
          :key="k"
          type="button"
          role="tab"
          :aria-selected="tab === k"
          aria-controls="library-panel"
          :tabindex="tab === k ? 0 : -1"
          class="relative shrink-0 px-3 py-3 text-sm font-semibold transition"
          :class="tab === k ? 'text-brand-700 dark:text-brand-300' : 'text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white'"
          :data-testid="`library-tab-${k}`"
          @click="selectTab(k)"
          @keydown="onTabKey($event, i)"
        >
          {{ t(`studio.library.tabs.${k}`) }}
          <span v-if="counts[k] !== null" class="ms-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-800">{{ fmtNumber(counts[k]!) }}</span>
          <span v-if="tab === k" class="absolute inset-x-2 bottom-0 h-[3px] rounded-full bg-brand-600" aria-hidden="true" />
        </button>
      </div>

      <div id="library-panel" role="tabpanel" :aria-labelledby="`library-tab-${tab}`" class="p-2 sm:p-3">
        <LoadingSkeleton v-if="loading" :rows="2" />
        <ErrorState v-else-if="failed" @retry="load()" />
        <EmptyState v-else-if="!rows.length">{{ tab === "published" && filtered ? t("polish.studio.noMatches") : t(`studio.library.empty.${tab}`) }}</EmptyState>
        <template v-else>
          <!-- Column headings (wide screens). -->
          <div
            class="hidden grid-cols-[minmax(0,1fr)_11rem_5.5rem_5.5rem_5.5rem_12rem] gap-3 border-b border-gray-100 px-3 pb-2 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:border-gray-800 dark:text-gray-400 md:grid"
            aria-hidden="true"
          >
            <span>{{ t("studio.library.cols.post") }}</span>
            <span>{{ whenLabel }}</span>
            <span>{{ tab === "published" ? t("studio.library.cols.reactions") : "" }}</span>
            <span>{{ tab === "published" ? t("studio.library.cols.comments") : "" }}</span>
            <span>{{ tab === "published" ? t("studio.library.cols.shares") : "" }}</span>
            <span class="text-end">{{ t("studio.library.cols.actions") }}</span>
          </div>
          <ul class="divide-y divide-gray-100 dark:divide-gray-800" data-testid="library-rows">
            <li
              v-for="p in rows"
              :key="p.id"
              class="grid grid-cols-1 items-center gap-2 px-3 py-3 md:grid-cols-[minmax(0,1fr)_11rem_5.5rem_5.5rem_5.5rem_12rem] md:gap-3"
              :data-post-id="p.id"
            >
              <div class="flex min-w-0 items-center gap-3">
                <StudioPostThumb :type="p.type" :media-ids="p.media_ids" :size="48" />
                <div class="min-w-0">
                  <p class="line-clamp-2 text-sm font-semibold text-gray-900 dark:text-gray-100" dir="auto">{{ excerpt(p) }}</p>
                  <p class="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-gray-500 dark:text-gray-400">
                    <span>{{ t(`studio.library.types.${p.type}`) }}</span>
                    <span v-if="p.group_id" class="inline-flex items-center gap-1"><UsersRound class="h-3 w-3" aria-hidden="true" />{{ t("studio.library.inGroup") }}</span>
                    <span class="md:hidden">· {{ whenLabel }}: {{ when(p) }}</span>
                  </p>
                </div>
              </div>
              <span class="hidden text-sm text-gray-700 dark:text-gray-300 md:flex md:items-center md:gap-1">
                <CalendarClock v-if="tab === 'scheduled'" class="h-4 w-4 shrink-0 text-accent-500" aria-hidden="true" />{{ when(p) }}
              </span>
              <template v-if="tab === 'published'">
                <span class="text-sm text-gray-700 dark:text-gray-300"><span class="md:sr-only">{{ t("studio.library.cols.reactions") }}: </span>{{ fmtNumber(p.reaction_count) }}</span>
                <span class="text-sm text-gray-700 dark:text-gray-300"><span class="md:sr-only">{{ t("studio.library.cols.comments") }}: </span>{{ fmtNumber(p.comment_count) }}</span>
                <span class="text-sm text-gray-700 dark:text-gray-300"><span class="md:sr-only">{{ t("studio.library.cols.shares") }}: </span>{{ fmtNumber(p.share_count) }}</span>
              </template>
              <template v-else>
                <span class="hidden md:block" /><span class="hidden md:block" /><span class="hidden md:block" />
              </template>

              <div class="flex flex-wrap items-center justify-start gap-1 md:justify-end">
                <template v-if="confirming === p.id">
                  <span class="text-xs font-semibold text-red-600 dark:text-red-400">{{ t("studio.library.confirmDelete") }}</span>
                  <button type="button" class="btn-danger px-3 py-1.5" :disabled="busy === p.id" data-testid="library-confirm-delete" @click="remove(p)">{{ t("studio.library.delete") }}</button>
                  <button type="button" class="btn-ghost px-3 py-1.5" @click="confirming = null">{{ t("studio.library.cancel") }}</button>
                </template>
                <template v-else>
                  <RouterLink v-if="tab === 'published'" :to="`/posts/${p.id}`" class="icon-btn h-9 w-9" :aria-label="t('studio.library.view')" :title="t('studio.library.view')">
                    <Eye class="h-4 w-4" aria-hidden="true" />
                  </RouterLink>
                  <template v-else>
                    <button type="button" class="icon-btn h-9 w-9" :aria-label="t('studio.library.edit')" :title="t('studio.library.edit')" data-testid="library-edit" @click="composer.open({ draft: p })">
                      <Pencil class="h-4 w-4" aria-hidden="true" />
                    </button>
                    <button type="button" class="btn-soft px-3 py-1.5" :disabled="busy === p.id" data-testid="library-publish" @click="publishNow(p)">
                      <Send class="h-4 w-4 rtl:-scale-x-100" aria-hidden="true" />{{ t("studio.library.publishNow") }}
                    </button>
                  </template>
                  <button type="button" class="icon-btn h-9 w-9 hover:!text-red-600" :aria-label="t('studio.library.delete')" :title="t('studio.library.delete')" data-testid="library-delete" @click="confirming = p.id">
                    <Trash2 class="h-4 w-4" aria-hidden="true" />
                  </button>
                </template>
              </div>
            </li>
          </ul>
          <div v-if="cursor" class="flex justify-center p-3">
            <button type="button" class="btn-outline" :disabled="more" @click="load(false)">{{ t("studio.library.loadMore") }}</button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
