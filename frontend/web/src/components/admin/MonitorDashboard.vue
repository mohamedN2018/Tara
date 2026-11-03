<script setup lang="ts">
import { Activity, BarChart3 } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { relativeTime } from "@/lib/format";
import { useVisiblePolling } from "@/lib/visiblePolling";
import { adminService, PLATFORM_METRICS, type MonitorOverview, type PlatformStat } from "@/services/admin";

import { useAdminLabels } from "./labels";

/** The data comes from the backend's beat task, so polling only reads it. */
const POLL_MS = 15_000;

const { t, te, locale } = useI18n();
const { metricLabel } = useAdminLabels();

const overview = ref<MonitorOverview | null>(null);
const loading = ref(true);
const error = ref(false);

async function refresh() {
  try {
    overview.value = await adminService.monitor();
    error.value = false;
  } catch {
    // Keep the last good numbers on screen; show the error only if there are none.
    error.value = true;
  } finally {
    loading.value = false;
  }
}

useVisiblePolling(refresh, POLL_MS);

const enumLabel = (group: string, value: string) => (te(`admin.${group}.${value}`) ? t(`admin.${group}.${value}`) : value);

/** Every known metric, in a fixed order, even before the first stats poll. */
const stats = computed<PlatformStat[]>(() => {
  const byMetric = new Map((overview.value?.stats ?? []).map((s) => [s.metric, s]));
  const known: PlatformStat[] = PLATFORM_METRICS.map((m) => byMetric.get(m) ?? { metric: m, value: null, updated_at: null });
  const extra = (overview.value?.stats ?? []).filter((s) => !(PLATFORM_METRICS as readonly string[]).includes(s.metric));
  return [...known, ...extra];
});

const formatNumber = (value: number | null) =>
  typeof value === "number" ? new Intl.NumberFormat(locale.value).format(value) : "—";

const dotClass = (status: string) =>
  status === "ready" ? "bg-green-500" : status === "not_ready" ? "bg-amber-500" : status === "unreachable" ? "bg-red-500" : "bg-gray-400";
</script>

<template>
  <section aria-labelledby="monitor-title">
    <h2 id="monitor-title" class="mb-1 flex items-center gap-2 font-semibold">
      <Activity class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("admin.monitor.title") }}
      <span
        v-if="overview"
        class="ms-auto rounded-full px-2 py-0.5 text-xs font-medium"
        :class="
          overview.overall === 'ok'
            ? 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300'
            : 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300'
        "
      >
        {{ enumLabel("overall", overview.overall) }}
      </span>
    </h2>
    <p class="mb-4 text-xs text-gray-500 dark:text-gray-400">{{ t("admin.monitor.refreshHint") }}</p>

    <LoadingSkeleton v-if="loading" :rows="3" />
    <ErrorState v-else-if="error && !overview" @retry="refresh" />
    <template v-else-if="overview">
      <h3 class="mb-2 flex items-center gap-2 text-sm font-semibold">
        <BarChart3 class="h-4 w-4 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("admin.monitor.stats") }}
      </h3>
      <ul class="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5" data-testid="platform-stats">
        <li v-for="s in stats" :key="s.metric" class="card p-3" :data-metric="s.metric">
          <p class="text-xs text-gray-500 dark:text-gray-400">{{ metricLabel(s.metric) }}</p>
          <p class="mt-1 text-2xl font-bold tabular-nums">{{ formatNumber(s.value) }}</p>
          <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
            <time v-if="s.updated_at" :datetime="s.updated_at">{{ t("admin.monitor.updated", { time: relativeTime(s.updated_at) }) }}</time>
            <span v-else>{{ t("admin.monitor.never") }}</span>
          </p>
        </li>
      </ul>

      <h3 class="mb-2 text-sm font-semibold">{{ t("admin.monitor.services") }}</h3>
      <ul class="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3" data-testid="service-tiles">
        <li v-for="s in overview.services" :key="s.service" class="card flex items-start gap-3 p-3" :data-service="s.service">
          <span class="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" :class="dotClass(s.status)" aria-hidden="true" />
          <span class="min-w-0 flex-1">
            <span class="flex items-center justify-between gap-2">
              <span class="truncate font-medium" dir="ltr">{{ s.service }}</span>
              <span class="text-xs">{{ enumLabel("health", s.status) }}</span>
            </span>
            <span class="mt-0.5 flex justify-between gap-2 text-xs text-gray-500 dark:text-gray-400">
              <time v-if="s.checked_at" :datetime="s.checked_at">{{ t("admin.monitor.checked", { time: relativeTime(s.checked_at) }) }}</time>
              <span v-else>{{ t("admin.monitor.never") }}</span>
              <span v-if="s.latency_ms !== null">{{ t("admin.monitor.latency", { ms: s.latency_ms }) }}</span>
            </span>
          </span>
        </li>
      </ul>
      <p v-if="error" class="mt-3 text-xs text-amber-700 dark:text-amber-300" role="status">{{ t("admin.monitor.unavailable") }}</p>
    </template>
  </section>
</template>
