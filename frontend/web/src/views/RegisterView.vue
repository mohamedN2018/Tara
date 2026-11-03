<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import LocaleToggle from "@/components/common/LocaleToggle.vue";
import ThemeToggle from "@/components/common/ThemeToggle.vue";
import { apiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useAuthStore } from "@/stores/auth";

const { t, locale } = useI18n();
const auth = useAuthStore();

const form = ref({ display_name: "", handle: "", email: "", password: "" });
type Field = keyof typeof form.value;
const FIELD_ERRORS: Record<Field, string> = {
  display_name: "errors.validation_error",
  handle: "auth.handleHint",
  email: "auth.emailInvalid",
  password: "auth.passwordHint",
};

const loading = ref(false);
const error = ref("");
const fieldErrors = ref<Partial<Record<Field, string>>>({});
const done = ref(false);

function applyErrors(e: unknown) {
  const { code, details } = apiError(e);
  const next: Partial<Record<Field, string>> = {};
  if (code === "conflict") next.email = t("auth.emailTaken");
  for (const d of details ?? []) {
    if (d.code === "weak_password") next.password = t("auth.passwordWeak");
    else if (d.field && d.field in FIELD_ERRORS) next[d.field as Field] = t(FIELD_ERRORS[d.field as Field]);
  }
  fieldErrors.value = next;
  error.value = Object.keys(next).length ? "" : errorMessage(e);
}

async function submit() {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  fieldErrors.value = {};
  try {
    await auth.register({ ...form.value, language: locale.value });
    // Account is created in "pending" state — verification is required before
    // sign-in, so show a notice instead of auto-logging in.
    done.value = true;
  } catch (e) {
    applyErrors(e);
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
          <label for="reg-display-name" class="mb-1 block text-sm font-medium">{{ t("auth.displayName") }}</label>
          <input
            id="reg-display-name"
            v-model="form.display_name"
            class="input"
            dir="auto"
            required
            maxlength="120"
            autocomplete="name"
            :aria-invalid="!!fieldErrors.display_name"
            aria-describedby="reg-display-name-error"
          />
          <p v-if="fieldErrors.display_name" id="reg-display-name-error" class="mt-1 text-xs text-red-500">
            {{ fieldErrors.display_name }}
          </p>
        </div>
        <div>
          <label for="reg-handle" class="mb-1 block text-sm font-medium">{{ t("auth.handle") }}</label>
          <input
            id="reg-handle"
            v-model="form.handle"
            class="input"
            dir="ltr"
            required
            minlength="3"
            maxlength="30"
            pattern="[a-zA-Z0-9_]{3,30}"
            :title="t('auth.handleHint')"
            autocomplete="username"
            :aria-invalid="!!fieldErrors.handle"
            aria-describedby="reg-handle-hint"
          />
          <p id="reg-handle-hint" class="mt-1 text-xs" :class="fieldErrors.handle ? 'text-red-500' : 'text-gray-400'">
            {{ fieldErrors.handle || t("auth.handleHint") }}
          </p>
        </div>
        <div>
          <label for="reg-email" class="mb-1 block text-sm font-medium">{{ t("auth.email") }}</label>
          <input
            id="reg-email"
            v-model="form.email"
            type="email"
            class="input"
            dir="ltr"
            required
            autocomplete="email"
            :aria-invalid="!!fieldErrors.email"
            aria-describedby="reg-email-error"
          />
          <p v-if="fieldErrors.email" id="reg-email-error" class="mt-1 text-xs text-red-500">{{ fieldErrors.email }}</p>
        </div>
        <div>
          <label for="reg-password" class="mb-1 block text-sm font-medium">{{ t("auth.password") }}</label>
          <input
            id="reg-password"
            v-model="form.password"
            type="password"
            class="input"
            dir="ltr"
            required
            minlength="10"
            maxlength="128"
            autocomplete="new-password"
            :aria-invalid="!!fieldErrors.password"
            aria-describedby="reg-password-hint"
          />
          <p id="reg-password-hint" class="mt-1 text-xs" :class="fieldErrors.password ? 'text-red-500' : 'text-gray-400'">
            {{ fieldErrors.password || t("auth.passwordHint") }}
          </p>
        </div>

        <p v-if="error" class="text-sm text-red-500" role="alert">{{ error }}</p>

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
