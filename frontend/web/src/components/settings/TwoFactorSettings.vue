<script setup lang="ts">
// Two-factor authentication (TOTP, /me/2fa/*). Turning it on: re-enter the
// password, add the setup key to an authenticator app, confirm a code, save the
// recovery codes (shown once). Turning it off needs the password and a code.
import { Copy, Download, KeyRound } from "lucide-vue-next";
import { onMounted, ref, useId, watch } from "vue";
import { useI18n } from "vue-i18n";

import { apiError } from "@/lib/api";
import { securityErrorKey } from "@/lib/securityErrors";
import { identityService, type TwoFactorSetup, type TwoFactorStatus } from "@/services/identity";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";

const { t, locale } = useI18n();
const auth = useAuthStore();
const toasts = useToastStore();
const uid = useId();

const status = ref<TwoFactorStatus | null>(null);
const failed = ref(false);
// idle → password (to start or to get new codes) → setup → codes; or disable.
const step = ref<"idle" | "password" | "setup" | "codes" | "disable" | "regenerate">("idle");
const password = ref("");
const code = ref("");
const setup = ref<TwoFactorSetup | null>(null);
const codes = ref<string[]>([]);
const busy = ref(false);
const error = ref("");

async function load() {
  failed.value = false;
  try {
    status.value = await identityService.twoFactor();
  } catch {
    failed.value = true;
  }
}

function reset() {
  step.value = "idle";
  password.value = "";
  code.value = "";
  setup.value = null;
  error.value = "";
}

function fieldError(e: unknown): string {
  const err = apiError(e);
  const detail = err.details?.[0]?.code;
  if (detail === "invalid_code" || err.code === "two_factor_invalid") return t("settingsCenter.twoFactor.invalidCode");
  if (detail === "no_pending_setup") return t("settingsCenter.twoFactor.restart");
  return t(securityErrorKey(e));
}

async function run(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await action();
  } catch (e) {
    error.value = fieldError(e);
  } finally {
    busy.value = false;
  }
}

// A scannable QR of the otpauth URI. The encoder (qrcode, pinned) is loaded
// only when a setup starts, as an SVG data URL (CSP allows data: images). If
// it can't load, the setup key and the app link below still work.
const qr = ref("");
watch(setup, async (next) => {
  qr.value = "";
  if (!next) return;
  try {
    // CommonJS package: its API sits on the default export once bundled.
    const mod = await import("qrcode");
    const encoder = (mod.default ?? mod) as typeof mod.default;
    const svg = await encoder.toString(next.otpauth_uri, { type: "svg", margin: 1, errorCorrectionLevel: "M" });
    if (!svg.startsWith("<svg") && !svg.startsWith("<?xml")) throw new Error("not an svg");
    if (setup.value === next) qr.value = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  } catch {
    qr.value = "";
  }
});

const start = () =>
  run(async () => {
    setup.value = await identityService.startTwoFactor(password.value);
    password.value = "";
    step.value = "setup";
  });

const confirm = () =>
  run(async () => {
    const result = await identityService.confirmTwoFactor(code.value.trim());
    codes.value = result.recovery_codes;
    status.value = result;
    if (auth.account) auth.account = { ...auth.account, two_factor_enabled: true };
    setup.value = null;
    code.value = "";
    step.value = "codes";
    toasts.success(t("settingsCenter.twoFactor.enabled"));
  });

const disable = () =>
  run(async () => {
    status.value = await identityService.disableTwoFactor(password.value, code.value.trim());
    if (auth.account) auth.account = { ...auth.account, two_factor_enabled: false };
    reset();
    toasts.success(t("settingsCenter.twoFactor.disabled"));
  });

const regenerate = () =>
  run(async () => {
    const result = await identityService.newRecoveryCodes(password.value);
    codes.value = result.recovery_codes;
    status.value = result;
    password.value = "";
    step.value = "codes";
  });

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toasts.success(t("settingsCenter.twoFactor.copied"));
  } catch {
    // Clipboard blocked: the text stays selectable on screen.
  }
}

