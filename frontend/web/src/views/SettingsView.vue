<script setup lang="ts">
import { Monitor, Smartphone } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import LocaleToggle from "@/components/common/LocaleToggle.vue";
import NotificationPreferences from "@/components/notifications/NotificationPreferences.vue";
import SecuritySettings from "@/components/settings/SecuritySettings.vue";
import ThemeToggle from "@/components/common/ThemeToggle.vue";
import AppShell from "@/components/layout/AppShell.vue";
import { errorMessage } from "@/lib/errors";
import { relativeTime } from "@/lib/format";
import { canInstall, installApp } from "@/lib/pwa";
import { identityService, type UserSession } from "@/services/identity";
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

// --- Notification preferences: components/notifications/NotificationPreferences.vue ---

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
        <div v-if="canInstall" class="flex items-center justify-between py-2">
          <span class="text-sm">{{ t("settings.installApp") }}</span>
          <button class="btn-primary text-sm" @click="installApp">{{ t("settings.install") }}</button>
        </div>
      </section>

      <!-- Account -->
      <section class="card mb-4 p-4">
        <h2 class="mb-3 font-semibold">{{ t("settings.account") }}</h2>
        <div class="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2 text-sm dark:bg-gray-800/60">
          <span class="min-w-0">
            <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t("settings.email") }}</span>
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

      <!-- Security: password, email, linked accounts, phone -->
      <SecuritySettings />

      <!-- Notification preferences -->
      <section id="notifications" class="card mb-4 scroll-mt-20 p-4">
        <h2 class="mb-3 font-semibold">{{ t("settings.notifications") }}</h2>
        <NotificationPreferences />
      </section>

      <!-- Active sessions -->
      <section class="card mb-4 p-4">
        <h2 class="mb-3 font-semibold">{{ t("settings.sessions") }}</h2>
        <p v-if="sessionsLoading" class="text-sm text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</p>
        <p v-else-if="sessionsError" class="flex items-center justify-between gap-2 text-sm text-gray-500 dark:text-gray-400">
          {{ t("settings.sessionsUnavailable") }}
          <button class="btn-ghost text-sm" @click="loadSessions">{{ t("states.retry") }}</button>
        </p>
        <ul v-else class="space-y-2">
          <li
            v-for="s in sessions"
            :key="s.id"
            class="flex items-center gap-3 rounded-lg bg-gray-50 px-3 py-2 text-sm dark:bg-gray-800/60"
          >
            <component :is="s.platform === 'web' ? Monitor : Smartphone" class="h-5 w-5 shrink-0 text-gray-500 dark:text-gray-400" />
            <span class="min-w-0 flex-1">
              <span class="block truncate font-medium">
                {{ s.platform }} <span v-if="s.is_current" class="text-xs text-brand-600 dark:text-brand-300">· {{ t("settings.thisDevice") }}</span>
              </span>
              <span class="block truncate text-xs text-gray-500 dark:text-gray-400">
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

          <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("settings.fullProfileHint") }}</p>
          <p v-if="message" class="text-sm text-green-600">{{ message }}</p>
          <p v-if="error" class="text-sm text-red-500">{{ error }}</p>

          <button type="submit" class="btn-primary" :disabled="saving">{{ t("settings.save") }}</button>
        </form>
      </section>
    </div>
  </AppShell>
</template>
