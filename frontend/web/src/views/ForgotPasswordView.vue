<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import AuthLayout from "@/components/brand/AuthLayout.vue";
import { errorMessage } from "@/lib/errors";
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
    error.value = errorMessage(e);
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <AuthLayout :title="t('auth.forgotTitle')">

      <p v-if="sent" class="rounded-lg bg-green-50 p-3 text-center text-sm text-green-700 dark:bg-green-950/40 dark:text-green-300">
        {{ t("auth.forgotSent") }}
      </p>
      <form v-else class="space-y-4" @submit.prevent="submit">
        <div>
          <label for="forgot-email" class="label">{{ t("auth.email") }}</label>
          <input id="forgot-email" v-model="email" type="email" class="input" required autocomplete="email" />
        </div>
        <p v-if="error" class="text-sm text-red-500">{{ error }}</p>
        <button type="submit" class="btn-gradient w-full py-3 text-base" :disabled="loading">{{ t("auth.forgotCta") }}</button>
      </form>

      <p class="mt-4 text-center text-sm">
        <RouterLink to="/login" class="font-medium text-brand-600 dark:text-brand-300">{{ t("auth.backToLogin") }}</RouterLink>
      </p>
  </AuthLayout>
</template>
