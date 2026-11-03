<script setup lang="ts">
import { Activity, ShieldAlert } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import FeatureFlagsPanel from "@/components/admin/FeatureFlagsPanel.vue";
import RolesPanel from "@/components/admin/RolesPanel.vue";
import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { adminService, type HealthOverview, type ModerationCase } from "@/services/admin";
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

/** Translate a backend enum value, showing it raw if a new one appears. */
function enumLabel(group: string, value: string): string {
  const key = `admin.${group}.${value}`;
  return te(key) ? t(key) : value;
}

async function load() {
  loading.value = true;
  casesError.value = false;
  try {
    const [overview, queue] = await Promise.all([
      adminService.health().catch(() => null),
      adminService.cases().catch(() => {
        casesError.value = true;
        return [];
      }),
    ]);
    health.value = overview;
    cases.value = queue;
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
          <Activity class="h-5 w-5 text-brand-600" /> {{ t("admin.serviceHealth") }}
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
        <ShieldAlert class="h-5 w-5 text-brand-600" /> {{ t("admin.moderationQueue") }}
      </h2>
      <ErrorState v-if="casesError" @retry="load" />
      <EmptyState v-else-if="cases.length === 0">{{ t("admin.queueEmpty") }}</EmptyState>
      <ul v-else class="space-y-2">
        <li v-for="c in cases" :key="c.id" class="card flex items-center gap-3 p-3">
          <span class="min-w-0 flex-1">
            <span class="block text-sm font-medium">
              {{ enumLabel("targets", c.target_type) }} · {{ t("admin.reportsCount", c.report_count) }} · {{ enumLabel("states", c.state) }}
            </span>
            <span class="block truncate text-xs text-gray-500">{{ c.target_id }}</span>
          </span>
          <button class="btn-ghost text-sm" :disabled="acting === c.id" @click="act(c.id, 'dismiss')">{{ t("admin.dismiss") }}</button>
          <button class="btn-primary text-sm" :disabled="acting === c.id" @click="act(c.id, 'remove')">{{ t("admin.remove") }}</button>
        </li>
      </ul>
    </template>
  </AppShell>
</template>
