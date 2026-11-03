<script setup lang="ts">
// Settings → Notifications: browser push for this device, per-kind in-app and push
// toggles grouped by category (the server's kind registry supplies the defaults),
// quiet hours, message previews and the optional sound ping.
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import PushSettings from "@/components/common/PushSettings.vue";
import { CATEGORY_ORDER, kindKey } from "@/components/notifications/kinds";
import { setSoundEnabled, soundEnabled } from "@/lib/sound";
import {
  notificationService,
  type NotificationChannel,
  type NotificationKindInfo,
  type NotificationPrefs,
  type QuietHours,
  withSwitch,
} from "@/services/notification";
import { useNotificationStore } from "@/stores/notifications";
import { useToastStore } from "@/stores/toasts";

const { t, te } = useI18n();
const toasts = useToastStore();
const store = useNotificationStore();

const CHANNELS: NotificationChannel[] = ["in_app", "push"];

const kinds = ref<NotificationKindInfo[]>([]);
const prefs = ref<NotificationPrefs>({});
const quiet = ref<QuietHours>({});
const previews = ref(true);
const sound = ref(soundEnabled());
const loading = ref(true);
const failed = ref(false);

const groups = computed(() =>
  CATEGORY_ORDER.map((category) => ({
    category,
    kinds: kinds.value.filter((k) => k.category === category),
  })).filter((g) => g.kinds.length),
);

function effective(kind: NotificationKindInfo, channel: NotificationChannel): boolean {
  const own = prefs.value[kind.kind]?.[channel];
  if (typeof own === "boolean") return own;
  const inherited = prefs.value[kind.category]?.[channel];
  if (typeof inherited === "boolean") return inherited;
  return kind.defaults[channel];
}

const kindLabel = (kind: string) => {
  const key = `settings.notif.${kindKey(kind)}`;
  return te(key) ? t(key) : kind;
};

