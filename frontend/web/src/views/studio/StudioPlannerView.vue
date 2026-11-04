<script setup lang="ts">
import { CalendarClock, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, Plus, SlidersHorizontal } from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import ErrorState from "@/components/states/ErrorState.vue";
import PlannerPostDialog from "@/components/studio/PlannerPostDialog.vue";
import StudioPostThumb from "@/components/studio/StudioPostThumb.vue";
import { useStudioComposer } from "@/components/studio/studioComposer";
import {
  addDays,
  addMonths,
  canScheduleOn,
  dayKey,
  defaultSlot,
  gridRange,
  groupByDay,
  monthGrid,
  moveToDay,
  type PlannerView,
  postTime,
  rescheduleProblem,
  weekGrid,
  zoneLabel,
} from "@/lib/planner";
import { COMPOSER_ERRORS, type ComposerPost, composerService, timeZoneName } from "@/services/composer";
import { studioService } from "@/services/studio";
import { useToastStore } from "@/stores/toasts";

defineOptions({ name: "StudioPlannerView" });

/**
 * The planner (reference 6): a month (or week) calendar of my scheduled and
 * published posts in my own time zone, today marked, Today / previous / next,
 * a month picker, a Month/Week switch and a filter. A scheduled post can be
 * dragged to another day (it keeps its local time) or opened to change its
 * time, edit, publish now or delete; a future day's "+" opens the composer
 * already scheduled on that day.
 */
const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const toasts = useToastStore();
const composer = useStudioComposer();

const MONTH_CHIPS = 2;
const zone = timeZoneName();
const zoneText = computed(() => zoneLabel(locale.value, zone));

// ---- where we are (kept in the URL: ?view=week&date=2026-11-04) ----------------------------
function parseDate(value: unknown): Date {
  const m = typeof value === "string" ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(value) : null;
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date();
  return Number.isNaN(d.getTime()) ? new Date() : d;
}
const view = computed<PlannerView>(() => (route.query.view === "week" ? "week" : "month"));
const anchor = computed(() => parseDate(route.query.date));
function go(next: { view?: PlannerView; date?: Date }) {
  const v = next.view ?? view.value;
  const d = next.date ?? anchor.value;
  void router.replace({ query: { ...route.query, view: v === "month" ? undefined : v, date: dayKey(d) } });
}

const days = computed(() => (view.value === "month" ? monthGrid(anchor.value) : weekGrid(anchor.value)));
const weeks = computed(() => {
  const out: Date[][] = [];
  for (let i = 0; i < days.value.length; i += 7) out.push(days.value.slice(i, i + 7));
  return out;
});
const todayKey = ref(dayKey(new Date()));

function step(dir: 1 | -1) {
  go({ date: view.value === "month" ? addMonths(anchor.value, dir) : addDays(anchor.value, 7 * dir) });
}

// ---- data ----------------------------------------------------------------------------------------
const posts = ref<ComposerPost[]>([]);
const truncated = ref(false);
const loading = ref(true);
const failed = ref(false);
const showScheduled = ref(true);
const showPublished = ref(true);
let seq = 0;

async function load() {
  const mine = ++seq;
  failed.value = false;
  loading.value = true;
  const { from, to } = gridRange(days.value);
  try {
    const page = await studioService.calendar(from, to);
    if (mine !== seq) return;
    posts.value = page.data;
    truncated.value = page.meta.truncated;
  } catch {
    if (mine === seq) failed.value = true;
  } finally {
    if (mine === seq) loading.value = false;
  }
  todayKey.value = dayKey(new Date());
}
watch(() => gridRange(days.value).from + view.value, load);
watch(composer.version, load);
onMounted(load);

const visible = computed(() =>
  posts.value.filter((p) => (p.state === "scheduled" ? showScheduled.value : showPublished.value)),
);
const byDay = computed(() => groupByDay(visible.value));
const postsOn = (d: Date) => byDay.value.get(dayKey(d)) ?? [];

