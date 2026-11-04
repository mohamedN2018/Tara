<script setup lang="ts">
// Full registration (plan 08 §1.1, track 1D). Every rule here is checked again
// by identity; the client checks only to answer sooner.
import { CheckCircle2, Loader2 } from "lucide-vue-next";
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import GoogleSignInButton from "@/components/auth/GoogleSignInButton.vue";
import PasswordStrength from "@/components/auth/PasswordStrength.vue";
import AuthLayout from "@/components/brand/AuthLayout.vue";
import { apiError } from "@/lib/api";
import { markProfileToComplete } from "@/lib/completeProfile";
import { errorMessage } from "@/lib/errors";
import { legalPath, PRIVACY_VERSION, TERMS_VERSION } from "@/lib/legal";
import { MIN_PASSWORD_LENGTH } from "@/lib/passwordStrength";
import { securityErrorKey } from "@/lib/securityErrors";
import { profileService } from "@/services/profile";
import { type RegisterPayload, useAuthStore } from "@/stores/auth";

const { t, locale } = useI18n();
const auth = useAuthStore();
const router = useRouter();

const HANDLE_RE = /^[a-zA-Z0-9_]{3,30}$/;
const HANDLE_CHECK_DELAY_MS = 400;
const OLDEST_YEARS = 120;

const form = reactive({
  first_name: "",
  last_name: "",
  handle: "",
  email: "",
  password: "",
  password_confirm: "",
  day: "",
  month: "",
  year: "",
  gender: "" as RegisterPayload["gender"],
  gender_custom: "",
  accept_terms: false,
});

type Field =
  | "first_name"
  | "last_name"
  | "handle"
  | "email"
  | "password"
  | "password_confirm"
  | "date_of_birth"
  | "gender"
  | "gender_custom"
  | "accept_terms";

// Element ids, in the order the form shows them (the first error gets focus).
const INPUT_ID: Record<Field, string> = {
  first_name: "reg-first-name",
  last_name: "reg-last-name",
  handle: "reg-handle",
  email: "reg-email",
  password: "reg-password",
  password_confirm: "reg-password-confirm",
  date_of_birth: "reg-dob-day",
  gender: "reg-gender-female",
  gender_custom: "reg-gender-custom",
  accept_terms: "reg-consent",
};

// A field's own message when the server names only the field.
const FIELD_MESSAGE: Record<Field, string> = {
  first_name: "register.nameInvalid",
  last_name: "register.nameInvalid",
  handle: "auth.handleHint",
  email: "auth.emailInvalid",
  password: "auth.passwordHint",
  password_confirm: "register.passwordMismatch",
  date_of_birth: "register.dobInvalid",
  gender: "errors.validation_error",
  gender_custom: "register.genderCustomRequired",
  accept_terms: "register.consentRequired",
};

// What the server's detail codes mean to the person filling the form.
const CODE_MESSAGE: Record<string, string> = {
  password_mismatch: "register.passwordMismatch",
  age_below_minimum: "register.dobTooYoung",
  invalid_date: "register.dobInvalid",
  consent_required: "register.consentRequired",
  legal_version_mismatch: "register.legalOutdated",
  weak_password: "auth.passwordWeak",
  reserved_handle: "register.handleTaken",
  invalid_name: "register.nameInvalid",
};

const loading = ref(false);
const error = ref("");
const fieldErrors = ref<Partial<Record<Field, string>>>({});
const done = ref(false);

// ---- date of birth ----------------------------------------------------------

const thisYear = new Date().getFullYear();
const years = Array.from({ length: OLDEST_YEARS + 1 }, (_, i) => thisYear - i);
const days = Array.from({ length: 31 }, (_, i) => i + 1);
const months = computed(() => {
  const format = new Intl.DateTimeFormat(locale.value, { month: "long", timeZone: "UTC" });
  return Array.from({ length: 12 }, (_, i) => ({ value: i + 1, label: format.format(Date.UTC(2000, i, 1)) }));
});

/** YYYY-MM-DD, or "" while incomplete or impossible (30 February). */
const dateOfBirth = computed(() => {
  const [y, m, d] = [Number(form.year), Number(form.month), Number(form.day)];
  if (!y || !m || !d) return "";
  const date = new Date(Date.UTC(y, m - 1, d));
  if (date.getUTCMonth() !== m - 1 || date.getUTCDate() !== d) return "";
  return date.toISOString().slice(0, 10);
});

