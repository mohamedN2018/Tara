<script setup lang="ts">
import { CheckCircle2, Loader2, Phone } from "lucide-vue-next";
import { onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";

import GoogleSignInButton from "@/components/auth/GoogleSignInButton.vue";
import { pollUntil } from "@/lib/pollUntil";
import { securityErrorKey } from "@/lib/securityErrors";
import {
  identityService,
  type AuthProviders,
  type SecurityOverview,
} from "@/services/identity";
import { useToastStore } from "@/stores/toasts";

const props = defineProps<{ overview: SecurityOverview; providers: AuthProviders }>();
const emit = defineEmits<{ updated: [overview: SecurityOverview] }>();

const { t } = useI18n();
const toasts = useToastStore();
const POLL_MS = 3000;

// ---- Google ----------------------------------------------------------------
const googleBusy = ref(false);
const googleError = ref("");

async function link(credential: string) {
  googleBusy.value = true;
  googleError.value = "";
  try {
    emit("updated", await identityService.linkGoogle(credential));
    toasts.push({ text: t("accountSecurity.google.linked") });
  } catch (e) {
    googleError.value = t(securityErrorKey(e));
  } finally {
    googleBusy.value = false;
  }
}

async function unlink() {
  googleBusy.value = true;
  googleError.value = "";
  try {
    emit("updated", await identityService.unlinkGoogle());
    toasts.push({ text: t("accountSecurity.google.unlinked") });
  } catch (e) {
    googleError.value = t(securityErrorKey(e));
  } finally {
    googleBusy.value = false;
  }
}

// ---- Phone (Telegram) --------------------------------------------------------
const deepLink = ref("");
const phoneError = ref("");
const phoneBusy = ref(false);
let poll: ReturnType<typeof pollUntil> | null = null;

function stopPolling() {
  poll?.stop();
  poll = null;
}

async function startPhone() {
  phoneBusy.value = true;
  phoneError.value = "";
  stopPolling();
  try {
    const started = await identityService.startPhoneVerification();
    deepLink.value = started.deep_link;
    const seen: { latest: SecurityOverview | null } = { latest: null };
    const current = pollUntil(
      async () => {
        seen.latest = await identityService.security();
        return seen.latest.phone_verified;
      },
      { intervalMs: POLL_MS, timeoutMs: started.expires_in * 1000 },
    );
    poll = current;
    const verified = await current.done;
    const cancelled = poll !== current; // cancelPhone() clears `poll` first
    deepLink.value = "";
    if (verified && seen.latest) {
      emit("updated", seen.latest);
      toasts.push({ text: t("accountSecurity.phone.verified") });
    } else if (!cancelled) {
      phoneError.value = t("accountSecurity.phone.expired");
    }
  } catch (e) {
    phoneError.value = t(securityErrorKey(e));
  } finally {
    poll = null;
    phoneBusy.value = false;
  }
}

function cancelPhone() {
  const current = poll;
  poll = null; // tells startPhone this was a cancel, not an expiry
  current?.stop();
  deepLink.value = "";
}

async function removePhone() {
  try {
    emit("updated", await identityService.removePhone());
    toasts.push({ text: t("accountSecurity.phone.removed") });
  } catch (e) {
    toasts.error(e);
  }
}

onBeforeUnmount(cancelPhone);
</script>

<template>
  <div>
    <h3 class="mb-2 text-sm font-semibold">{{ t("accountSecurity.linked.title") }}</h3>
    <ul class="space-y-2">
      <!-- Google -->
      <li
        v-if="props.providers.google.enabled || props.overview.google.linked"
        class="rounded-lg bg-gray-50 px-3 py-2 text-sm dark:bg-gray-800/60"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <span class="min-w-0">
            <span class="block font-medium">{{ t("accountSecurity.google.name") }}</span>
            <span class="block truncate text-xs text-gray-500 dark:text-gray-400">
              <template v-if="props.overview.google.linked">
                {{ t("accountSecurity.google.linkedAs") }}
                <bdi dir="ltr">{{ props.overview.google.email }}</bdi>
              </template>
              <template v-else>{{ t("accountSecurity.google.notLinked") }}</template>
            </span>
          </span>
          <button
            v-if="props.overview.google.linked"
            type="button"
            class="btn-ghost text-sm"
            :disabled="googleBusy || !props.overview.has_password"
            :aria-describedby="!props.overview.has_password ? 'sec-google-last' : undefined"
            @click="unlink"
          >
            {{ t("accountSecurity.google.unlink") }}
          </button>
        </div>
        <p
          v-if="props.overview.google.linked && !props.overview.has_password"
          id="sec-google-last"
          class="mt-1 text-xs text-gray-500 dark:text-gray-400"
        >
          {{ t("accountSecurity.google.lastMethod") }}
        </p>
        <div v-if="!props.overview.google.linked && props.providers.google.enabled" class="mt-2">
          <p class="mb-2 text-xs text-gray-500 dark:text-gray-400">{{ t("accountSecurity.google.linkHint") }}</p>
          <GoogleSignInButton text="continue_with" @credential="link" />
        </div>
        <p v-if="googleError" class="mt-2 text-sm text-red-500" role="alert">{{ googleError }}</p>
      </li>

      <!-- Phone via Telegram -->
      <li
        v-if="props.providers.telegram.enabled || props.overview.phone_verified"
        class="rounded-lg bg-gray-50 px-3 py-2 text-sm dark:bg-gray-800/60"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <span class="flex min-w-0 items-center gap-2">
            <Phone class="h-4 w-4 shrink-0 text-gray-500 dark:text-gray-400" aria-hidden="true" />
            <span class="min-w-0">
              <span class="block font-medium">{{ t("accountSecurity.phone.title") }}</span>
              <span class="block truncate text-xs text-gray-500 dark:text-gray-400">
                <template v-if="props.overview.phone_verified">
                  <CheckCircle2 class="inline h-3.5 w-3.5 text-green-500" aria-hidden="true" />
                  {{ t("accountSecurity.phone.verifiedLabel") }}
                  <bdi dir="ltr">{{ props.overview.phone }}</bdi>
                </template>
                <template v-else>{{ t("accountSecurity.phone.notVerified") }}</template>
              </span>
            </span>
          </span>
          <span class="flex shrink-0 gap-1">
            <button
              v-if="props.providers.telegram.enabled && !deepLink"
              type="button"
              class="btn-soft text-sm"
              :disabled="phoneBusy"
              @click="startPhone"
            >
              {{ props.overview.phone_verified ? t("accountSecurity.phone.change") : t("accountSecurity.phone.verify") }}
            </button>
            <button
              v-if="props.overview.phone_verified && !deepLink"
              type="button"
              class="btn-ghost text-sm"
              @click="removePhone"
            >
              {{ t("accountSecurity.phone.remove") }}
            </button>
          </span>
        </div>

        <div v-if="deepLink" class="mt-2 space-y-2" role="status">
          <p class="text-xs text-gray-600 dark:text-gray-300">{{ t("accountSecurity.phone.instructions") }}</p>
          <div class="flex flex-wrap items-center gap-2">
            <a :href="deepLink" target="_blank" rel="noopener noreferrer" class="btn-primary text-sm">
              {{ t("accountSecurity.phone.openBot") }}
            </a>
            <span class="inline-flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
              <Loader2 class="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              {{ t("accountSecurity.phone.waiting") }}
            </span>
            <button type="button" class="btn-ghost text-sm" @click="cancelPhone">
              {{ t("accountSecurity.phone.cancel") }}
            </button>
          </div>
        </div>
        <p v-if="phoneError" class="mt-2 text-sm text-red-500" role="alert">{{ phoneError }}</p>
      </li>

      <li
        v-if="!props.providers.google.enabled && !props.overview.google.linked && !props.providers.telegram.enabled && !props.overview.phone_verified"
        class="text-sm text-gray-500 dark:text-gray-400"
      >
        {{ t("accountSecurity.linked.none") }}
      </li>
    </ul>
  </div>
</template>
