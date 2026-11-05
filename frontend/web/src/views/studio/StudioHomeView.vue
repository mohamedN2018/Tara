<script setup lang="ts">
import { Bookmark, CalendarClock, FileText, MessageCircle, Newspaper, Repeat2, ThumbsUp } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import EngagementChart from "@/components/studio/EngagementChart.vue";
import StudioPostThumb from "@/components/studio/StudioPostThumb.vue";
import { useStudioComposer } from "@/components/studio/studioComposer";
import { addDays } from "@/lib/planner";
import { CHART_METRICS, type ChartMetric, lastDays, metricOf, spanDays } from "@/lib/studioRange";
import type { ComposerPost } from "@/services/composer";
import { timeZoneName } from "@/services/composer";
import { type StudioDaily, type StudioSummary, studioService } from "@/services/studio";

defineOptions({ name: "StudioHomeView" });

const { t } = useI18n();

const summary = ref<StudioSummary | null>(null);
const upcoming = ref<ComposerPost[]>([]);
const loading = ref(true);
const failed = ref(false);

async function load() {
  loading.value = !summary.value;
  failed.value = false;
  try {
    const now = new Date();
    const [s, cal] = await Promise.all([
      studioService.summary(),
      studioService.calendar(now.toISOString(), addDays(now, 42).toISOString()),
    ]);
    summary.value = s;
    upcoming.value = cal.data.filter((p) => p.state === "scheduled").slice(0, 5);
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const stats = computed(() => {
  const s = summary.value;
  if (!s) return [];
  return [
    { key: "posts", value: s.posts, icon: Newspaper },
    { key: "reactions", value: s.reactions, icon: ThumbsUp },
    { key: "comments", value: s.comments, icon: MessageCircle },
    { key: "shares", value: s.shares, icon: Repeat2 },
    { key: "saves", value: s.saves, icon: Bookmark },
  ];
});

const { locale } = useI18n();
const fmtNumber = (n: number) => new Intl.NumberFormat(locale.value).format(n);
const fmtTime = (iso: string) =>
  new Intl.DateTimeFormat(locale.value, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }).format(new Date(iso));
const excerpt = (p: ComposerPost) => (p.body || "").trim() || t("studio.library.noText");

watch(useStudioComposer().version, load);

// ---- engagement over time (real per-day numbers from /posts/studio/daily/) -------------
const PRESETS = [7, 28, 90] as const;
const MAX_SPAN = 366;
const preset = ref<number | "custom">(28);
const range = ref(lastDays(28));
const metric = ref<ChartMetric>("engagement");
const daily = ref<StudioDaily | null>(null);
const dailyLoading = ref(false);
const dailyFailed = ref(false);
const rangeError = computed(() => {
  const n = spanDays(range.value.from, range.value.to);
  if (!n) return t("polish.studio.rangeInvalid");
  if (n > MAX_SPAN) return t("polish.studio.rangeTooLong", { max: MAX_SPAN });
  return "";
});

let dailySeq = 0;
async function loadDaily() {
  if (rangeError.value) return;
  const mine = ++dailySeq;
  dailyLoading.value = true;
  dailyFailed.value = false;
  try {
    const data = await studioService.daily(range.value.from, range.value.to, timeZoneName());
    if (mine === dailySeq) daily.value = data;
  } catch {
    if (mine === dailySeq) dailyFailed.value = true;
  } finally {
    if (mine === dailySeq) dailyLoading.value = false;
  }
}
function pickPreset(days: number) {
  preset.value = days;
  range.value = lastDays(days);
}
watch(range, loadDaily, { deep: true });
onMounted(loadDaily);

const points = computed(() => (daily.value?.days ?? []).map((d) => ({ date: d.date, value: metricOf(d, metric.value) })));
const metricTotal = computed(() => points.value.reduce((s, p) => s + p.value, 0));
const metricLabel = computed(() => t(`polish.studio.metrics.${metric.value}`));
</script>

<template>
    <div class="mx-auto max-w-5xl space-y-4" data-testid="studio-home">
      <header class="card p-5">
        <h1 class="text-2xl font-extrabold tracking-tight text-gray-900 dark:text-white">{{ t("studio.home.title") }}</h1>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t("studio.home.subtitle") }}</p>
      </header>

      <LoadingSkeleton v-if="loading" />
      <ErrorState v-else-if="failed" @retry="load" />
      <template v-else-if="summary">
        <section :aria-label="t('studio.home.statsLabel')">
          <ul class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5" data-testid="studio-stats">
            <li v-for="s in stats" :key="s.key" class="card p-4" :data-stat="s.key">
              <div class="flex items-center gap-2 text-sm font-semibold text-gray-500 dark:text-gray-400">
                <component :is="s.icon" class="h-4 w-4 text-brand-500" aria-hidden="true" />
                {{ t(`studio.home.stats.${s.key}`) }}
              </div>
              <p class="mt-2 text-2xl font-extrabold text-gray-900 dark:text-white" data-testid="studio-stat-value">{{ fmtNumber(s.value) }}</p>
            </li>
          </ul>
        </section>

        <section class="card p-4" aria-labelledby="studio-trend" data-testid="studio-trend">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 id="studio-trend" class="section-title">{{ t("polish.studio.trendTitle") }}</h2>
              <p class="mt-0.5 text-xs text-gray-600 dark:text-gray-400">{{ t("polish.studio.trendLead") }}</p>
            </div>
            <div class="flex flex-wrap items-center gap-1" role="group" :aria-label="t('polish.studio.rangeLabel')">
              <button
                v-for="d in PRESETS"
                :key="d"
                type="button"
                class="rounded-full px-3 py-1 text-sm font-semibold transition"
                :class="preset === d ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-800 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700'"
                :aria-pressed="preset === d"
                :data-testid="`studio-range-${d}`"
                @click="pickPreset(d)"
              >
                {{ t("polish.studio.lastDays", { n: d }, d) }}
              </button>
              <button
                type="button"
                class="rounded-full px-3 py-1 text-sm font-semibold transition"
                :class="preset === 'custom' ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-800 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700'"
                :aria-pressed="preset === 'custom'"
                data-testid="studio-range-custom"
                @click="preset = 'custom'"
              >
                {{ t("polish.studio.custom") }}
              </button>
            </div>
          </div>
          <div v-if="preset === 'custom'" class="mt-3 flex flex-wrap items-end gap-3" data-testid="studio-range-dates">
            <label class="text-sm">
              <span class="mb-1 block font-semibold text-gray-700 dark:text-gray-300">{{ t("polish.studio.from") }}</span>
              <input v-model.lazy="range.from" type="date" class="input w-auto py-1.5" dir="ltr" :max="range.to" data-testid="studio-range-from" />
            </label>
            <label class="text-sm">
              <span class="mb-1 block font-semibold text-gray-700 dark:text-gray-300">{{ t("polish.studio.to") }}</span>
              <input v-model.lazy="range.to" type="date" class="input w-auto py-1.5" dir="ltr" :min="range.from" data-testid="studio-range-to" />
            </label>
            <p v-if="rangeError" class="text-sm text-red-700 dark:text-red-400" role="alert">{{ rangeError }}</p>
          </div>

          <div class="mt-3 flex gap-1 overflow-x-auto" role="radiogroup" :aria-label="t('polish.studio.metricLabel')">
            <button
              v-for="m in CHART_METRICS"
              :key="m"
              type="button"
              role="radio"
              class="shrink-0 rounded-lg px-3 py-1.5 text-start text-sm transition"
              :class="metric === m ? 'bg-brand-50 font-semibold text-brand-800 ring-1 ring-brand-300 dark:bg-brand-950/50 dark:text-brand-100 dark:ring-brand-800' : 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'"
              :aria-checked="metric === m"
              :data-testid="`studio-metric-${m}`"
              @click="metric = m"
            >
              <span class="block">{{ t(`polish.studio.metrics.${m}`) }}</span>
              <span v-if="daily" class="block text-base font-extrabold tabular-nums">{{ fmtNumber(daily.days.reduce((s, d) => s + metricOf(d, m), 0)) }}</span>
            </button>
          </div>

          <div class="mt-3">
            <LoadingSkeleton v-if="dailyLoading && !daily" :rows="1" />
            <ErrorState v-else-if="dailyFailed" @retry="loadDaily" />
            <template v-else-if="daily">
              <p class="sr-only" aria-live="polite">{{ t("polish.studio.totalLive", { metric: metricLabel, total: fmtNumber(metricTotal) }) }}</p>
              <EngagementChart :points="points" :label="metricLabel" />
              <p v-if="metric === 'views'" class="mt-1 text-xs text-gray-600 dark:text-gray-400">{{ t("polish.studio.viewsNote") }}</p>
            </template>
          </div>
        </section>

        <div class="grid gap-4 lg:grid-cols-2">
          <section class="card p-4" aria-labelledby="studio-top">
            <h2 id="studio-top" class="section-title">{{ t("studio.home.topPosts") }}</h2>
            <ul v-if="summary.top_posts.length" class="mt-3 divide-y divide-gray-100 dark:divide-gray-800" data-testid="studio-top-posts">
              <li v-for="p in summary.top_posts" :key="p.id">
                <RouterLink :to="`/posts/${p.id}`" class="flex items-center gap-3 rounded-xl px-1 py-2.5 hover:bg-gray-50 dark:hover:bg-gray-800/60">
                  <StudioPostThumb :type="p.type" :media-ids="p.media_ids" :size="44" />
                  <span class="min-w-0 flex-1">
                    <span class="block truncate text-sm font-semibold text-gray-900 dark:text-gray-100" dir="auto">{{ excerpt(p) }}</span>
                    <span class="block text-xs text-gray-500 dark:text-gray-400">
                      {{ t("studio.home.interactions", { reactions: fmtNumber(p.reaction_count), comments: fmtNumber(p.comment_count), shares: fmtNumber(p.share_count) }) }}
                    </span>
                  </span>
                </RouterLink>
              </li>
            </ul>
            <p v-else class="mt-3 text-sm text-gray-500 dark:text-gray-400">{{ t("studio.home.topEmpty") }}</p>
          </section>

          <section class="card p-4" aria-labelledby="studio-upcoming">
            <div class="flex items-center justify-between gap-2">
              <h2 id="studio-upcoming" class="section-title">{{ t("studio.home.upcoming") }}</h2>
              <RouterLink to="/studio/planner" class="text-sm font-semibold text-brand-700 hover:underline dark:text-brand-300">{{ t("studio.home.openPlanner") }}</RouterLink>
            </div>
            <ul v-if="upcoming.length" class="mt-3 divide-y divide-gray-100 dark:divide-gray-800" data-testid="studio-upcoming">
              <li v-for="p in upcoming" :key="p.id" class="flex items-center gap-3 py-2.5">
                <StudioPostThumb :type="p.type" :media-ids="p.media_ids" :size="36" />
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-sm font-semibold text-gray-900 dark:text-gray-100" dir="auto">{{ excerpt(p) }}</span>
                  <span class="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
                    <CalendarClock class="h-3.5 w-3.5" aria-hidden="true" />
                    {{ fmtTime(p.publish_at!) }}
                  </span>
                </span>
              </li>
            </ul>
            <p v-else class="mt-3 text-sm text-gray-500 dark:text-gray-400">{{ t("studio.home.upcomingEmpty") }}</p>
          </section>
        </div>

        <section class="grid grid-cols-2 gap-3">
          <RouterLink :to="{ path: '/studio/library', query: { tab: 'drafts' } }" class="card card-hover flex items-center gap-3 p-4" data-testid="studio-drafts-count">
            <FileText class="h-6 w-6 text-brand-500" aria-hidden="true" />
            <span class="flex-1 text-sm font-semibold">{{ t("studio.home.drafts") }}</span>
            <span class="text-xl font-extrabold">{{ fmtNumber(summary.drafts) }}</span>
          </RouterLink>
          <RouterLink :to="{ path: '/studio/library', query: { tab: 'scheduled' } }" class="card card-hover flex items-center gap-3 p-4" data-testid="studio-scheduled-count">
            <CalendarClock class="h-6 w-6 text-accent-500" aria-hidden="true" />
            <span class="flex-1 text-sm font-semibold">{{ t("studio.home.scheduled") }}</span>
            <span class="text-xl font-extrabold">{{ fmtNumber(summary.scheduled) }}</span>
          </RouterLink>
        </section>
      </template>
    </div>
</template>
