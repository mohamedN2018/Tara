<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { pushRegistration, pushSupported, subscriptionJson, vapidKeyBytes } from "@/lib/pwa";
import { notificationService } from "@/services/notification";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
const toasts = useToastStore();

type State = "loading" | "unsupported" | "unavailable" | "denied" | "off" | "on";
const state = ref<State>("loading");
const busy = ref(false);
let publicKey = "";

async function refresh() {
  if (!pushSupported()) {
    state.value = "unsupported";
    return;
  }
  try {
    const config = await notificationService.pushConfig();
    publicKey = config.public_key;
    const registration = await pushRegistration();
    if (!config.enabled || !registration) {
      state.value = "unavailable";
    } else if (Notification.permission === "denied") {
      state.value = "denied";
    } else {
      state.value = (await registration.pushManager.getSubscription()) ? "on" : "off";
    }
  } catch {
    state.value = "unavailable";
  }
}

async function enable() {
  busy.value = true;
  try {
    if ((await Notification.requestPermission()) !== "granted") {
      state.value = Notification.permission === "denied" ? "denied" : "off";
      return;
    }
    const registration = await pushRegistration();
    if (!registration) return;
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: vapidKeyBytes(publicKey),
    });
    try {
      await notificationService.registerWebPush(subscriptionJson(subscription));
    } catch (e) {
      await subscription.unsubscribe(); // Don't claim a subscription the server refused.
      throw e;
    }
    state.value = "on";
  } catch (e) {
    toasts.error(e, { unknown: "settings.pushFailed", request_failed: "settings.pushFailed" });
  } finally {
    busy.value = false;
  }
}

async function disable() {
  busy.value = true;
  try {
    const registration = await pushRegistration();
    const subscription = await registration?.pushManager.getSubscription();
    if (subscription) {
      await notificationService.unregisterWebPush(subscription.endpoint);
      await subscription.unsubscribe();
    }
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
      <span v-if="state === 'unsupported'" class="block text-xs text-gray-500">{{ t("settings.pushUnsupported") }}</span>
      <span v-else-if="state === 'unavailable'" class="block text-xs text-gray-500">{{ t("settings.pushUnavailable") }}</span>
      <span v-else-if="state === 'denied'" class="block text-xs text-gray-500">{{ t("settings.pushDenied") }}</span>
      <span v-else-if="state === 'on'" class="block text-xs text-green-600">{{ t("settings.pushOn") }}</span>
    </span>
    <button v-if="state === 'off'" class="btn-primary shrink-0 text-sm" :disabled="busy" @click="enable">{{ t("settings.pushEnable") }}</button>
    <button v-else-if="state === 'on'" class="btn-ghost shrink-0 text-sm" :disabled="busy" @click="disable">{{ t("settings.pushDisable") }}</button>
  </div>
</template>
