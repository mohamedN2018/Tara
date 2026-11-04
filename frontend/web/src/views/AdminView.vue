<script setup lang="ts">
import { Activity, BadgeCheck, ChevronRight, Hand, Scale, ShieldAlert, UserCheck } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import AdminLayout from "@/components/admin/AdminLayout.vue";
import { useAdminLabels } from "@/components/admin/labels";
import EmptyState from "@/components/states/EmptyState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { adminService, type ModerationSummary, type MonitorOverview, PLATFORM_METRICS } from "@/services/admin";
import { useAuthStore } from "@/stores/auth";

/**
 * The console's home: what needs attention (queue counts, linking into the
 * moderation tabs), the platform's numbers and the services' health. Each
 * block needs its own capability; the server enforces the same keys.
 */
const { t, te, locale } = useI18n();
const auth = useAuthStore();
const { metricLabel } = useAdminLabels();

const canMonitor = computed(() => auth.can("admin.monitor.view"));
const canViewCases = computed(() => auth.can("moderation.case.view"));
const canViewAppeals = computed(() => auth.can("moderation.appeal.view"));
const canReviewAds = computed(() => auth.can("ads.review"));

const loading = ref(true);
const summary = ref<ModerationSummary | null>(null);
const monitor = ref<MonitorOverview | null>(null);
const summaryError = ref(false);

const enumLabel = (group: string, value: string) => (te(`admin.${group}.${value}`) ? t(`admin.${group}.${value}`) : value);
const formatNumber = (value: number | null | undefined) =>
  typeof value === "number" ? new Intl.NumberFormat(locale.value).format(value) : "—";

interface Tile {
  id: string;
  label: string;
  value: number | null | undefined;
  to: string | { path: string; query: Record<string, string> };
  icon: unknown;
}

const queueTiles = computed<Tile[]>(() => {
  const s = summary.value;
  const tiles: Tile[] = [];
  if (canViewCases.value) {
    tiles.push(
      { id: "open", label: "safety.console.overview.open", value: s?.open, to: { path: "/admin/moderation", query: { tab: "open" } }, icon: ShieldAlert },
      { id: "in_review", label: "safety.console.overview.inReview", value: s?.in_review, to: { path: "/admin/moderation", query: { tab: "in_review" } }, icon: Hand },
      { id: "mine", label: "safety.console.overview.assignedToMe", value: s?.assigned_to_me, to: { path: "/admin/moderation", query: { tab: "mine" } }, icon: UserCheck },
    );
  }
  if (canViewAppeals.value) {
    tiles.push({ id: "appeals", label: "safety.console.overview.openAppeals", value: s?.open_appeals, to: { path: "/admin/moderation", query: { tab: "appeals" } }, icon: Scale });
  }
  return tiles;
});

const stats = computed(() => {
  const stats = monitor.value?.stats;
  const byMetric = new Map((Array.isArray(stats) ? stats : []).map((s) => [s.metric, s.value]));
  return PLATFORM_METRICS.filter((m) => m !== "open_cases").map((m) => ({ metric: m, value: byMetric.get(m) ?? null }));
});

async function load() {
  loading.value = true;
  summaryError.value = false;
  const [s, m] = await Promise.all([
    canViewCases.value
      ? adminService.moderationSummary().catch(() => {
          summaryError.value = true;
          return null;
        })
      : null,
    canMonitor.value ? adminService.monitor().catch(() => null) : null,
  ]);
  // A malformed answer reads as unavailable rather than breaking the page.
  summary.value = s && typeof s === "object" && !Array.isArray(s) ? s : null;
  monitor.value = m && Array.isArray(m.services) ? m : null;
  loading.value = false;
}

onMounted(load);
</script>

