<script setup lang="ts">
import { Activity, ShieldAlert } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { adminService, type HealthOverview, type ModerationCase } from "@/services/admin";

const { t } = useI18n();

const health = ref<HealthOverview | null>(null);
const cases = ref<ModerationCase[]>([]);
const loading = ref(true);

async function load() {
  loading.value = true;
  try {
    [health.value, cases.value] = await Promise.all([
      adminService.health().catch(() => null),
      adminService.cases().catch(() => []),
    ]);
  } finally {
    loading.value = false;
  }
}

async function act(id: string, action: string) {
  await adminService.actionCase(id, action).catch(() => {});
  cases.value = cases.value.filter((c) => c.id !== id);
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
          <Activity class="h-5 w-5 text-brand-600" /> Service health
          <span
            v-if="health"
            class="ms-auto rounded-full px-2 py-0.5 text-xs font-medium"
            :class="
              health.overall === 'ok'
                ? 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300'
                : 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300'
            "
          >
            {{ health.overall }}
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
              :title="s.status"
            />
          </div>
        </div>
        <EmptyState v-else>Service health unavailable.</EmptyState>
      </section>

      <!-- Moderation queue (cases) -->
      <h2 class="mb-2 flex items-center gap-2 font-semibold">
        <ShieldAlert class="h-5 w-5 text-brand-600" /> Moderation queue
      </h2>
      <EmptyState v-if="cases.length === 0">{{ t("notifications.empty") }}</EmptyState>
      <ul v-else class="space-y-2">
        <li v-for="c in cases" :key="c.id" class="card flex items-center gap-3 p-3">
          <span class="min-w-0 flex-1">
            <span class="block text-sm font-medium">
              {{ c.target_type }} · {{ c.report_count }} report(s) · {{ c.state }}
            </span>
            <span class="block truncate text-xs text-gray-500">{{ c.target_id }}</span>
          </span>
          <button class="btn-ghost text-sm" @click="act(c.id, 'dismiss')">Dismiss</button>
          <button class="btn-primary text-sm" @click="act(c.id, 'remove')">Remove</button>
        </li>
      </ul>
    </template>
  </AppShell>
</template>
