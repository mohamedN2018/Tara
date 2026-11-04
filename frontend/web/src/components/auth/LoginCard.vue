<script setup lang="ts">
// The sign-in card (1C), shared by the visitor landing on `/` and by `/login`.
// Email or username (decision 5.6), a show/hide password toggle and "Remember me".
import { Eye, EyeOff } from "lucide-vue-next";
import { computed, ref, useId } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import GoogleSignInButton from "@/components/auth/GoogleSignInButton.vue";
import { errorMessage } from "@/lib/errors";
import { safeRedirect } from "@/lib/redirect";
import { securityErrorKey } from "@/lib/securityErrors";
import { useAuthStore } from "@/stores/auth";

withDefaults(defineProps<{ title?: string }>(), { title: "" });

const { t, locale } = useI18n();
const auth = useAuthStore();
const router = useRouter();
const route = useRoute();

const id = useId();
const identifier = ref("");
const password = ref("");
const remember = ref(true);
const showPassword = ref(false);
const loading = ref(false);
const error = ref("");

// `?redirect=` from the route guard; `?next=` from older links.
const target = computed(() => safeRedirect(route.query.redirect ?? route.query.next));

async function submit() {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  const typed = identifier.value.trim();
  try {
    await auth.login(typed, password.value, remember.value);
    await router.push(target.value);
  } catch (e) {
    // One message for a wrong password and an unknown account alike.
    error.value = errorMessage(e, {
      authentication_failed: "loginCard.invalid",
      permission_denied: "auth.accountNotActive",
      ...(typed.includes("@") ? {} : { dependency_unavailable: "loginCard.unavailable" }),
    });
  } finally {
    loading.value = false;
  }
}

async function googleSignIn(credential: string) {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  try {
    await auth.loginWithGoogle(credential, locale.value);
    await router.push(target.value);
  } catch (e) {
    error.value = t(
      securityErrorKey(e, {
        authentication_failed: "accountSecurity.google.failed",
        permission_denied: "auth.accountNotActive",
      }),
    );
  } finally {
    loading.value = false;
  }
}

// The stored session is intact; the server just couldn't be reached at boot.
async function retrySession() {
  await auth.bootstrap();
  if (auth.isAuthenticated) await router.push(target.value);
}
</script>

<template>
  <section class="card p-5 shadow-pop sm:p-6" :aria-labelledby="title ? `${id}-title` : undefined">
    <h2 v-if="title" :id="`${id}-title`" class="mb-5 font-display text-lg font-bold text-gray-950 dark:text-white">
      {{ title }}
    </h2>

    <div
      v-if="auth.sessionUnavailable"
      class="mb-4 flex items-center justify-between gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
      role="status"
    >
      <span>{{ t("auth.sessionUnavailable") }}</span>
      <button type="button" class="shrink-0 font-semibold underline" @click="retrySession">{{ t("states.retry") }}</button>
    </div>

    <form class="space-y-4" @submit.prevent="submit">
      <div>
        <label :for="`${id}-identifier`" class="label">{{ t("loginCard.identifier") }}</label>
        <input
          :id="`${id}-identifier`"
          v-model="identifier"
          dir="ltr"
          type="text"
          class="input"
          required
          maxlength="254"
          autocomplete="username"
          autocapitalize="none"
          spellcheck="false"
        />
      </div>

      <div>
        <label :for="`${id}-password`" class="label">{{ t("loginCard.password") }}</label>
        <div class="relative">
          <input
            :id="`${id}-password`"
            v-model="password"
            dir="ltr"
            :type="showPassword ? 'text' : 'password'"
            class="input pe-12"
            required
            autocomplete="current-password"
          />
          <!-- Named by its text, not aria-label, so the field's label stays unique. -->
          <button
            type="button"
            class="absolute inset-y-0 end-0 flex w-11 items-center justify-center rounded-e-xl text-gray-500 hover:text-brand-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:text-gray-400 dark:hover:text-brand-300"
            :aria-pressed="showPassword"
            :aria-controls="`${id}-password`"
            data-testid="toggle-password"
            @click="showPassword = !showPassword"
          >
            <EyeOff v-if="showPassword" class="h-5 w-5" aria-hidden="true" />
            <Eye v-else class="h-5 w-5" aria-hidden="true" />
            <span class="sr-only">{{ t("loginCard.showPassword") }}</span>
          </button>
        </div>
      </div>

      <div class="flex items-start gap-2.5">
        <input
          :id="`${id}-remember`"
          v-model="remember"
          type="checkbox"
          class="mt-0.5 h-4 w-4 shrink-0 rounded border-gray-300 text-brand-600 accent-brand-600 focus-visible:ring-2 focus-visible:ring-brand-400 dark:border-gray-700"
          :aria-describedby="`${id}-remember-hint`"
        />
        <div class="text-sm">
          <label :for="`${id}-remember`" class="font-semibold text-gray-700 dark:text-gray-200">{{ t("loginCard.remember") }}</label>
          <p :id="`${id}-remember-hint`" class="text-xs text-gray-500 dark:text-gray-400">{{ t("loginCard.rememberHint") }}</p>
        </div>
      </div>

      <p v-if="error" class="text-sm text-red-600 dark:text-red-400" role="alert">{{ error }}</p>

      <button type="submit" class="btn-gradient w-full py-3 text-base" :disabled="loading">
        {{ loading ? t("loginCard.submitting") : t("loginCard.submit") }}
      </button>
    </form>

    <p class="mt-4 text-center text-sm">
      <RouterLink to="/forgot-password" class="font-semibold text-brand-700 hover:underline dark:text-brand-300">
        {{ t("loginCard.forgotten") }}
      </RouterLink>
    </p>

    <GoogleSignInButton text="signin_with" divider @credential="googleSignIn" />

    <hr class="divider my-5" />

    <RouterLink
      to="/register"
      class="btn-outline w-full border-brand-600 py-3 text-base text-brand-700 hover:bg-brand-50 dark:border-brand-400 dark:text-brand-200 dark:hover:bg-brand-950/50"
    >
      {{ t("loginCard.createAccount") }}
    </RouterLink>
  </section>
</template>
