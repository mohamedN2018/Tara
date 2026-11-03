<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import AuthLayout from "@/components/brand/AuthLayout.vue";
import { errorMessage } from "@/lib/errors";
import { identityService } from "@/services/identity";

const { t } = useI18n();
const route = useRoute();
const token = computed(() => (typeof route.query.token === "string" ? route.query.token : ""));
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
    error.value = errorMessage(e);
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <AuthLayout :title="t('auth.resetTitle')">

      <div v-if="done" class="space-y-4 text-center">
        <p class="rounded-lg bg-green-50 p-3 text-sm text-green-700 dark:bg-green-950/40 dark:text-green-300">
          {{ t("auth.resetDone") }}
        </p>
        <RouterLink to="/login" class="btn-gradient w-full py-3 text-base">{{ t("auth.loginCta") }}</RouterLink>
      </div>
      <form v-else class="space-y-4" @submit.prevent="submit">
        <div>
          <label for="reset-password" class="label">{{ t("auth.newPassword") }}</label>
          <input id="reset-password" v-model="password" type="password" class="input" required minlength="10" autocomplete="new-password" />
        </div>
        <p v-if="error" class="text-sm text-red-500" role="alert">{{ error }}</p>
        <button type="submit" class="btn-gradient w-full py-3 text-base" :disabled="loading">{{ t("auth.resetCta") }}</button>
      </form>

      <p v-if="!done" class="mt-4 text-center text-sm">
        <RouterLink to="/login" class="font-medium text-brand-600 dark:text-brand-300">{{ t("auth.backToLogin") }}</RouterLink>
      </p>
  </AuthLayout>
</template>
