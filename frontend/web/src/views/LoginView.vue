<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import LocaleToggle from "@/components/common/LocaleToggle.vue";
import ThemeToggle from "@/components/common/ThemeToggle.vue";
import { apiError } from "@/lib/api";
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
    const redirect = (route.query.redirect as string) || "/home";
    router.push(redirect);
  } catch (e) {
    error.value = apiError(e).message;
  } finally {
    loading.value = false;
  }
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

      <form class="space-y-4" @submit.prevent="submit">
        <div>
          <label class="mb-1 block text-sm font-medium">{{ t("auth.email") }}</label>
          <input v-model="email" type="email" class="input" required autocomplete="email" />
        </div>
        <div>
          <label class="mb-1 block text-sm font-medium">{{ t("auth.password") }}</label>
          <input
            v-model="password"
            type="password"
            class="input"
            required
            autocomplete="current-password"
          />
        </div>

        <p v-if="error" class="text-sm text-red-500">{{ error }}</p>

        <button type="submit" class="btn-primary w-full" :disabled="loading">
          {{ loading ? t("auth.loggingIn") : t("auth.loginCta") }}
        </button>
      </form>

      <p class="mt-4 text-center text-sm text-gray-500">
        {{ t("auth.noAccount") }}
        <RouterLink to="/register" class="font-medium text-brand-600">
          {{ t("auth.registerCta") }}
        </RouterLink>
      </p>
    </div>
  </div>
</template>