// ---- formatting ----------------------------------------------------------------------------------
// As in the reference, Arabic dates (title, day numbers, year) use Arabic-Indic
// digits; times keep the app's usual digits.
const dateLocale = computed(() => (locale.value === "ar" ? "ar-EG-u-nu-arab" : locale.value));
const title = computed(() => new Intl.DateTimeFormat(dateLocale.value, { month: "long", year: "numeric" }).format(anchor.value));
const weekdays = computed(() => days.value.slice(0, 7).map((d) => new Intl.DateTimeFormat(locale.value, { weekday: "short" }).format(d)));
const dayNumber = (d: Date) => new Intl.NumberFormat(dateLocale.value).format(d.getDate());
const fullDate = (d: Date) => new Intl.DateTimeFormat(dateLocale.value, { dateStyle: "full" }).format(d);
const time = (p: ComposerPost) => new Intl.DateTimeFormat(locale.value, { hour: "numeric", minute: "2-digit" }).format(new Date(postTime(p)));
const excerpt = (p: ComposerPost) => (p.body || "").trim() || t("studio.library.noText");
const inMonth = (d: Date) => view.value === "week" || d.getMonth() === anchor.value.getMonth();
const chipLabel = (p: ComposerPost) =>
  `${p.state === "scheduled" ? t("studio.planner.scheduled") : t("studio.planner.published")}, ${time(p)}: ${excerpt(p)}`;

// ---- popovers: month picker, view switch, filter -------------------------------------------------
const pop = ref<"month" | "view" | "filter" | null>(null);
const pickerYear = ref(anchor.value.getFullYear());
const monthNames = computed(() =>
  Array.from({ length: 12 }, (_, m) => new Intl.DateTimeFormat(locale.value, { month: "short" }).format(new Date(2026, m, 1))),
);
function toggle(which: "month" | "view" | "filter") {
  pickerYear.value = anchor.value.getFullYear();
  pop.value = pop.value === which ? null : which;
}
function pickMonth(m: number) {
  pop.value = null;
  go({ view: "month", date: new Date(pickerYear.value, m, 1) });
}
function onDocument(e: Event) {
  if (pop.value && !(e.target as HTMLElement).closest("[data-popover-root]")) pop.value = null;
}
function onKey(e: KeyboardEvent) {
  if (e.key === "Escape") pop.value = null;
}
onMounted(() => {
  document.addEventListener("click", onDocument);
  window.addEventListener("keydown", onKey);
});
onBeforeUnmount(() => {
  document.removeEventListener("click", onDocument);
  window.removeEventListener("keydown", onKey);
});

// ---- the selected day (phones: the agenda under the grid) ------------------------------------------
const AGENDA_CAP = 10;
const selected = ref<Date>(new Date());
const agendaAll = ref(false);
watch(() => dayKey(selected.value), () => (agendaAll.value = false));
const selectedPosts = computed(() => postsOn(selected.value));
const agendaPosts = computed(() => (agendaAll.value ? selectedPosts.value : selectedPosts.value.slice(0, AGENDA_CAP)));

// ---- open, move, publish, delete ------------------------------------------------------------------
const opened = ref<ComposerPost | null>(null);
const busy = ref(false);

function scheduleOn(d: Date) {
  composer.open({ scheduleAt: defaultSlot(d).toISOString() });
}

async function reschedule(p: ComposerPost, at: Date) {
  const problem = rescheduleProblem(at);
  if (problem) {
    toasts.push({ text: t(problem === "past" ? "composer.errors.publishAtPast" : "composer.errors.publishAtTooFar"), icon: "error" });
    return;
  }
  busy.value = true;
  const before = p.publish_at;
  // Optimistic: the chip moves at once and comes back if the server refuses.
  posts.value = posts.value.map((x) => (x.id === p.id ? { ...x, publish_at: at.toISOString() } : x));
  try {
    const saved = await composerService.editDraft(p.id, { publish_at: at.toISOString() });
    posts.value = posts.value.map((x) => (x.id === p.id ? { ...x, ...saved } : x));
    opened.value = null;
    toasts.success(t("studio.planner.moved", { time: new Intl.DateTimeFormat(locale.value, { dateStyle: "medium", timeStyle: "short" }).format(at) }));
    composer.touch();
  } catch (err) {
    posts.value = posts.value.map((x) => (x.id === p.id ? { ...x, publish_at: before } : x));
    toasts.error(err, COMPOSER_ERRORS);
  } finally {
    busy.value = false;
  }
}

