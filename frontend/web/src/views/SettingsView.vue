<script setup lang="ts">
import { Monitor, Smartphone } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import LocaleToggle from "@/components/common/LocaleToggle.vue";
import ThemeToggle from "@/components/common/ThemeToggle.vue";
import AppShell from "@/components/layout/AppShell.vue";
import { errorMessage } from "@/lib/errors";
import { relativeTime } from "@/lib/format";
import { identityService, type UserSession } from "@/services/identity";
import { notificationService, type NotificationPreferences, type NotificationPrefs } from "@/services/notification";
import { profileService } from "@/services/profile";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
const auth = useAuthStore();
const toasts = useToastStore();

// --- Profile quick-edit ---
const form = ref({
  display_name: auth.profile?.display_name ?? "",
  intro: auth.profile?.intro ?? "",
  bio: auth.profile?.bio ?? "",
  city: auth.profile?.city ?? "",
  country: auth.profile?.country ?? "",
});
const saving = ref(false);
const message = ref("");
const error = ref("");

async function save() {
  saving.value = true;
  message.value = "";
  error.value = "";
  try {
    const updated = await profileService.update(form.value);
    auth.profile = updated;
    message.value = t("settings.saved");
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    saving.value = false;
  }
}

// --- Notification preferences ---
const NOTIF_KINDS = [
  "post.reaction",
  "post.comment",
  "comment.reply",
  "post.share",
  "mention",
  "friend.request",
  "friend.accepted",
  "follow",
  "message",
  "listing.status",
];
const CHANNEL = "in_app";
const prefs = ref<NotificationPrefs>({});
const quiet = ref<NotificationPreferences["quiet_hours"]>({});
const prefsLoading = ref(true);
const prefsError = ref(false);

const isEnabled = (kind: string) => prefs.value[kind]?.[CHANNEL] !== false; // default on

async function loadPrefs() {
  prefsLoading.value = true;
  prefsError.value = false;
  try {
    const p = await notificationService.getPreferences();
    // PATCH replaces `prefs` whole, so other channels must be kept and sent back.
    prefs.value = Object.fromEntries(
      Object.entries(p.prefs).filter(([, channels]) => channels && typeof channels === "object"),
    );
    quiet.value = p.quiet_hours ?? {};
  } catch {
    // Never show (or save) guessed defaults over the user's real choices.
    prefsError.value = true;
  } finally {
    prefsLoading.value = false;
  }
}

async function togglePref(kind: string, enabled: boolean) {
  const previous = prefs.value;
  prefs.value = { ...previous, [kind]: { ...previous[kind], [CHANNEL]: enabled } };
  try {
    await notificationService.updatePreferences({ prefs: prefs.value });
  } catch (e) {
    prefs.value = previous;
    toasts.error(e);
  }
}

async function saveQuietHours() {
  const { start, end } = quiet.value;
  if (!start !== !end) return; // Half a window: wait for the other end.
  if (start && start === end) {
    toasts.push({ text: t("settings.quietSameTime"), icon: "error" });
    return;
  }
  try {
    await notificationService.updatePreferences({
      quiet_hours: start
        ? { start, end, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }
        : {},
    });
  } catch (e) {
    toasts.error(e);
  }
}

function clearQuietHours() {
  quiet.value = {};
  void saveQuietHours();
}

// --- Active sessions ---
const sessions = ref<UserSession[]>([]);
const sessionsLoading = ref(true);
const sessionsError = ref(false);

async function loadSessions() {
  sessionsLoading.value = true;
  sessionsError.value = false;
  try {
    sessions.value = await identityService.sessions();
  } catch {
    sessionsError.value = true;
  } finally {
    sessionsLoading.value = false;
  }
}
async function revoke(id: string) {
  try {
    await identityService.revokeSession(id);
    sessions.value = sessions.value.filter((s) => s.id !== id);
  } catch (e) {
    toasts.error(e);
  }
}

onMounted(() => {
  loadPrefs();
  loadSessions();
});
</script>