function download() {
  const blob = new Blob([`Tara recovery codes\n\n${codes.value.join("\n")}\n`], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "tara-recovery-codes.txt";
  a.click();
  URL.revokeObjectURL(a.href);
}

const day = (iso: string) => new Intl.DateTimeFormat(locale.value, { dateStyle: "medium" }).format(new Date(iso));

/** The base32 key in groups of four, easier to type. */
const grouped = (key: string) => key.replace(/(.{4})/g, "$1 ").trim();

onMounted(load);
</script>

<template>
  <section id="two-factor" class="card mb-4 scroll-mt-20 p-4" data-testid="two-factor">
    <div class="mb-2 flex items-start justify-between gap-3">
      <div>
        <h2 class="flex items-center gap-2 font-semibold">
          <KeyRound class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" />
          {{ t("settingsCenter.twoFactor.title") }}
        </h2>
        <p class="mt-1 text-sm text-gray-600 dark:text-gray-300">{{ t("settingsCenter.twoFactor.lead") }}</p>
      </div>
      <span
        v-if="status"
        class="shrink-0 rounded-full px-2 py-0.5 text-xs font-medium"
        :class="status.enabled ? 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300' : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300'"
        data-testid="two-factor-status"
      >
        {{ status.enabled ? t("settingsCenter.twoFactor.on") : t("settingsCenter.twoFactor.off") }}
      </span>
    </div>

    <p v-if="failed" class="flex items-center justify-between gap-2 text-sm text-gray-500 dark:text-gray-400">
      {{ t("accountSecurity.loadFailed") }}
      <button type="button" class="btn-ghost text-sm" @click="load">{{ t("states.retry") }}</button>
    </p>
    <p v-else-if="!status" class="text-sm text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</p>

    <template v-else>
      <!-- Recovery codes, shown once -->
      <div v-if="step === 'codes'" class="space-y-3" data-testid="recovery-codes">
        <h3 class="font-semibold">{{ t("settingsCenter.twoFactor.codesTitle") }}</h3>
        <p class="text-sm text-gray-600 dark:text-gray-300">{{ t("settingsCenter.twoFactor.codesLead") }}</p>
        <ul class="grid grid-cols-2 gap-2 rounded-xl bg-gray-50 p-3 font-mono text-sm dark:bg-gray-800/60" dir="ltr">
          <li v-for="c in codes" :key="c">{{ c }}</li>
        </ul>
        <div class="flex flex-wrap gap-2">
          <button type="button" class="btn-soft text-sm" @click="copy(codes.join('\n'))">
            <Copy class="h-4 w-4" aria-hidden="true" />{{ t("settingsCenter.twoFactor.copyCodes") }}
          </button>
          <button type="button" class="btn-soft text-sm" @click="download">
            <Download class="h-4 w-4" aria-hidden="true" />{{ t("settingsCenter.twoFactor.downloadCodes") }}
          </button>
          <button type="button" class="btn-primary text-sm" data-testid="recovery-codes-done" @click="codes = []; reset()">
            {{ t("settingsCenter.twoFactor.doneSaving") }}
          </button>
        </div>
      </div>

      <!-- Setup: key + confirmation code -->
      <form v-else-if="step === 'setup' && setup" class="space-y-3" data-testid="two-factor-setup" @submit.prevent="confirm">
        <h3 class="text-sm font-semibold">{{ t("settingsCenter.twoFactor.step1") }}</h3>
        <div v-if="qr" class="flex flex-col items-start gap-1">
          <img
            :src="qr"
            :alt="t('settingsCenter.twoFactor.qrAlt')"
            width="176"
            height="176"
            class="rounded-lg bg-white p-2 ring-1 ring-gray-200 dark:ring-gray-700"
            data-testid="two-factor-qr"
          />
          <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("settingsCenter.twoFactor.qrHint") }}</p>
        </div>
        <p class="text-sm text-gray-600 dark:text-gray-300">{{ t("settingsCenter.twoFactor.step1Hint") }}</p>
        <div class="flex flex-wrap items-center gap-2">
          <code class="select-all rounded-lg bg-gray-100 px-3 py-2 font-mono text-sm dark:bg-gray-800" dir="ltr" data-testid="two-factor-key">{{ grouped(setup.secret) }}</code>
          <button type="button" class="btn-soft text-sm" @click="copy(setup.secret)">
            <Copy class="h-4 w-4" aria-hidden="true" />{{ t("settingsCenter.twoFactor.copyKey") }}
          </button>
          <a :href="setup.otpauth_uri" class="btn-ghost text-sm font-semibold text-brand-700 dark:text-brand-300">{{ t("settingsCenter.twoFactor.openApp") }}</a>
        </div>
        <label :for="`${uid}-code`" class="block text-sm font-semibold">{{ t("settingsCenter.twoFactor.step2") }}</label>
        <input
          :id="`${uid}-code`"
          v-model="code"
          class="input max-w-[12rem] text-center font-mono tracking-widest"
          dir="ltr"
          inputmode="numeric"
          autocomplete="one-time-code"
          maxlength="8"
          required
        />
        <p v-if="error" class="text-sm text-red-600 dark:text-red-400" role="alert">{{ error }}</p>
        <div class="flex gap-2">
          <button type="submit" class="btn-primary text-sm" :disabled="busy || code.trim().length < 6">{{ t("settingsCenter.twoFactor.confirm") }}</button>
          <button type="button" class="btn-ghost text-sm" @click="reset">{{ t("settingsCenter.twoFactor.cancel") }}</button>
        </div>
      </form>

      <!-- Password re-entry: start setup, or new recovery codes, or turn off (+ code) -->
      <form
        v-else-if="step === 'password' || step === 'regenerate' || step === 'disable'"
        class="space-y-3"
        data-testid="two-factor-reauth"
        @submit.prevent="step === 'password' ? start() : step === 'regenerate' ? regenerate() : disable()"
      >
        <h3 v-if="step === 'disable'" class="text-sm font-semibold">{{ t("settingsCenter.twoFactor.disableTitle") }}</h3>
        <p v-if="step === 'regenerate'" class="text-sm text-gray-600 dark:text-gray-300">{{ t("settingsCenter.twoFactor.newCodesHint") }}</p>
        <div>
          <label :for="`${uid}-password`" class="label">{{ t("settingsCenter.twoFactor.password") }}</label>
          <input :id="`${uid}-password`" v-model="password" type="password" class="input" dir="ltr" autocomplete="current-password" />
          <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ t("settingsCenter.twoFactor.passwordHint") }}</p>
        </div>
        <div v-if="step === 'disable'">
          <label :for="`${uid}-disable-code`" class="label">{{ t("settingsCenter.twoFactor.disableCode") }}</label>
          <input :id="`${uid}-disable-code`" v-model="code" class="input font-mono" dir="ltr" autocomplete="one-time-code" maxlength="32" required />
        </div>
        <p v-if="error" class="text-sm text-red-600 dark:text-red-400" role="alert">{{ error }}</p>
        <div class="flex gap-2">
          <button type="submit" :class="step === 'disable' ? 'btn bg-red-700 text-sm text-white hover:bg-red-800' : 'btn-primary text-sm'" :disabled="busy">
            {{ step === "disable" ? t("settingsCenter.twoFactor.turnOff") : t("settingsCenter.twoFactor.continue") }}
          </button>
          <button type="button" class="btn-ghost text-sm" @click="reset">{{ t("settingsCenter.twoFactor.cancel") }}</button>
        </div>
      </form>

      <!-- Idle -->
      <div v-else class="flex flex-wrap items-center justify-between gap-2">
        <p class="text-sm text-gray-600 dark:text-gray-300">
          <template v-if="status.enabled">
            <span v-if="status.enabled_at">{{ t("settingsCenter.twoFactor.since", { date: day(status.enabled_at) }) }} · </span>
            {{ t("settingsCenter.twoFactor.remaining", { count: status.recovery_codes_remaining }) }}
          </template>
        </p>
        <div class="flex flex-wrap gap-2">
          <template v-if="status.enabled">
            <button type="button" class="btn-soft text-sm" data-testid="two-factor-new-codes" @click="step = 'regenerate'">{{ t("settingsCenter.twoFactor.newCodes") }}</button>
            <button type="button" class="btn-outline text-sm" data-testid="two-factor-turn-off" @click="step = 'disable'">{{ t("settingsCenter.twoFactor.turnOff") }}</button>
          </template>
          <button v-else type="button" class="btn-primary text-sm" data-testid="two-factor-turn-on" @click="step = 'password'">{{ t("settingsCenter.twoFactor.turnOn") }}</button>
        </div>
      </div>
    </template>
  </section>
</template>
