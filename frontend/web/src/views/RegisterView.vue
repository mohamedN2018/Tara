<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import LocaleToggle from "@/components/common/LocaleToggle.vue";
import ThemeToggle from "@/components/common/ThemeToggle.vue";
import { apiError } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

const { t } = useI18n();
const auth = useAuthStore();

const form = ref({ display_name: "", handle: "", email: "", password: "" });
const loading = ref(false);
const error = ref("");
const done = ref(false);

async function submit() {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  try {
    await auth.register(form.value);
    // Account is created in "pending" state — verification is required before
    // sign-in, so show a notice instead of auto-logging in.
    done.value = true;
  } catch (e) {
    error.value = apiError(e).message;
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center px-4 py-8">
    <div class="absolute end-4 top-4 flex gap-2">
      <LocaleToggle />
      <ThemeToggle />
    </div>

    <div class="card w-full max-w-sm p-6">
      <RouterLink to="/" class="mb-1 block text-center text-2xl font-extrabold text-brand-600">
        {{ t("app.name") }}
      </RouterLink>
      <h1 class="mb-6 text-center text-sm text-gray-500">{{ t("auth.joinTara") }}</h1>

      <div v-if="done" class="space-y-4 text-center">
        <p class="rounded-lg bg-green-50 px-3 py-3 text-sm text-green-700 dark:bg-green-950 dark:text-green-300">
          {{ t("auth.verifyEmail") }}
        </p>
        <RouterLink to="/login" class="btn-primary w-full">{{ t("auth.loginCta") }}</RouterLink>
      </div>

      <form v-else class="space-y-4" @submit.prevent="submit">
        <div>
          <label class="mb-1 block text-sm font-medium">{{ t("auth.displayName") }}</label>
          <input v-model="form.display_name" class="input" required />
        </div>
        <div>
          <label class="mb-1 block text-sm font-medium">{{ t("auth.handle") }}</label>
          <input v-model="form.handle" class="input" required autocomplete="username" />
        </div>
        <div>
          <label class="mb-1 block text-sm font-medium">{{ t("auth.email") }}</label>
          <input v-model="form.email" type="email" class="input" required autocomplete="email" />
        </div>
        <div>
          <label class="mb-1 block text-sm font-medium">{{ t("auth.password") }}</label>
          <input
            v-model="form.password"
            type="password"
            class="input"
            required
            minlength="8"
            autocomplete="new-password"
          />
        </div>

        <p v-if="error" class="text-sm text-red-500">{{ error }}</p>

        <button type="submit" class="btn-primary w-full" :disabled="loading">
          {{ t("auth.registerCta") }}
        </button>
      </form>

      <p class="mt-4 text-center text-sm text-gray-500">
        {{ t("auth.haveAccount") }}
        <RouterLink to="/login" class="font-medium text-brand-600">{{ t("auth.loginCta") }}</RouterLink>
      </p>
    </div>
  </div>
</template>