<template>
  <AppShell>
    <div class="mx-auto w-full max-w-[640px]">
      <h1 class="mb-4 text-xl font-bold">{{ t("settings.title") }}</h1>

      <!-- Appearance -->
      <section class="card mb-4 p-4">
        <h2 class="mb-3 font-semibold">{{ t("settings.appearance") }}</h2>
        <div class="flex items-center justify-between py-2">
          <span class="text-sm">{{ t("settings.theme") }}</span>
          <ThemeToggle />
        </div>
        <div class="flex items-center justify-between py-2">
          <span class="text-sm">{{ t("settings.language") }}</span>
          <LocaleToggle />
        </div>
      </section>

      <!-- Account -->
      <section class="card mb-4 p-4">
        <h2 class="mb-3 font-semibold">{{ t("settings.account") }}</h2>
        <div class="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2 text-sm dark:bg-gray-800/60">
          <span class="min-w-0">
            <span class="block text-xs text-gray-400">{{ t("settings.email") }}</span>
            <span class="block truncate">{{ auth.account?.email || "—" }}</span>
          </span>
          <span
            class="shrink-0 rounded-full px-2 py-0.5 text-xs font-medium"
            :class="auth.account?.email_verified
              ? 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300'
              : 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300'"
          >
            {{ auth.account?.email_verified ? t("settings.verified") : t("settings.unverified") }}
          </span>
        </div>
      </section>

      <!-- Notification preferences -->
      <section class="card mb-4 p-4">
        <h2 class="mb-3 font-semibold">{{ t("settings.notifications") }}</h2>
        <p v-if="prefsLoading" class="text-sm text-gray-400">{{ t("states.loading") }}</p>
        <p v-else-if="prefsError" class="flex items-center justify-between gap-2 text-sm text-gray-500">
          {{ t("settings.prefsUnavailable") }}
          <button class="btn-ghost text-sm" @click="loadPrefs">{{ t("states.retry") }}</button>
        </p>
        <div v-else class="divide-y divide-gray-100 dark:divide-gray-800">
          <label v-for="k in NOTIF_KINDS" :key="k" class="flex cursor-pointer items-center justify-between py-2.5">
            <span class="text-sm">{{ t(`settings.notif.${k.replace(".", "_")}`) }}</span>
            <input
              type="checkbox"
              class="h-5 w-5 rounded accent-brand-600"
              :checked="isEnabled(k)"
              @change="togglePref(k, ($event.target as HTMLInputElement).checked)"
            />
          </label>
          <div class="pt-3">
            <p class="mb-2 text-sm font-medium">{{ t("settings.quietHours") }}</p>
            <div class="flex items-center gap-3 text-sm">
              <label class="flex items-center gap-1.5">
                <span class="text-gray-500">{{ t("settings.quietFrom") }}</span>
                <input v-model="quiet.start" type="time" class="input w-auto" @change="saveQuietHours" />
              </label>
              <label class="flex items-center gap-1.5">
                <span class="text-gray-500">{{ t("settings.quietTo") }}</span>
                <input v-model="quiet.end" type="time" class="input w-auto" @change="saveQuietHours" />
              </label>
              <button v-if="quiet.start || quiet.end" class="btn-ghost text-sm" @click="clearQuietHours">
                {{ t("settings.quietClear") }}
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- Active sessions -->
      <section class="card mb-4 p-4">
        <h2 class="mb-3 font-semibold">{{ t("settings.sessions") }}</h2>
        <p v-if="sessionsLoading" class="text-sm text-gray-400">{{ t("states.loading") }}</p>
        <p v-else-if="sessionsError" class="flex items-center justify-between gap-2 text-sm text-gray-500">
          {{ t("settings.sessionsUnavailable") }}
          <button class="btn-ghost text-sm" @click="loadSessions">{{ t("states.retry") }}</button>
        </p>
        <ul v-else class="space-y-2">
          <li
            v-for="s in sessions"
            :key="s.id"
            class="flex items-center gap-3 rounded-lg bg-gray-50 px-3 py-2 text-sm dark:bg-gray-800/60"
          >
            <component :is="s.platform === 'web' ? Monitor : Smartphone" class="h-5 w-5 shrink-0 text-gray-400" />
            <span class="min-w-0 flex-1">
              <span class="block truncate font-medium">
                {{ s.platform }} <span v-if="s.is_current" class="text-xs text-brand-600">· {{ t("settings.thisDevice") }}</span>
              </span>
              <span class="block truncate text-xs text-gray-400">
                {{ s.ip_region || "—" }} · {{ relativeTime(s.last_seen_at) }}
              </span>
            </span>
            <button v-if="!s.is_current" class="btn-ghost text-sm" @click="revoke(s.id)">
              {{ t("settings.revoke") }}
            </button>
          </li>
        </ul>
      </section>

      <!-- Profile quick-edit -->
      <section class="card p-4">
        <h2 class="mb-3 font-semibold">{{ t("profile.editProfile") }}</h2>
        <form class="space-y-3" @submit.prevent="save">
          <div>
            <label for="settings-name" class="mb-1 block text-sm font-medium">{{ t("auth.displayName") }}</label>
            <input id="settings-name" v-model="form.display_name" class="input" dir="auto" />
          </div>
          <div>
            <label for="settings-intro" class="mb-1 block text-sm font-medium">{{ t("settings.intro") }}</label>
            <input id="settings-intro" v-model="form.intro" class="input" dir="auto" maxlength="160" />
          </div>
          <div>
            <label for="settings-bio" class="mb-1 block text-sm font-medium">{{ t("profile.bioLabel") }}</label>
            <textarea id="settings-bio" v-model="form.bio" class="input min-h-[80px] resize-none" dir="auto" />
          </div>
          <div class="grid grid-cols-2 gap-3">
            <input v-model="form.city" class="input" dir="auto" :aria-label="t('profile.city')" :placeholder="t('profile.city')" />
            <input v-model="form.country" class="input" dir="auto" :aria-label="t('profile.country')" :placeholder="t('profile.country')" />
          </div>

          <p class="text-xs text-gray-400">{{ t("settings.fullProfileHint") }}</p>
          <p v-if="message" class="text-sm text-green-600">{{ message }}</p>
          <p v-if="error" class="text-sm text-red-500">{{ error }}</p>

          <button type="submit" class="btn-primary" :disabled="saving">{{ t("settings.save") }}</button>
        </form>
      </section>
    </div>
  </AppShell>
</template>