async function load() {
  loading.value = true;
  failed.value = false;
  try {
    const [registry, saved] = await Promise.all([notificationService.registry(), notificationService.getPreferences()]);
    kinds.value = registry.kinds;
    prefs.value = saved.prefs;
    quiet.value = saved.quiet_hours;
    previews.value = saved.message_previews;
  } catch {
    // Never show (or save) guessed defaults over the user's real choices.
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

// Only this one switch is sent, applied from the answer and rolled back on
// failure: toggles in flight together never overwrite each other.
async function toggle(kind: NotificationKindInfo, channel: NotificationChannel, enabled: boolean) {
  const previous = prefs.value[kind.kind]?.[channel];
  prefs.value = withSwitch(prefs.value, kind.kind, channel, enabled);
  try {
    const saved = (await notificationService.updatePreferences({ prefs: { [kind.kind]: { [channel]: enabled } } })).prefs;
    const stored = saved[kind.kind]?.[channel];
    if (typeof stored === "boolean") prefs.value = withSwitch(prefs.value, kind.kind, channel, stored);
  } catch (e) {
    prefs.value = withSwitch(prefs.value, kind.kind, channel, previous);
    toasts.error(e);
  }
}

async function togglePreviews(enabled: boolean) {
  previews.value = enabled;
  try {
    await notificationService.updatePreferences({ message_previews: enabled });
  } catch (e) {
    previews.value = !enabled;
    toasts.error(e);
  }
}

function toggleSound(enabled: boolean) {
  sound.value = enabled;
  setSoundEnabled(enabled);
}

async function saveQuietHours() {
  const { start, end } = quiet.value;
  if (!start !== !end) return; // Half a window: wait for the other end.
  if (start && start === end) {
    toasts.push({ text: t("settings.quietSameTime"), icon: "error" });
    return;
  }
  const value: QuietHours = start ? { start, end, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone } : {};
  try {
    await notificationService.updatePreferences({ quiet_hours: value });
    store.quietHours = value; // the sound ping follows the new window at once
  } catch (e) {
    toasts.error(e);
  }
}

function clearQuietHours() {
  quiet.value = {};
  void saveQuietHours();
}

onMounted(load);
</script>

<template>
  <div data-testid="notification-preferences">
    <PushSettings />

    <label class="flex cursor-pointer items-center justify-between gap-3 py-2">
      <span class="min-w-0">
        <span class="block text-sm">{{ t("notifications.prefs.sound") }}</span>
        <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t("notifications.prefs.soundHint") }}</span>
      </span>
      <input
        type="checkbox"
        class="h-5 w-5 shrink-0 rounded accent-brand-600"
        :checked="sound"
        data-testid="notification-sound"
        @change="toggleSound(($event.target as HTMLInputElement).checked)"
      />
    </label>

    <p v-if="loading" class="py-2 text-sm text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</p>
    <p v-else-if="failed" class="flex items-center justify-between gap-2 py-2 text-sm text-gray-500 dark:text-gray-400">
      {{ t("settings.prefsUnavailable") }}
      <button class="btn-ghost text-sm" @click="load">{{ t("states.retry") }}</button>
    </p>
    <template v-else>
      <label class="flex cursor-pointer items-center justify-between gap-3 py-2">
        <span class="min-w-0">
          <span class="block text-sm">{{ t("notifications.prefs.previews") }}</span>
          <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t("notifications.prefs.previewsHint") }}</span>
        </span>
        <input
          type="checkbox"
          class="h-5 w-5 shrink-0 rounded accent-brand-600"
          :checked="previews"
          @change="togglePreviews(($event.target as HTMLInputElement).checked)"
        />
      </label>

      <div v-for="group in groups" :key="group.category" class="mt-3">
        <div class="flex items-center justify-between gap-3 border-b border-gray-100 pb-1.5 dark:border-gray-800">
          <h3 class="text-xs font-bold uppercase tracking-wide text-gray-500 dark:text-gray-400">
            {{ t(`notifications.categories.${group.category}`) }}
          </h3>
          <span class="flex w-28 shrink-0 justify-around text-[11px] font-semibold text-gray-500 dark:text-gray-400">
            <span v-for="ch in CHANNELS" :key="ch">{{ t(`notifications.prefs.${ch}`) }}</span>
          </span>
        </div>
        <div class="divide-y divide-gray-100 dark:divide-gray-800">
          <div v-for="k in group.kinds" :key="k.kind" class="flex items-center justify-between gap-3 py-2">
            <span class="min-w-0 text-sm">{{ kindLabel(k.kind) }}</span>
            <span class="flex w-28 shrink-0 justify-around">
              <input
                v-for="ch in CHANNELS"
                :key="ch"
                type="checkbox"
                class="h-5 w-5 cursor-pointer rounded accent-brand-600"
                :checked="effective(k, ch)"
                :aria-label="`${kindLabel(k.kind)} · ${t(`notifications.prefs.${ch}`)}`"
                :data-testid="`pref-${k.kind}-${ch}`"
                @change="toggle(k, ch, ($event.target as HTMLInputElement).checked)"
              />
            </span>
          </div>
        </div>
      </div>

      <div class="mt-4 border-t border-gray-100 pt-3 dark:border-gray-800">
        <p class="mb-1 text-sm font-medium">{{ t("settings.quietHours") }}</p>
        <p class="mb-2 text-xs text-gray-500 dark:text-gray-400">{{ t("notifications.prefs.quietHint") }}</p>
        <div class="flex flex-wrap items-center gap-3 text-sm">
          <label class="flex items-center gap-1.5">
            <span class="text-gray-500 dark:text-gray-400">{{ t("settings.quietFrom") }}</span>
            <input v-model="quiet.start" type="time" class="input w-auto" dir="ltr" @change="saveQuietHours" />
          </label>
          <label class="flex items-center gap-1.5">
            <span class="text-gray-500 dark:text-gray-400">{{ t("settings.quietTo") }}</span>
            <input v-model="quiet.end" type="time" class="input w-auto" dir="ltr" @change="saveQuietHours" />
          </label>
          <button v-if="quiet.start || quiet.end" class="btn-ghost text-sm" @click="clearQuietHours">
            {{ t("settings.quietClear") }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