// ---- live handle check (debounced; the server's answer is all we show) ------

type HandleState = "idle" | "invalid" | "checking" | "available" | "taken" | "error";
const handleState = ref<HandleState>("idle");
let handleTimer: number | undefined;
let handleRequest: AbortController | null = null;

async function checkHandle(handle: string) {
  handleRequest?.abort();
  const request = new AbortController();
  handleRequest = request;
  try {
    const result = await profileService.handleAvailable(handle, request.signal);
    if (request.signal.aborted) return;
    handleState.value = result.available ? "available" : result.reason === "invalid" ? "invalid" : "taken";
  } catch {
    if (!request.signal.aborted) handleState.value = "error";
  }
}

watch(
  () => form.handle,
  (handle) => {
    window.clearTimeout(handleTimer);
    handleRequest?.abort();
    if (fieldErrors.value.handle) fieldErrors.value = { ...fieldErrors.value, handle: undefined };
    if (!handle) handleState.value = "idle";
    else if (!HANDLE_RE.test(handle)) handleState.value = "invalid";
    else {
      handleState.value = "checking";
      handleTimer = window.setTimeout(() => void checkHandle(handle), HANDLE_CHECK_DELAY_MS);
    }
  },
);

onBeforeUnmount(() => {
  window.clearTimeout(handleTimer);
  handleRequest?.abort();
});

const handleMessage = computed(() => {
  if (fieldErrors.value.handle) return fieldErrors.value.handle;
  switch (handleState.value) {
    case "checking":
      return t("register.handleChecking");
    case "available":
      return t("register.handleAvailable", { handle: form.handle.toLowerCase() });
    case "taken":
      return t("register.handleTaken");
    case "error":
      return t("register.handleCheckFailed");
    default:
      return t("auth.handleHint");
  }
});
const handleIsBad = computed(() => !!fieldErrors.value.handle || handleState.value === "taken");

// ---- validation -------------------------------------------------------------

const confirmMismatch = computed(
  () => !!form.password_confirm && form.password_confirm !== form.password,
);
const strengthInputs = computed(() => [form.email, form.handle, form.first_name, form.last_name]);

function clientErrors(): Partial<Record<Field, string>> {
  const next: Partial<Record<Field, string>> = {};
  if (handleState.value === "taken") next.handle = t("register.handleTaken");
  if (form.password !== form.password_confirm) next.password_confirm = t("register.passwordMismatch");
  if (!form.day || !form.month || !form.year) next.date_of_birth = t("register.dobIncomplete");
  else if (!dateOfBirth.value) next.date_of_birth = t("register.dobInvalid");
  if (form.gender === "custom" && !form.gender_custom.trim()) {
    next.gender_custom = t("register.genderCustomRequired");
  }
  if (!form.accept_terms) next.accept_terms = t("register.consentRequired");
  return next;
}

function focusFirst(errors: Partial<Record<Field, string>>) {
  const first = (Object.keys(INPUT_ID) as Field[]).find((f) => errors[f]);
  if (first) document.getElementById(INPUT_ID[first])?.focus();
}

function applyServerErrors(e: unknown) {
  const { code, details } = apiError(e);
  const next: Partial<Record<Field, string>> = {};
  if (code === "conflict") next.email = t("auth.emailTaken");
  for (const d of details ?? []) {
    // A changed legal version is about the consent the person gave.
    const field = d.field === "terms_version" || d.field === "privacy_version" ? "accept_terms" : d.field;
    if (!field || !(field in FIELD_MESSAGE)) continue;
    next[field as Field] ??= t(CODE_MESSAGE[d.code] ?? FIELD_MESSAGE[field as Field]);
  }
  fieldErrors.value = next;
  error.value = Object.keys(next).length ? t("register.fixErrors") : errorMessage(e);
  focusFirst(next);
}

function describedBy(field: Field, hint?: string): string {
  return [hint, fieldErrors.value[field] ? `${INPUT_ID[field]}-error` : ""].filter(Boolean).join(" ");
}

// ---- submit -----------------------------------------------------------------