async function publishNow(p: ComposerPost) {
  busy.value = true;
  try {
    await composerService.publishDraft(p.id);
    opened.value = null;
    toasts.success(t("studio.library.publishedToast"));
    composer.touch();
  } catch (err) {
    toasts.error(err, COMPOSER_ERRORS);
  } finally {
    busy.value = false;
  }
}

async function remove(p: ComposerPost) {
  busy.value = true;
  try {
    await composerService.deleteDraft(p.id);
    posts.value = posts.value.filter((x) => x.id !== p.id);
    opened.value = null;
    toasts.success(t("studio.library.deletedToast"));
    composer.touch();
  } catch (err) {
    toasts.error(err);
  } finally {
    busy.value = false;
  }
}

function edit(p: ComposerPost) {
  opened.value = null;
  composer.open({ draft: p });
}

// Drag and drop: only scheduled posts move; a drop keeps the local time of day.
const dragging = ref<string | null>(null);
const over = ref<string | null>(null);
function onDragStart(e: DragEvent, p: ComposerPost) {
  if (p.state !== "scheduled") return;
  dragging.value = p.id;
  e.dataTransfer?.setData("text/plain", p.id);
  if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
}
function onDragOver(e: DragEvent, d: Date) {
  if (!dragging.value) return;
  e.preventDefault();
  over.value = dayKey(d);
}
function onDrop(e: DragEvent, d: Date) {
  e.preventDefault();
  const id = dragging.value || e.dataTransfer?.getData("text/plain");
  dragging.value = null;
  over.value = null;
  const p = posts.value.find((x) => x.id === id);
  if (!p || p.state !== "scheduled" || !p.publish_at) return;
  if (dayKey(new Date(p.publish_at)) === dayKey(d)) return;
  void reschedule(p, moveToDay(p.publish_at, d));
}
function onDragEnd() {
  dragging.value = null;
  over.value = null;
}
</script>

