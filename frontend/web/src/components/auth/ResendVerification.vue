<script setup lang="ts">
// "Resend verification email" (POST /auth/verify-email/resend/). The server
// answers the same way whether or not the address exists, so this only says a
// link is on its way "if this address needs verifying". A cooldown stops
// repeated clicks; the server throttles too.
import { MailCheck } from "lucide-vue-next";
import { computed, onBeforeUnmount, ref, useId } from "vue";
import { useI18n } from "vue-i18n";

import { identityService } from "@/services/identity";

const props = withDefaults(defineProps<{ email?: string; compact?: boolean }>(), { email: "", compact: false });

const COOLDOWN_SECONDS = 60;
const { t } = useI18n();
const id = useId();
const typed = ref("");
const busy = ref(false);
const sent = ref(false);
const failed = ref(false);
const wait = ref(0);
let timer: number | undefined;

const address = computed(() => (props.email || typed.value).trim());

function tick() {
  wait.value -= 1;
  if (wait.value <= 0) window.clearInterval(timer);
}

async function resend() {
  if (busy.value || wait.value > 0 || !address.value) return;
  busy.value = true;
  failed.value = false;
  try {
    await identityService.resendVerification(address.value);
    sent.value = true;
    wait.value = COOLDOWN_SECONDS;
    window.clearInterval(timer);
    timer = window.setInterval(tick, 1000);
  } catch {
    failed.value = true;
  } finally {
    busy.value = false;
  }
}

onBeforeUnmount(() => window.clearInterval(timer));
</script>

<template>
  <div :class="compact ? 'inline-flex flex-col items-start gap-1' : 'space-y-2'" data-testid="resend-verification">
    <div v-if="!email">
      <label :for="`${id}-email`" class="label">{{ t("settingsCenter.resend.emailLabel") }}</label>
      <input :id="`${id}-email`" v-model="typed" type="email" dir="ltr" class="input" autocomplete="email" maxlength="254" />
    </div>
    <button
      type="button"
      :class="compact ? 'btn-ghost px-2 py-1 text-sm font-semibold text-brand-700 dark:text-brand-300' : 'btn-outline w-full'"
      :disabled="busy || wait > 0 || !address"
      data-testid="resend-verification-button"
      @click="resend"
    >
      <MailCheck class="h-4 w-4" aria-hidden="true" />
      {{ wait > 0 ? t("settingsCenter.resend.wait", { seconds: wait }) : t("settingsCenter.resend.action") }}
    </button>
    <p v-if="sent" class="text-xs text-green-700 dark:text-green-300" role="status">{{ t("settingsCenter.resend.sent") }}</p>
    <p v-else-if="failed" class="text-xs text-red-600 dark:text-red-400" role="alert">{{ t("settingsCenter.resend.failed") }}</p>
  </div>
</template>
