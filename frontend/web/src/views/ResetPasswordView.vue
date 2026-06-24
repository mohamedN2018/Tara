<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import LocaleToggle from "@/components/common/LocaleToggle.vue";
import ThemeToggle from "@/components/common/ThemeToggle.vue";
import { apiError } from "@/lib/api";
import { identityService } from "@/services/identity";

const { t } = useI18n();
const route = useRoute();
const token = computed(() => (route.query.token as string) || "");
const password = ref("");
const loading = ref(false);
const done = ref(false);
const error = ref("");

async function submit() {
  if (loading.value) return;
  if (!token.value) {
    error.value = t("auth.missingToken");
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    await identityService.resetPassword(token.value, password.value);
    done.value = true;
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
      <h1 class="mb-6 text-center text-sm text-gray-500">{{ t("auth.resetTitle") }}</h1>

      <div v-if="done" class="space-y-4 text-center">
        <p class="rounded-lg bg-green-50 p-3 text-sm text-green-700 dark:bg-green-950/40 dark:text-green-300">
          {{ t("auth.resetDone") }}
        </p>
        <RouterLink to="/login" class="btn-primary w-full">{{ t("auth.loginCta") }}</RouterLink>
      </div>
      <form v-else class="space-y-4" @submit.prevent="submit">
        <div>
          <label class="mb-1 block text-sm font-medium">{{ t("auth.newPassword") }}</label>
          <input v-model="password" type="password" class="input" required minlength="10" autocomplete="new-password" />
        </div>
        <p v-if="error" class="text-sm text-red-500">{{ error }}</p>
        <button type="submit" class="btn-primary w-full" :disabled="loading">{{ t("auth.resetCta") }}</button>
      </form>

      <p v-if="!done" class="mt-4 text-center text-sm">
        <RouterLink to="/login" class="font-medium text-brand-600">{{ t("auth.backToLogin") }}</RouterLink>
      </p>
    </div>
  </div>
</template>
