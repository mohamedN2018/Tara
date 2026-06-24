<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import LocaleToggle from "@/components/common/LocaleToggle.vue";
import ThemeToggle from "@/components/common/ThemeToggle.vue";
import { apiError } from "@/lib/api";
import { identityService } from "@/services/identity";

const { t } = useI18n();
const email = ref("");
const loading = ref(false);
const sent = ref(false);
const error = ref("");

async function submit() {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  try {
    await identityService.forgotPassword(email.value);
    sent.value = true;
  } catch (e) {
    error.value = apiError(e).message;
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center px-4">
    <div class="absolute end-4 top-4 flex gap-2"><LocaleToggle /><ThemeToggle /></div>
    <div class="card w-full max-w-sm p-6">
      <RouterLink to="/" class="mb-1 block text-center text-2xl font-extrabold text-brand-600">
        {{ t("app.name") }}
      </RouterLink>
      <h1 class="mb-6 text-center text-sm text-gray-500">{{ t("auth.forgotTitle") }}</h1>

      <p v-if="sent" class="rounded-lg bg-green-50 p-3 text-center text-sm text-green-700 dark:bg-green-950/40 dark:text-green-300">
        {{ t("auth.forgotSent") }}
      </p>
      <form v-else class="space-y-4" @submit.prevent="submit">
        <div>
          <label class="mb-1 block text-sm font-medium">{{ t("auth.email") }}</label>
          <input v-model="email" type="email" class="input" required autocomplete="email" />
        </div>
        <p v-if="error" class="text-sm text-red-500">{{ error }}</p>
        <button type="submit" class="btn-primary w-full" :disabled="loading">{{ t("auth.forgotCta") }}</button>
      </form>

      <p class="mt-4 text-center text-sm">
        <RouterLink to="/login" class="font-medium text-brand-600">{{ t("auth.backToLogin") }}</RouterLink>
      </p>
    </div>
  </div>
</template>
