<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { disablePush, enablePush, pushActiveFor, pushRegistration, pushSupported } from "@/lib/pwa";
import { notificationService } from "@/services/notification";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
const toasts = useToastStore();
const auth = useAuthStore();

type State = "loading" | "unsupported" | "unavailable" | "denied" | "off" | "on";
const state = ref<State>("loading");
const busy = ref(false);

async function refresh() {
  if (!pushSupported()) {
    state.value = "unsupported";
    return;
  }
  try {
    const config = await notificationService.pushConfig();
    const registration = await pushRegistration();
    if (!config.enabled || !registration) {
      state.value = "unavailable";
    } else if (Notification.permission === "denied") {
      state.value = "denied";
    } else {
      // A subscription another account left in this browser does not count as "on".
      state.value = (await pushActiveFor(auth.account?.id)) ? "on" : "off";
    }
  } catch {
    state.value = "unavailable";
  }
}

async function enable() {
  const me = auth.account?.id;
  if (!me) return;
  busy.value = true;
  try {
    state.value = await enablePush(me); // asks for permission: this is the user's click
  } catch (e) {
    toasts.error(e, { unknown: "settings.pushFailed", request_failed: "settings.pushFailed" });
  } finally {
    busy.value = false;
  }
}

async function disable() {
  const me = auth.account?.id;
  if (!me) return;
  busy.value = true;
  try {
    await disablePush(me);
    state.value = "off";
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

onMounted(refresh);
</script>

<template>
  <div class="flex items-center justify-between gap-3 py-2" data-testid="push-settings">
    <span class="min-w-0">
      <span class="block text-sm">{{ t("settings.push") }}</span>
      <span v-if="state === 'unsupported'" class="block text-xs text-gray-500 dark:text-gray-400">{{ t("settings.pushUnsupported") }}</span>
      <span v-else-if="state === 'unavailable'" class="block text-xs text-gray-500 dark:text-gray-400">{{ t("settings.pushUnavailable") }}</span>
      <span v-else-if="state === 'denied'" class="block text-xs text-gray-500 dark:text-gray-400">{{ t("settings.pushDenied") }}</span>
      <span v-else-if="state === 'on'" class="block text-xs text-green-600 dark:text-green-400">{{ t("settings.pushOn") }}</span>
    </span>
    <button v-if="state === 'off'" class="btn-primary shrink-0 text-sm" :disabled="busy" @click="enable">{{ t("settings.pushEnable") }}</button>
    <button v-else-if="state === 'on'" class="btn-ghost shrink-0 text-sm" :disabled="busy" @click="disable">{{ t("settings.pushDisable") }}</button>
  </div>
</template>