<template>
  <AdminLayout :title="t('admin.sections.overview')" :subtitle="t('safety.console.overview.subtitle')">
    <LoadingSkeleton v-if="loading" :rows="3" />
    <template v-else>
      <!-- What needs attention -->
      <section v-if="queueTiles.length" class="mb-6" aria-labelledby="attention-title">
        <h2 id="attention-title" class="mb-2 font-semibold">{{ t("safety.console.overview.attention") }}</h2>
        <p v-if="summaryError" class="mb-2 text-sm text-amber-700 dark:text-amber-300" role="status">{{ t("safety.console.overview.countsUnavailable") }}</p>
        <ul class="grid grid-cols-2 gap-3 xl:grid-cols-4" data-testid="admin-attention">
          <li v-for="tile in queueTiles" :key="tile.id">
            <RouterLink :to="tile.to" class="card card-hover flex h-full flex-col gap-2 p-4" :data-testid="`admin-tile-${tile.id}`">
              <span class="flex items-center justify-between gap-2 text-sm font-medium text-gray-600 dark:text-gray-300">
                <span class="flex items-center gap-2">
                  <component :is="tile.icon" class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" />
                  {{ t(tile.label) }}
                </span>
                <ChevronRight class="h-4 w-4 shrink-0 rtl:rotate-180" aria-hidden="true" />
              </span>
              <span class="text-3xl font-extrabold tabular-nums" dir="ltr">{{ formatNumber(tile.value) }}</span>
            </RouterLink>
          </li>
        </ul>
      </section>

      <section v-if="canReviewAds" class="mb-6">
        <RouterLink to="/ads/review" class="card card-hover flex items-center gap-3 p-4" data-testid="admin-tile-ads">
          <BadgeCheck class="h-6 w-6 text-brand-600 dark:text-brand-300" aria-hidden="true" />
          <span class="min-w-0 flex-1">
            <span class="block font-semibold">{{ t("safety.console.sections.adReview") }}</span>
            <span class="block text-sm text-gray-500 dark:text-gray-400">{{ t("safety.console.overview.adReviewHint") }}</span>
          </span>
          <ChevronRight class="h-5 w-5 rtl:rotate-180" aria-hidden="true" />
        </RouterLink>
      </section>

      <!-- Platform numbers and service health (the monitor's last poll) -->
      <template v-if="canMonitor">
        <section class="mb-6" aria-labelledby="platform-title">
          <h2 id="platform-title" class="mb-2 flex items-center justify-between font-semibold">
            {{ t("safety.console.overview.platform") }}
            <RouterLink to="/admin/monitor" class="text-sm font-semibold text-brand-700 hover:underline dark:text-brand-300">{{ t("safety.console.overview.openMonitor") }}</RouterLink>
          </h2>
          <ul class="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <li v-for="s in stats" :key="s.metric" class="card p-4">
              <span class="block text-sm text-gray-600 dark:text-gray-300">{{ metricLabel(s.metric) }}</span>
              <span class="mt-1 block text-2xl font-bold tabular-nums" dir="ltr">{{ formatNumber(s.value) }}</span>
            </li>
          </ul>
        </section>

        <section class="card mb-6 p-4" aria-labelledby="health-title">
          <h2 id="health-title" class="mb-3 flex items-center gap-2 font-semibold">
            <Activity class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("admin.serviceHealth") }}
            <span
              v-if="monitor"
              class="ms-auto rounded-full px-2 py-0.5 text-xs font-medium"
              :class="
                monitor.overall === 'ok'
                  ? 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300'
                  : 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300'
              "
            >
              {{ enumLabel("overall", monitor.overall) }}
            </span>
          </h2>
          <div v-if="monitor && monitor.services.length" class="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <div
              v-for="s in monitor.services"
              :key="s.service"
              class="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2 text-sm dark:border-gray-800"
            >
              <span class="truncate" dir="ltr">{{ s.service }}</span>
              <span
                class="h-2.5 w-2.5 shrink-0 rounded-full"
                :class="s.status === 'ready' ? 'bg-green-500' : 'bg-red-500'"
                role="img"
                :aria-label="`${s.service}: ${enumLabel('health', s.status)}`"
              />
            </div>
          </div>
          <EmptyState v-else>{{ t("admin.healthUnavailable") }}</EmptyState>
        </section>
      </template>

      <EmptyState v-if="!queueTiles.length && !canMonitor && !canReviewAds">{{ t("safety.console.overview.nothing") }}</EmptyState>
    </template>
  </AdminLayout>
</template>
