<script setup lang="ts">
import { Activity, Scale, ShieldAlert } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import FeatureFlagsPanel from "@/components/admin/FeatureFlagsPanel.vue";
import RolesPanel from "@/components/admin/RolesPanel.vue";
import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { relativeTime } from "@/lib/format";
import { adminService, type Appeal, type HealthOverview, type ModerationCase } from "@/services/admin";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";

const { t, te } = useI18n();
const toasts = useToastStore();
const auth = useAuthStore();
const isAdmin = computed(() => auth.roles.includes("admin"));

const health = ref<HealthOverview | null>(null);
const cases = ref<ModerationCase[]>([]);
const loading = ref(true);
const casesError = ref(false);
const acting = ref("");
const appeals = ref<Appeal[]>([]);
const appealsCursor = ref<string | null>(null);
const appealsError = ref(false);
const loadingMoreAppeals = ref(false);

/** Translate a backend enum value, showing it raw if a new one appears. */
function enumLabel(group: string, value: string): string {
  const key = `admin.${group}.${value}`;
  return te(key) ? t(key) : value;
}

async function load() {
  loading.value = true;
  casesError.value = false;
  try {
    appealsError.value = false;
    const [overview, queue, appealPage] = await Promise.all([
      adminService.health().catch(() => null),
      adminService.cases().catch(() => {
        casesError.value = true;
        return [];
      }),
      adminService.appeals("open").catch(() => {
        appealsError.value = true;
        return null;
      }),
    ]);
    health.value = overview;
    cases.value = queue;
    appeals.value = appealPage?.data ?? [];
    appealsCursor.value = appealPage?.page.next_cursor ?? null;
  } finally {
    loading.value = false;
  }
}

async function act(id: string, action: string) {
  if (acting.value) return;
  acting.value = id;
  try {
    await adminService.actionCase(id, action);
    cases.value = cases.value.filter((c) => c.id !== id);
    toasts.success(t("admin.actionDone"));
  } catch (e) {
    toasts.error(e); // The case stays in the queue: nothing happened to it.
  } finally {
    acting.value = "";
  }
}

async function moreAppeals() {
  if (!appealsCursor.value || loadingMoreAppeals.value) return;
  loadingMoreAppeals.value = true;
  try {
    const page = await adminService.appeals("open", appealsCursor.value);
    const known = new Set(appeals.value.map((a) => a.id));
    appeals.value = [...appeals.value, ...page.data.filter((a) => !known.has(a.id))];
    appealsCursor.value = page.page.next_cursor;
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMoreAppeals.value = false;
  }
}

async function resolveAppeal(id: string, status: "upheld" | "overturned") {
  if (acting.value) return;
  acting.value = id;
  try {
    await adminService.resolveAppeal(id, status);
    appeals.value = appeals.value.filter((a) => a.id !== id);
    toasts.success(t("admin.appeals.done"));
  } catch (e) {
    toasts.error(e); // The appeal stays open: nothing was decided.
  } finally {
    acting.value = "";
  }
}

onMounted(load);
</script>

<template>
  <AppShell>
    <h1 class="mb-4 text-xl font-bold">{{ t("nav.admin") }}</h1>

    <LoadingSkeleton v-if="loading" :rows="2" />
    <template v-else>
      <!-- Service health overview -->
      <section class="card mb-6 p-4">
        <h2 class="mb-3 flex items-center gap-2 font-semibold">
          <Activity class="h-5 w-5 text-brand-600 dark:text-brand-300" /> {{ t("admin.serviceHealth") }}
          <span
            v-if="health"
            class="ms-auto rounded-full px-2 py-0.5 text-xs font-medium"
            :class="
              health.overall === 'ok'
                ? 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300'
                : 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300'
            "
          >
            {{ enumLabel("overall", health.overall) }}
          </span>
        </h2>
        <div v-if="health" class="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <div
            v-for="s in health.services"
            :key="s.service"
            class="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2 text-sm dark:border-gray-800"
          >
            <span class="truncate">{{ s.service }}</span>
            <span
              class="h-2.5 w-2.5 shrink-0 rounded-full"
              :class="s.status === 'ready' ? 'bg-green-500' : 'bg-red-500'"
              :title="enumLabel('health', s.status)"
              role="img"
              :aria-label="enumLabel('health', s.status)"
            />
          </div>
        </div>
        <EmptyState v-else>{{ t("admin.healthUnavailable") }}</EmptyState>
      </section>

      <template v-if="isAdmin">
        <RolesPanel />
        <FeatureFlagsPanel />
      </template>

      <!-- Moderation queue (cases) -->
      <h2 class="mb-2 flex items-center gap-2 font-semibold">
        <ShieldAlert class="h-5 w-5 text-brand-600 dark:text-brand-300" /> {{ t("admin.moderationQueue") }}
      </h2>
      <ErrorState v-if="casesError" @retry="load" />
      <EmptyState v-else-if="cases.length === 0">{{ t("admin.queueEmpty") }}</EmptyState>
      <ul v-else class="space-y-2">
        <li v-for="c in cases" :key="c.id" class="card flex items-center gap-3 p-3">
          <span class="min-w-0 flex-1">
            <span class="block text-sm font-medium">
              {{ enumLabel("targets", c.target_type) }} · {{ t("admin.reportsCount", c.report_count) }} · {{ enumLabel("states", c.state) }}
            </span>
            <span class="block truncate text-xs text-gray-500 dark:text-gray-400">{{ c.target_id }}</span>
          </span>
          <button class="btn-ghost text-sm" :disabled="acting === c.id" @click="act(c.id, 'dismiss')">{{ t("admin.dismiss") }}</button>
          <button class="btn-primary text-sm" :disabled="acting === c.id" @click="act(c.id, 'remove')">{{ t("admin.remove") }}</button>
        </li>
      </ul>

      <!-- Appeals against moderation decisions -->
      <h2 class="mb-2 mt-6 flex items-center gap-2 font-semibold">
        <Scale class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("admin.appeals.title") }}
      </h2>
      <ErrorState v-if="appealsError" @retry="load" />
      <EmptyState v-else-if="appeals.length === 0">{{ t("admin.appeals.empty") }}</EmptyState>
      <ul v-else class="space-y-2" data-testid="appeals">
        <li v-for="a in appeals" :key="a.id" class="card space-y-2 p-3">
          <p class="text-sm font-medium">
            {{ enumLabel("targets", a.target_type) }} ·
            <time :datetime="a.created_at">{{ relativeTime(a.created_at) }}</time>
          </p>
          <p class="truncate text-xs text-gray-500 dark:text-gray-400" dir="ltr">{{ a.target_id }}</p>
          <p class="whitespace-pre-wrap break-words text-sm" dir="auto">{{ a.text }}</p>
          <div class="flex justify-end gap-2">
            <button class="btn-ghost text-sm" :disabled="acting === a.id" @click="resolveAppeal(a.id, 'upheld')">
              {{ t("admin.appeals.uphold") }}
            </button>
            <button class="btn-primary text-sm" :disabled="acting === a.id" @click="resolveAppeal(a.id, 'overturned')">
              {{ t("admin.appeals.overturn") }}
            </button>
          </div>
        </li>
      </ul>
      <div v-if="appealsCursor && !appealsError" class="mt-2 flex justify-center">
        <button class="btn-ghost text-sm" :disabled="loadingMoreAppeals" @click="moreAppeals">
          {{ loadingMoreAppeals ? t("states.loading") : t("feed.loadMore") }}
        </button>
      </div>
    </template>
  </AppShell>
</template>
