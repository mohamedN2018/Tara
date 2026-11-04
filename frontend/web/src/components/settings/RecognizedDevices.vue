<script setup lang="ts">
// "Where you're signed in": recognised devices (GET /me/devices/) and their
// live sessions (GET /auth/sessions/). Removing a device signs it out and
// forgets it, so its next sign-in counts as new (and alerts).
import { Monitor, Smartphone } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { relativeTime } from "@/lib/format";
import { identityService, type RecognizedDevice, type UserSession } from "@/services/identity";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
const toasts = useToastStore();

const devices = ref<RecognizedDevice[]>([]);
const sessions = ref<UserSession[]>([]);
const loading = ref(true);
const failed = ref(false);
const busy = ref<string | null>(null);

async function load() {
  loading.value = true;
  failed.value = false;
  try {
    [devices.value, sessions.value] = await Promise.all([identityService.devices(), identityService.sessions()]);
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

async function removeDevice(id: string) {
  if (busy.value) return;
  busy.value = id;
  try {
    await identityService.removeDevice(id);
    devices.value = devices.value.filter((d) => d.id !== id);
    sessions.value = await identityService.sessions().catch(() => sessions.value);
    toasts.success(t("settingsCenter.devices.removed"));
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = null;
  }
}

async function revoke(id: string) {
  if (busy.value) return;
  busy.value = id;
  try {
    await identityService.revokeSession(id);
    sessions.value = sessions.value.filter((s) => s.id !== id);
    devices.value = await identityService.devices().catch(() => devices.value);
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = null;
  }
}

// A long-lived account collects many sessions: show a few, the rest on request.
const LIMIT = 5;
const showAllDevices = ref(false);
const showAllSessions = ref(false);
const shownDevices = computed(() => (showAllDevices.value ? devices.value : devices.value.slice(0, LIMIT)));
const shownSessions = computed(() => (showAllSessions.value ? sessions.value : sessions.value.slice(0, LIMIT)));

const icon = (platform: string) => (platform === "web" ? Monitor : Smartphone);

onMounted(load);
</script>

<template>
  <section id="devices" class="card mb-4 scroll-mt-20 p-4" data-testid="recognized-devices">
    <h2 class="font-semibold">{{ t("settingsCenter.devices.title") }}</h2>
    <p class="mb-3 mt-1 text-sm text-gray-600 dark:text-gray-300">{{ t("settingsCenter.devices.lead") }}</p>

    <p v-if="loading" class="text-sm text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</p>
    <p v-else-if="failed" class="flex items-center justify-between gap-2 text-sm text-gray-500 dark:text-gray-400">
      {{ t("settingsCenter.devices.failed") }}
      <button type="button" class="btn-ghost text-sm" @click="load">{{ t("states.retry") }}</button>
    </p>
    <p v-else-if="!devices.length" class="text-sm text-gray-500 dark:text-gray-400">{{ t("settingsCenter.devices.empty") }}</p>
    <ul v-else class="space-y-2">
      <li
        v-for="dev in shownDevices"
        :key="dev.id"
        class="flex items-center gap-3 rounded-lg bg-gray-50 px-3 py-2 text-sm dark:bg-gray-800/60"
        data-testid="device-row"
      >
        <component :is="icon(dev.platform)" class="h-5 w-5 shrink-0 text-gray-500 dark:text-gray-400" aria-hidden="true" />
        <span class="min-w-0 flex-1">
          <span class="block truncate font-medium" dir="auto">
            {{ dev.label || t("settingsCenter.devices.unknown") }}
            <span v-if="dev.is_current" class="text-xs text-brand-600 dark:text-brand-300">· {{ t("settingsCenter.devices.current") }}</span>
          </span>
          <span class="block truncate text-xs text-gray-500 dark:text-gray-400">
            {{ dev.ip_region || "—" }} ·
            {{ t("settingsCenter.devices.lastActive", { time: relativeTime(dev.last_seen_at) }) }} ·
            {{ dev.active_sessions ? t("settingsCenter.devices.sessions", dev.active_sessions) : t("settingsCenter.devices.noSessions") }}
          </span>
        </span>
        <button
          v-if="!dev.is_current"
          type="button"
          class="btn-ghost text-sm"
          :disabled="busy === dev.id"
          @click="removeDevice(dev.id)"
        >
          {{ t("settingsCenter.devices.remove") }}
        </button>
      </li>
    </ul>
    <button v-if="!showAllDevices && devices.length > LIMIT" type="button" class="btn-ghost mt-2 w-full text-sm" @click="showAllDevices = true">
      {{ t("settingsCenter.activity.more") }} ({{ devices.length - LIMIT }})
    </button>

    <template v-if="!loading && !failed && sessions.length">
      <h3 class="mb-2 mt-5 text-sm font-semibold">{{ t("settings.sessions") }}</h3>
      <ul class="space-y-2" data-testid="active-sessions">
        <li
          v-for="s in shownSessions"
          :key="s.id"
          class="flex items-center gap-3 rounded-lg bg-gray-50 px-3 py-2 text-sm dark:bg-gray-800/60"
        >
          <component :is="icon(s.platform)" class="h-5 w-5 shrink-0 text-gray-500 dark:text-gray-400" aria-hidden="true" />
          <span class="min-w-0 flex-1">
            <span class="block truncate font-medium">
              {{ s.platform }} <span v-if="s.is_current" class="text-xs text-brand-600 dark:text-brand-300">· {{ t("settings.thisDevice") }}</span>
            </span>
            <span class="block truncate text-xs text-gray-500 dark:text-gray-400">{{ s.ip_region || "—" }} · {{ relativeTime(s.last_seen_at) }}</span>
          </span>
          <button v-if="!s.is_current" type="button" class="btn-ghost text-sm" :disabled="busy === s.id" @click="revoke(s.id)">
            {{ t("settings.revoke") }}
          </button>
        </li>
      </ul>
      <button v-if="!showAllSessions && sessions.length > LIMIT" type="button" class="btn-ghost mt-2 w-full text-sm" @click="showAllSessions = true">
        {{ t("settingsCenter.activity.more") }} ({{ sessions.length - LIMIT }})
      </button>
    </template>
  </section>
</template>