// Google already proved the address: the account is active at once.
async function googleSignUp(credential: string) {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  fieldErrors.value = {};
  try {
    await auth.loginWithGoogle(credential, locale.value);
    router.push("/home");
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

async function submit() {
  if (loading.value) return;
  error.value = "";
  const local = clientErrors();
  fieldErrors.value = local;
  if (Object.keys(local).length) {
    error.value = t("register.fixErrors");
    focusFirst(local);
    return;
  }
  loading.value = true;
  try {
    const result = await auth.register({
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
      handle: form.handle,
      email: form.email.trim(),
      password: form.password,
      password_confirm: form.password_confirm,
      date_of_birth: dateOfBirth.value,
      gender: form.gender,
      gender_custom: form.gender === "custom" ? form.gender_custom.trim() : "",
      accept_terms: form.accept_terms,
      terms_version: TERMS_VERSION,
      privacy_version: PRIVACY_VERSION,
      language: locale.value,
    });
    // "Complete your profile" waits on /home for this account's first sign-in.
    markProfileToComplete(result.account_id);
    // Pending until the mailed link is opened: no auto-login.
    done.value = true;
  } catch (e) {
    applyServerErrors(e);
  } finally {
    loading.value = false;
  }
}

const GENDERS: Array<{ value: Exclude<RegisterPayload["gender"], "">; label: string }> = [
  { value: "female", label: "register.genderFemale" },
  { value: "male", label: "register.genderMale" },
  { value: "custom", label: "register.genderCustom" },
  { value: "prefer_not_to_say", label: "register.genderUndisclosed" },
];
</script>

<template>
  <AuthLayout :title="t('auth.joinTara')">
    <div v-if="done" class="space-y-4 text-center">
      <p class="rounded-xl bg-brand-50 px-3 py-3 text-sm text-brand-800 dark:bg-brand-950 dark:text-brand-100" role="status">
        {{ t("auth.verifyEmail") }}
      </p>
      <RouterLink to="/login" class="btn-gradient w-full py-3 text-base">{{ t("auth.loginCta") }}</RouterLink>
    </div>

    <form v-else class="space-y-4" data-testid="register-form" @submit.prevent="submit">
      <p class="-mt-4 text-sm text-gray-500 dark:text-gray-400">{{ t("register.subtitle") }}</p>

      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label for="reg-first-name" class="label">{{ t("register.firstName") }}</label>
          <input
            id="reg-first-name"
            v-model="form.first_name"
            class="input"
            dir="auto"
            required
            maxlength="40"
            autocomplete="given-name"
            :aria-invalid="!!fieldErrors.first_name"
            :aria-describedby="describedBy('first_name') || undefined"
          />
          <p v-if="fieldErrors.first_name" id="reg-first-name-error" class="mt-1 text-xs text-red-600 dark:text-red-400">
            {{ fieldErrors.first_name }}
          </p>
        </div>
        <div>
          <label for="reg-last-name" class="label">{{ t("register.lastName") }}</label>
          <input
            id="reg-last-name"
            v-model="form.last_name"
            class="input"
            dir="auto"
            required
            maxlength="40"
            autocomplete="family-name"
            :aria-invalid="!!fieldErrors.last_name"
            :aria-describedby="describedBy('last_name') || undefined"
          />
          <p v-if="fieldErrors.last_name" id="reg-last-name-error" class="mt-1 text-xs text-red-600 dark:text-red-400">
            {{ fieldErrors.last_name }}
          </p>
        </div>
      </div>

      <div>
        <label for="reg-handle" class="label">{{ t("auth.handle") }}</label>
        <div class="relative">
          <span class="pointer-events-none absolute inset-y-0 start-3 flex items-center text-sm text-gray-400" aria-hidden="true">@</span>
          <input
            id="reg-handle"
            v-model.trim="form.handle"
            class="input ps-8"
            dir="ltr"
            required
            minlength="3"
            maxlength="30"
            pattern="[a-zA-Z0-9_]{3,30}"
            autocomplete="username"
            autocapitalize="none"
            spellcheck="false"
            :aria-invalid="handleIsBad"
            aria-describedby="reg-handle-hint"
          />
          <span class="pointer-events-none absolute inset-y-0 end-3 flex items-center" aria-hidden="true">
            <Loader2 v-if="handleState === 'checking'" class="h-4 w-4 animate-spin text-gray-400" />
            <CheckCircle2 v-else-if="handleState === 'available'" class="h-4 w-4 text-brand-600 dark:text-brand-300" />
          </span>
        </div>
        <p
          id="reg-handle-hint"
          class="mt-1 text-xs"
          :class="handleIsBad ? 'text-red-600 dark:text-red-400' : handleState === 'available' ? 'text-brand-700 dark:text-brand-300' : 'text-gray-500 dark:text-gray-400'"
          aria-live="polite"
          data-testid="handle-status"
          :data-state="handleState"
        >
          {{ handleMessage }}
        </p>
      </div>

      <div>
        <label for="reg-email" class="label">{{ t("auth.email") }}</label>
        <input
          id="reg-email"
          v-model="form.email"
          type="email"
          class="input"
          dir="ltr"
          required
          autocomplete="email"
          :aria-invalid="!!fieldErrors.email"
          :aria-describedby="describedBy('email') || undefined"
        />
        <p v-if="fieldErrors.email" id="reg-email-error" class="mt-1 text-xs text-red-600 dark:text-red-400">{{ fieldErrors.email }}</p>
      </div>

      <div>
        <label for="reg-password" class="label">{{ t("auth.password") }}</label>
        <input
          id="reg-password"
          v-model="form.password"
          type="password"
          class="input"
          dir="ltr"
          required
          :minlength="MIN_PASSWORD_LENGTH"
          maxlength="128"
          autocomplete="new-password"
          :aria-invalid="!!fieldErrors.password"
          aria-describedby="reg-password-hint reg-password-strength"
        />
        <p
          id="reg-password-hint"
          class="mt-1 text-xs"
          :class="fieldErrors.password ? 'text-red-600 dark:text-red-400' : 'text-gray-500 dark:text-gray-400'"
        >
          {{ fieldErrors.password || t("auth.passwordHint") }}
        </p>
        <PasswordStrength id="reg-password-strength" :password="form.password" :user-inputs="strengthInputs" />
      </div>

      <div>
        <label for="reg-password-confirm" class="label">{{ t("register.confirmPassword") }}</label>
        <input
          id="reg-password-confirm"
          v-model="form.password_confirm"
          type="password"
          class="input"
          dir="ltr"
          required
          maxlength="128"
          autocomplete="new-password"
          :aria-invalid="!!fieldErrors.password_confirm || confirmMismatch"
          :aria-describedby="fieldErrors.password_confirm || confirmMismatch ? 'reg-password-confirm-error' : undefined"
        />
        <p
          v-if="fieldErrors.password_confirm || confirmMismatch"
          id="reg-password-confirm-error"
          class="mt-1 text-xs text-red-600 dark:text-red-400"
        >
          {{ fieldErrors.password_confirm || t("register.passwordMismatch") }}
        </p>
      </div>

      <fieldset :aria-describedby="describedBy('date_of_birth', 'reg-dob-hint')">
        <legend class="label">{{ t("register.dateOfBirth") }}</legend>
        <div class="grid grid-cols-[1fr_1.6fr_1.2fr] gap-2">
          <div>
            <label for="reg-dob-day" class="sr-only">{{ t("register.day") }}</label>
            <select id="reg-dob-day" v-model="form.day" class="input" required :aria-invalid="!!fieldErrors.date_of_birth">
              <option value="" disabled>{{ t("register.day") }}</option>
              <option v-for="d in days" :key="d" :value="String(d)">{{ d }}</option>
            </select>
          </div>
          <div>
            <label for="reg-dob-month" class="sr-only">{{ t("register.month") }}</label>
            <select id="reg-dob-month" v-model="form.month" class="input" required :aria-invalid="!!fieldErrors.date_of_birth">
              <option value="" disabled>{{ t("register.month") }}</option>
              <option v-for="m in months" :key="m.value" :value="String(m.value)">{{ m.label }}</option>
            </select>
          </div>
          <div>
            <label for="reg-dob-year" class="sr-only">{{ t("register.year") }}</label>
            <select id="reg-dob-year" v-model="form.year" class="input" required :aria-invalid="!!fieldErrors.date_of_birth">
              <option value="" disabled>{{ t("register.year") }}</option>
              <option v-for="y in years" :key="y" :value="String(y)">{{ y }}</option>
            </select>
          </div>
        </div>
        <p id="reg-dob-hint" class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ t("register.dobHint") }}</p>
        <p v-if="fieldErrors.date_of_birth" id="reg-dob-day-error" class="mt-1 text-xs text-red-600 dark:text-red-400">
          {{ fieldErrors.date_of_birth }}
        </p>
      </fieldset>

      <fieldset aria-describedby="reg-gender-hint">
        <legend class="label">
          {{ t("register.gender") }}
          <span class="font-normal text-gray-500 dark:text-gray-400">{{ t("register.optional") }}</span>
        </legend>
        <div class="grid grid-cols-2 gap-2">
          <label
            v-for="g in GENDERS"
            :key="g.value"
            class="flex cursor-pointer items-center justify-between gap-2 rounded-xl border border-gray-200 bg-gray-50 px-3 py-2.5 text-sm transition hover:border-brand-300 has-[:checked]:border-brand-500 has-[:checked]:bg-brand-50 dark:border-gray-800 dark:bg-gray-950/60 dark:has-[:checked]:border-brand-400 dark:has-[:checked]:bg-brand-950"
          >
            <span>{{ t(g.label) }}</span>
            <input
              :id="`reg-gender-${g.value === 'prefer_not_to_say' ? 'undisclosed' : g.value}`"
              v-model="form.gender"
              type="radio"
              name="gender"
              :value="g.value"
              class="h-4 w-4 accent-brand-600"
            />
          </label>
        </div>
        <p id="reg-gender-hint" class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ t("register.genderHint") }}</p>
        <div v-if="form.gender === 'custom'" class="mt-3">
          <label for="reg-gender-custom" class="label">{{ t("register.genderCustomLabel") }}</label>
          <input
            id="reg-gender-custom"
            v-model="form.gender_custom"
            class="input"
            dir="auto"
            maxlength="40"
            :aria-invalid="!!fieldErrors.gender_custom"
            :aria-describedby="describedBy('gender_custom') || undefined"
          />
          <p v-if="fieldErrors.gender_custom" id="reg-gender-custom-error" class="mt-1 text-xs text-red-600 dark:text-red-400">
            {{ fieldErrors.gender_custom }}
          </p>
        </div>
      </fieldset>

      <div>
        <div class="flex items-start gap-2.5">
          <input
            id="reg-consent"
            v-model="form.accept_terms"
            type="checkbox"
            class="mt-0.5 h-4 w-4 shrink-0 accent-brand-600"
            :aria-invalid="!!fieldErrors.accept_terms"
            :aria-describedby="describedBy('accept_terms') || undefined"
          />
          <label for="reg-consent" class="text-sm text-gray-700 dark:text-gray-200">
            <i18n-t keypath="register.consent" tag="span" scope="global">
              <template #terms>
                <a :href="legalPath('terms')" target="_blank" rel="noopener" class="font-semibold text-brand-700 underline-offset-2 hover:underline dark:text-brand-300">
                  {{ t("register.terms") }}<span class="sr-only"> {{ t("register.opensInNewTab") }}</span>
                </a>
              </template>
              <template #privacy>
                <a :href="legalPath('privacy')" target="_blank" rel="noopener" class="font-semibold text-brand-700 underline-offset-2 hover:underline dark:text-brand-300">
                  {{ t("register.privacy") }}<span class="sr-only"> {{ t("register.opensInNewTab") }}</span>
                </a>
              </template>
            </i18n-t>
          </label>
        </div>
        <p v-if="fieldErrors.accept_terms" id="reg-consent-error" class="mt-1 text-xs text-red-600 dark:text-red-400">
          {{ fieldErrors.accept_terms }}
        </p>
      </div>

      <p v-if="error" class="text-sm text-red-600 dark:text-red-400" role="alert">{{ error }}</p>

      <button type="submit" class="btn-gradient w-full py-3 text-base" :disabled="loading">
        {{ t("auth.registerCta") }}
      </button>
    </form>

    <GoogleSignInButton v-if="!done" text="signup_with" divider @credential="googleSignUp" />

    <p class="mt-4 text-center text-sm text-gray-500 dark:text-gray-400">
      {{ t("auth.haveAccount") }}
      <RouterLink to="/login" class="font-medium text-brand-600 dark:text-brand-300">{{ t("auth.loginCta") }}</RouterLink>
    </p>
  </AuthLayout>
</template>
