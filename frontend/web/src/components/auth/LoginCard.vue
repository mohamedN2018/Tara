<script setup lang="ts">
// The sign-in card (1C), shared by the visitor landing on `/` and by `/login`.
// Email or username (decision 5.6), a show/hide password toggle and "Remember me".
import { Eye, EyeOff } from "lucide-vue-next";
import { computed, ref, useId } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import GoogleSignInButton from "@/components/auth/GoogleSignInButton.vue";
import ResendVerification from "@/components/auth/ResendVerification.vue";
import SuspendedNotice from "@/components/moderation/SuspendedNotice.vue";
import { apiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { afterSignIn } from "@/lib/onboarding";
import { safeRedirect } from "@/lib/redirect";
import { securityErrorKey } from "@/lib/securityErrors";
import { type Suspension, suspensionFrom } from "@/services/moderation";
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
// The account is waiting for email verification: offer a new link.
const needsVerification = ref(false);
// A suspended account learns until when instead of a generic refusal (T7).
const suspended = ref<Suspension | null>(null);
// Two-factor sign-in (3C): the password (or Google) was right, a code is next.
const twoFactor = ref<null | { kind: "password" } | { kind: "google"; credential: string }>(null);
const otp = ref("");

// `?redirect=` from the route guard; `?next=` from older links.
const target = computed(() => safeRedirect(route.query.redirect ?? route.query.next));

async function submit() {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  needsVerification.value = false;
  suspended.value = null;
  const typed = identifier.value.trim();
  try {
    await auth.login(typed, password.value, remember.value, twoFactor.value ? otp.value.trim() : "");
    // A new account's first sign-in offers the optional topic picker (WP 6.6).
    await router.push(afterSignIn(auth.account?.id, target.value));
  } catch (e) {
    if (onTwoFactor(e, { kind: "password" })) return;
    suspended.value = suspensionFrom(e);
    if (suspended.value) return;
    needsVerification.value = apiError(e).code === "permission_denied";
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
  suspended.value = null;
  try {
    await auth.loginWithGoogle(credential, locale.value, twoFactor.value ? otp.value.trim() : "");
    await router.push(target.value);
  } catch (e) {
    if (onTwoFactor(e, { kind: "google", credential })) return;
    suspended.value = suspensionFrom(e);
    if (suspended.value) return;
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

/** A `two_factor_required` / `two_factor_invalid` answer: show (or keep) the code step. */
function onTwoFactor(e: unknown, step: { kind: "password" } | { kind: "google"; credential: string }): boolean {
  const { code } = apiError(e);
  if (code !== "two_factor_required" && code !== "two_factor_invalid") return false;
  if (code === "two_factor_invalid") error.value = t("settingsCenter.login.invalid");
  twoFactor.value = step;
  otp.value = "";
  return true;
}

function submitCode() {
  const step = twoFactor.value;
  if (!step || !otp.value.trim()) return;
  if (step.kind === "google") void googleSignIn(step.credential);
  else void submit();
}

function leaveTwoFactor() {
  twoFactor.value = null;
  otp.value = "";
  error.value = "";
  password.value = "";
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

    <SuspendedNotice v-if="suspended" class="mb-4" :suspension="suspended" />

    <!-- Second factor: the code from the authenticator app, or a recovery code -->
    <form v-if="twoFactor" class="space-y-4" data-testid="login-two-factor" @submit.prevent="submitCode">
      <div>
        <h3 class="font-semibold">{{ t("settingsCenter.login.twoFactorTitle") }}</h3>
        <p class="mt-1 text-sm text-gray-600 dark:text-gray-300">{{ t("settingsCenter.login.twoFactorLead") }}</p>
      </div>
      <div>
        <label :for="`${id}-otp`" class="label">{{ t("settingsCenter.login.code") }}</label>
        <input
          :id="`${id}-otp`"
          v-model="otp"
          dir="ltr"
          type="text"
          class="input text-center font-mono tracking-widest"
          required
          maxlength="32"
          inputmode="text"
          autocomplete="one-time-code"
          autocapitalize="none"
          spellcheck="false"
        />
      </div>
      <p v-if="error" class="text-sm text-red-600 dark:text-red-400" role="alert">{{ error }}</p>
      <button type="submit" class="btn-gradient w-full py-3 text-base" :disabled="loading || !otp.trim()">
        {{ loading ? t("loginCard.submitting") : t("settingsCenter.login.verify") }}
      </button>
      <button type="button" class="btn-ghost w-full text-sm" @click="leaveTwoFactor">{{ t("settingsCenter.login.back") }}</button>
    </form>

    <form v-else class="space-y-4" @submit.prevent="submit">
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
        <div class="min-w-0 flex-1 text-sm leading-snug">
          <label :for="`${id}-remember`" class="block font-semibold text-gray-700 dark:text-gray-200">{{ t("loginCard.remember") }}</label>
          <p :id="`${id}-remember-hint`" class="mt-0.5 text-pretty text-xs text-gray-500 dark:text-gray-400">{{ t("loginCard.rememberHint") }}</p>
        </div>
      </div>

      <p v-if="error" class="text-sm text-red-600 dark:text-red-400" role="alert">{{ error }}</p>
      <ResendVerification
        v-if="needsVerification"
        :email="identifier.includes('@') ? identifier.trim() : ''"
        :compact="identifier.includes('@')"
      />

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
