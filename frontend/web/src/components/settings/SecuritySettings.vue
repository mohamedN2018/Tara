<script setup lang="ts">
import { ShieldCheck } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { identityService, type AuthProviders, type SecurityOverview } from "@/services/identity";

import ChangeEmailForm from "./ChangeEmailForm.vue";
import ChangePasswordForm from "./ChangePasswordForm.vue";
import LinkedAccounts from "./LinkedAccounts.vue";

const { t } = useI18n();

const overview = ref<SecurityOverview | null>(null);
const providers = ref<AuthProviders | null>(null);
const loading = ref(true);
const failed = ref(false);

async function load() {
  loading.value = true;
  failed.value = false;
  try {
    [overview.value, providers.value] = await Promise.all([
      identityService.security(),
      identityService.providers(),
    ]);
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

async function refresh() {
  try {
    overview.value = await identityService.security();
  } catch {
    // Keep showing the last known state; the next action reloads it.
  }
}

onMounted(load);
</script>

<template>
  <section class="card mb-4 p-4" aria-labelledby="security-title">
    <h2 id="security-title" class="mb-3 flex items-center gap-2 font-semibold">
      <ShieldCheck class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" />
      {{ t("accountSecurity.title") }}
    </h2>

    <p v-if="loading" class="text-sm text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</p>
    <p v-else-if="failed || !overview || !providers" class="flex items-center justify-between gap-2 text-sm text-gray-500 dark:text-gray-400">
      {{ t("accountSecurity.loadFailed") }}
      <button type="button" class="btn-ghost text-sm" @click="load">{{ t("states.retry") }}</button>
    </p>
    <div v-else class="space-y-5 divide-y divide-gray-100 dark:divide-gray-800 [&>*:not(:first-child)]:pt-5">
      <ChangePasswordForm :has-password="overview.has_password" />
      <ChangeEmailForm :overview="overview" @changed="refresh" />
      <LinkedAccounts :overview="overview" :providers="providers" @updated="overview = $event" />
    </div>
  </section>
</template>
