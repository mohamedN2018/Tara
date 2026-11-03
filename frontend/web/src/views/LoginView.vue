<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import LocaleToggle from "@/components/common/LocaleToggle.vue";
import ThemeToggle from "@/components/common/ThemeToggle.vue";
import { errorMessage } from "@/lib/errors";
import { safeRedirect } from "@/lib/redirect";
import { useAuthStore } from "@/stores/auth";

const { t } = useI18n();
const auth = useAuthStore();
const router = useRouter();
const route = useRoute();

const email = ref("");
const password = ref("");
const loading = ref(false);
const error = ref("");

async function submit() {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  try {
    await auth.login(email.value, password.value);
    router.push(safeRedirect(route.query.redirect));
  } catch (e) {
    error.value = errorMessage(e, {
      authentication_failed: "auth.invalidCredentials",
      permission_denied: "auth.accountNotActive",
    });
  } finally {
    loading.value = false;
  }
}

// The stored session is intact; the server just couldn't be reached at boot.
async function retrySession() {
  await auth.bootstrap();
  if (auth.isAuthenticated) router.push(safeRedirect(route.query.redirect));
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center px-4">
    <div class="absolute end-4 top-4 flex gap-2">
      <LocaleToggle />
      <ThemeToggle />
    </div>

    <div class="card w-full max-w-sm p-6">
      <RouterLink to="/" class="mb-1 block text-center text-2xl font-extrabold text-brand-600">
        {{ t("app.name") }}
      </RouterLink>
      <h1 class="mb-6 text-center text-sm text-gray-500">{{ t("auth.welcome") }}</h1>

      <div
        v-if="auth.sessionUnavailable"
        class="mb-4 flex items-center justify-between gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-950/40 dark:text-amber-300"
        role="status"
      >
        <span>{{ t("auth.sessionUnavailable") }}</span>
        <button type="button" class="shrink-0 font-semibold underline" @click="retrySession">{{ t("states.retry") }}</button>
      </div>

      <form class="space-y-4" @submit.prevent="submit">
        <div>
          <label for="login-email" class="mb-1 block text-sm font-medium">{{ t("auth.email") }}</label>
          <input id="login-email" v-model="email" dir="ltr" type="email" class="input" required autocomplete="email" />
        </div>
        <div>
          <label for="login-password" class="mb-1 block text-sm font-medium">{{ t("auth.password") }}</label>
          <input
            id="login-password"
            v-model="password"
            dir="ltr"
            type="password"
            class="input"
            required
            autocomplete="current-password"
          />
        </div>

        <p v-if="error" class="text-sm text-red-500" role="alert">{{ error }}</p>

        <button type="submit" class="btn-primary w-full" :disabled="loading">
          {{ loading ? t("auth.loggingIn") : t("auth.loginCta") }}
        </button>
      </form>

      <p class="mt-3 text-center text-sm">
        <RouterLink to="/forgot-password" class="font-medium text-brand-600">
          {{ t("auth.forgotPassword") }}
        </RouterLink>
      </p>

      <p class="mt-4 text-center text-sm text-gray-500">
        {{ t("auth.noAccount") }}
        <RouterLink to="/register" class="font-medium text-brand-600">
          {{ t("auth.registerCta") }}
        </RouterLink>
      </p>
    </div>
  </div>
</template>