<template>
  <div class="card flex min-h-[calc(100vh-6rem)] flex-col overflow-hidden" data-testid="studio-planner">
    <!-- Header: month title + zone at the start; Today/prev/next, view and filter at the end. -->
    <header class="flex flex-wrap items-start justify-between gap-3 px-3 pb-2 pt-4 sm:px-5">
      <div class="relative min-w-0" data-popover-root>
        <h1 class="sr-only">{{ t("studio.planner.title") }}</h1>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-lg text-xl font-extrabold tracking-tight text-gray-900 hover:text-brand-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:text-white dark:hover:text-brand-300 sm:text-2xl"
          :aria-expanded="pop === 'month'"
          aria-haspopup="dialog"
          :aria-label="`${title}, ${t('studio.planner.pickMonth')}`"
          data-testid="planner-title"
          @click="toggle('month')"
        >
          {{ title }}
          <ChevronDown class="h-5 w-5" aria-hidden="true" />
        </button>
        <p class="mt-0.5 text-xs text-gray-500 dark:text-gray-400" dir="auto" data-testid="planner-zone">{{ zoneText }}</p>
        <div v-if="pop === 'month'" class="popover absolute start-0 top-full z-20 mt-2 w-72 p-3" role="dialog" :aria-label="t('studio.planner.pickMonth')" data-testid="planner-month-picker">
          <div class="flex items-center justify-between">
            <button type="button" class="icon-btn h-8 w-8" :aria-label="t('studio.planner.prevYear')" @click="pickerYear--">
              <ChevronRight class="h-4 w-4 ltr:rotate-180" aria-hidden="true" />
            </button>
            <span class="font-bold">{{ new Intl.NumberFormat(dateLocale, { useGrouping: false }).format(pickerYear) }}</span>
            <button type="button" class="icon-btn h-8 w-8" :aria-label="t('studio.planner.nextYear')" @click="pickerYear++">
              <ChevronLeft class="h-4 w-4 ltr:rotate-180" aria-hidden="true" />
            </button>
          </div>
          <div class="mt-2 grid grid-cols-3 gap-1">
            <button
              v-for="(name, m) in monthNames"
              :key="m"
              type="button"
              class="rounded-lg px-2 py-2 text-sm font-semibold hover:bg-gray-100 dark:hover:bg-gray-800"
              :class="pickerYear === anchor.getFullYear() && m === anchor.getMonth() && 'bg-brand-600 text-white hover:bg-brand-600 dark:hover:bg-brand-600'"
              @click="pickMonth(m)"
            >
              {{ name }}
            </button>
          </div>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <div class="flex items-center overflow-hidden rounded-xl bg-gray-100 dark:bg-gray-800">
          <!-- "Previous" points to the reading start: right in Arabic, left in English. -->
          <button type="button" class="flex h-10 w-10 items-center justify-center hover:bg-gray-200 dark:hover:bg-gray-700" :aria-label="t('studio.planner.prev')" data-testid="planner-prev" @click="step(-1)">
            <ChevronRight class="h-5 w-5 ltr:rotate-180" aria-hidden="true" />
          </button>
          <button type="button" class="h-10 px-3 text-sm font-semibold hover:bg-gray-200 dark:hover:bg-gray-700" data-testid="planner-today" @click="go({ date: new Date() })">
            {{ t("studio.planner.today") }}
          </button>
          <button type="button" class="flex h-10 w-10 items-center justify-center hover:bg-gray-200 dark:hover:bg-gray-700" :aria-label="t('studio.planner.next')" data-testid="planner-next" @click="step(1)">
            <ChevronLeft class="h-5 w-5 ltr:rotate-180" aria-hidden="true" />
          </button>
        </div>

        <div class="relative" data-popover-root>
          <button
            type="button"
            class="inline-flex h-10 items-center gap-1.5 rounded-xl bg-gray-100 px-3 text-sm font-semibold hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700"
            aria-haspopup="menu"
            :aria-expanded="pop === 'view'"
            :aria-label="`${t('studio.planner.view')}: ${view === 'month' ? t('studio.planner.month') : t('studio.planner.week')}`"
            data-testid="planner-view"
            @click="toggle('view')"
          >
            {{ view === "month" ? t("studio.planner.month") : t("studio.planner.week") }}
            <ChevronDown class="h-4 w-4" aria-hidden="true" />
          </button>
          <div v-if="pop === 'view'" role="menu" class="popover absolute end-0 top-full z-20 mt-2 w-40 p-1.5">
            <button
              v-for="v in (['month', 'week'] as const)"
              :key="v"
              type="button"
              role="menuitemradio"
              :aria-checked="view === v"
              class="btn-ghost w-full justify-start"
              :data-testid="`planner-view-${v}`"
              @click="pop = null; go({ view: v })"
            >
              {{ v === "month" ? t("studio.planner.month") : t("studio.planner.week") }}
            </button>
          </div>
        </div>

        <div class="relative" data-popover-root>
          <button
            type="button"
            class="flex h-10 w-10 items-center justify-center rounded-xl bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700"
            :class="(!showScheduled || !showPublished) && 'ring-2 ring-brand-500'"
            aria-haspopup="dialog"
            :aria-expanded="pop === 'filter'"
            :aria-label="t('studio.planner.filter')"
            :title="t('studio.planner.filter')"
            data-testid="planner-filter"
            @click="toggle('filter')"
          >
            <SlidersHorizontal class="h-5 w-5" aria-hidden="true" />
          </button>
          <div v-if="pop === 'filter'" role="dialog" :aria-label="t('studio.planner.filter')" class="popover absolute end-0 top-full z-20 mt-2 w-60 space-y-1 p-3">
            <label class="flex items-center gap-2 rounded-lg p-1.5 text-sm font-semibold hover:bg-gray-50 dark:hover:bg-gray-800">
              <input v-model="showScheduled" type="checkbox" class="h-4 w-4 accent-brand-600" data-testid="planner-filter-scheduled" />
              <CalendarClock class="h-4 w-4 text-accent-500" aria-hidden="true" />{{ t("studio.planner.showScheduled") }}
            </label>
            <label class="flex items-center gap-2 rounded-lg p-1.5 text-sm font-semibold hover:bg-gray-50 dark:hover:bg-gray-800">
              <input v-model="showPublished" type="checkbox" class="h-4 w-4 accent-brand-600" data-testid="planner-filter-published" />
              <CheckCircle2 class="h-4 w-4 text-brand-500" aria-hidden="true" />{{ t("studio.planner.showPublished") }}
            </label>
          </div>
        </div>
      </div>
    </header>

    <p class="sr-only">{{ t("studio.planner.dragHint") }}</p>
    <p v-if="truncated" class="mx-3 mb-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-200 sm:mx-5">{{ t("studio.planner.truncated") }}</p>

    <ErrorState v-if="failed" @retry="load" />
    <section v-else class="flex flex-1 flex-col" :aria-label="t('studio.planner.calendarLabel')" :aria-busy="loading" data-testid="planner-grid" :data-view="view">
      <!-- Weekday names -->
      <div class="grid grid-cols-7 border-b border-gray-200 text-center text-xs font-semibold text-gray-600 dark:border-gray-800 dark:text-gray-300 sm:text-sm" aria-hidden="true">
        <span v-for="(w, i) in weekdays" :key="i" class="truncate px-1 py-2">{{ w }}</span>
      </div>

      <div class="grid flex-1" :style="{ gridTemplateRows: `repeat(${weeks.length}, minmax(${view === 'week' ? '22rem' : '6.5rem'}, 1fr))` }">
        <div v-for="(week, wi) in weeks" :key="wi" class="grid grid-cols-7 border-b border-gray-200 last:border-b-0 dark:border-gray-800">
          <div
            v-for="d in week"
            :key="dayKey(d)"
            class="group relative flex min-w-0 flex-col gap-1 border-e border-gray-200 p-1 transition last:border-e-0 dark:border-gray-800 sm:p-1.5"
            :class="[
              dayKey(d) === todayKey && 'bg-brand-50 dark:bg-brand-950/40',
              !inMonth(d) && 'bg-gray-50 dark:bg-gray-950/60',
              over === dayKey(d) && 'ring-2 ring-inset ring-brand-500',
              dayKey(d) === dayKey(selected) && 'max-sm:outline max-sm:outline-2 max-sm:-outline-offset-2 max-sm:outline-brand-400',
            ]"
            :data-day="dayKey(d)"
            @click="selected = d"
            @dragover="onDragOver($event, d)"
            @dragleave="over = over === dayKey(d) ? null : over"
            @drop="onDrop($event, d)"
          >
            <div class="flex items-center justify-between gap-1">
              <span
                class="flex h-6 min-w-6 items-center justify-center rounded-full px-1 text-xs font-semibold sm:text-sm"
                :class="dayKey(d) === todayKey ? 'bg-brand-600 text-white' : inMonth(d) ? 'text-gray-700 dark:text-gray-200' : 'text-gray-400 dark:text-gray-600'"
              >
                <span aria-hidden="true">{{ dayNumber(d) }}</span>
                <span class="sr-only">{{ fullDate(d) }}</span>
              </span>
              <button
                v-if="canScheduleOn(d)"
                type="button"
                class="hidden h-6 w-6 items-center justify-center rounded-full text-gray-500 opacity-0 transition hover:bg-brand-600 hover:text-white focus:opacity-100 group-hover:opacity-100 sm:flex"
                :aria-label="t('studio.planner.scheduleOn', { date: fullDate(d) })"
                data-testid="planner-add"
                @click.stop="scheduleOn(d)"
              >
                <Plus class="h-4 w-4" aria-hidden="true" />
              </button>
            </div>

            <ul class="flex min-w-0 flex-col gap-1">
              <li v-for="p in (view === 'month' ? postsOn(d).slice(0, MONTH_CHIPS) : postsOn(d))" :key="p.id" class="min-w-0">
                <button
                  type="button"
                  class="flex w-full min-w-0 items-center gap-1.5 rounded-lg border bg-white px-1 py-1 text-start text-xs font-semibold text-gray-800 transition hover:border-brand-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:bg-gray-900 dark:text-gray-100 sm:px-1.5 sm:text-sm"
                  :class="[
                    p.state === 'scheduled' ? 'cursor-grab border-gray-300 dark:border-gray-600' : 'border-gray-200 dark:border-gray-800',
                    dragging === p.id && 'opacity-50',
                  ]"
                  :draggable="p.state === 'scheduled'"
                  :aria-label="chipLabel(p)"
                  :data-post-id="p.id"
                  :data-state="p.state"
                  data-testid="planner-chip"
                  @click.stop="opened = p"
                  @dragstart="onDragStart($event, p)"
                  @dragend="onDragEnd"
                >
                  <StudioPostThumb :type="p.type" :media-ids="p.media_ids" :size="22" />
                  <span class="hidden min-w-0 flex-1 truncate sm:inline" dir="auto">
                    <template v-if="view === 'week'">{{ time(p) }} · {{ excerpt(p) }}</template>
                    <template v-else>{{ time(p) }}</template>
                  </span>
                  <CalendarClock v-if="p.state === 'scheduled'" class="hidden h-3.5 w-3.5 shrink-0 text-accent-500 md:block" aria-hidden="true" />
                </button>
              </li>
            </ul>
            <button
              v-if="view === 'month' && postsOn(d).length > MONTH_CHIPS"
              type="button"
              class="truncate rounded px-1 text-start text-xs font-semibold text-gray-600 hover:underline dark:text-gray-300"
              data-testid="planner-more"
              :aria-label="t('studio.planner.more', { count: postsOn(d).length - MONTH_CHIPS })"
              @click.stop="go({ view: 'week', date: d })"
            >
              <span class="hidden sm:inline">{{ t("studio.planner.more", { count: postsOn(d).length - MONTH_CHIPS }) }}</span>
              <span class="sm:hidden">{{ t("studio.planner.moreShort", { count: postsOn(d).length - MONTH_CHIPS }) }}</span>
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- Phones: the selected day's posts in full under the grid. -->
    <section class="border-t border-gray-200 p-3 dark:border-gray-800 sm:hidden" :aria-label="fullDate(selected)" data-testid="planner-agenda">
      <div class="flex items-center justify-between gap-2">
        <h2 class="text-sm font-bold">{{ fullDate(selected) }}</h2>
        <button v-if="canScheduleOn(selected)" type="button" class="btn-soft px-3 py-1.5" :aria-label="t('studio.planner.scheduleOn', { date: fullDate(selected) })" @click="scheduleOn(selected)">
          <Plus class="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <ul class="mt-2 space-y-1.5">
        <li v-for="p in agendaPosts" :key="p.id">
          <button type="button" class="flex w-full items-center gap-2 rounded-xl border border-gray-200 p-2 text-start text-sm dark:border-gray-800" @click="opened = p">
            <StudioPostThumb :type="p.type" :media-ids="p.media_ids" :size="32" />
            <span class="min-w-0 flex-1">
              <span class="block truncate font-semibold" dir="auto">{{ excerpt(p) }}</span>
              <span class="block text-xs text-gray-500 dark:text-gray-400">
                {{ time(p) }} · {{ p.state === "scheduled" ? t("studio.planner.scheduled") : t("studio.planner.published") }}
              </span>
            </span>
          </button>
        </li>
      </ul>
      <button
        v-if="!agendaAll && selectedPosts.length > AGENDA_CAP"
        type="button"
        class="btn-ghost mt-2 w-full"
        data-testid="planner-agenda-all"
        @click="agendaAll = true"
      >
        {{ t("studio.planner.agendaAll", { count: selectedPosts.length }) }}
      </button>
    </section>

    <PlannerPostDialog
      v-if="opened"
      :post="opened"
      :zone="zoneText"
      :busy="busy"
      @close="opened = null"
      @edit="edit"
      @reschedule="reschedule"
      @publish="publishNow"
      @remove="remove"
    />
  </div>
</template>
