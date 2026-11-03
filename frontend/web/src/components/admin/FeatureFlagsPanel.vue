<script setup lang="ts">
import { Flag } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import { adminService, type FeatureFlag } from "@/services/admin";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
const toasts = useToastStore();
const flags = ref<FeatureFlag[]>([]);
const error = ref(false);
const newKey = ref("");

async function load() {
  error.value = false;
  try {
    flags.value = await adminService.flags();
  } catch {
    error.value = true;
  }
}

async function save(flag: FeatureFlag) {
  try {
    await adminService.setFlag(flag);
    toasts.success(t("settings.saved"));
  } catch (e) {
    toasts.error(e);
    void load();
  }
}

async function add() {
  const key = newKey.value.trim();
  if (!key) return;
  const flag: FeatureFlag = { key, enabled: false, rollout_pct: 0, description: "" };
  try {
    await adminService.setFlag(flag);
    newKey.value = "";
    await load();
  } catch (e) {
    toasts.error(e);
  }
}

onMounted(load);
</script>

<template>
  <section class="mb-6">
    <h2 class="mb-2 flex items-center gap-2 font-semibold">
      <Flag class="h-5 w-5 text-brand-600" /> {{ t("admin.featureFlags") }}
    </h2>
    <ErrorState v-if="error" @retry="load" />
    <template v-else>
      <EmptyState v-if="!flags.length">{{ t("admin.noFlags") }}</EmptyState>
      <ul v-else class="space-y-2" data-testid="feature-flags">
        <li v-for="flag in flags" :key="flag.key" class="card flex flex-wrap items-center gap-3 p-3">
          <span class="min-w-0 flex-1 truncate text-sm font-medium" dir="ltr">{{ flag.key }}</span>
          <label class="flex items-center gap-1.5 text-sm">
            <input v-model.number="flag.rollout_pct" class="input w-20 py-1" type="number" min="0" max="100" dir="ltr" :aria-label="t('admin.rollout', { key: flag.key })" @change="save(flag)" />
            %
          </label>
          <label class="flex items-center gap-1.5 text-sm">
            <input v-model="flag.enabled" type="checkbox" class="h-5 w-5 accent-brand-600" :aria-label="t('admin.flagEnabled', { key: flag.key })" @change="save(flag)" />
            {{ t("admin.enabled") }}
          </label>
        </li>
      </ul>
      <form class="mt-2 flex gap-2" @submit.prevent="add">
        <input v-model="newKey" class="input" dir="ltr" maxlength="80" pattern="[a-z0-9_.\-]+" :aria-label="t('admin.newFlag')" :placeholder="t('admin.newFlag')" />
        <button class="btn-ghost shrink-0" :disabled="!newKey.trim()">{{ t("messages.add") }}</button>
      </form>
    </template>
  </section>
</template>
