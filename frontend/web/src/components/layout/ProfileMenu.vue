<script setup lang="ts">
import { ChevronDown, LogOut, Settings } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import LocaleToggle from "@/components/common/LocaleToggle.vue";
import ThemeToggle from "@/components/common/ThemeToggle.vue";
import UserAvatar from "@/components/common/UserAvatar.vue";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useAuthStore } from "@/stores/auth";
import { usePresenceStore } from "@/stores/presence";

const { t } = useI18n();
const auth = useAuthStore();
const presence = usePresenceStore();

const open = ref(false);
useEscapeKey(open, () => (open.value = false));
const displayName = () =>
  auth.profile?.display_name || auth.account?.email?.split("@")[0] || "?";

async function logout() {
  open.value = false;
  await auth.logout();
}
</script>

<template>
  <div class="relative">
    <button
      class="flex items-center gap-1 rounded-full p-0.5 transition hover:bg-gray-100 dark:hover:bg-gray-800"
      :aria-label="t('nav.profile')"
      aria-haspopup="menu"
      :aria-expanded="open"
      @click="open = !open"
    >
      <span class="relative">
        <UserAvatar :name="displayName()" :media-id="auth.profile?.avatar_media_id" :size="34" />
        <span
          class="absolute -end-0 -bottom-0 h-2.5 w-2.5 rounded-full border-2 border-white dark:border-gray-900"
          :class="presence.connected ? 'bg-green-500' : 'bg-gray-400'"
          :title="presence.connected ? t('presence.online') : t('presence.offline')"
        />
      </span>
      <ChevronDown class="hidden h-4 w-4 text-gray-500 sm:block dark:text-gray-400" />
    </button>

    <template v-if="open">
      <div class="fixed inset-0 z-40" @click="open = false" />
      <div
        class="popover absolute end-0 z-50 mt-2 w-64 overflow-hidden p-1.5"
        role="menu"
      >
        <RouterLink
          v-if="auth.profile"
          :to="`/u/${auth.profile.handle}`"
          class="flex items-center gap-3 rounded-lg p-2 transition hover:bg-gray-100 dark:hover:bg-gray-800"
          role="menuitem"
          @click="open = false"
        >
          <UserAvatar :name="displayName()" :media-id="auth.profile.avatar_media_id" :size="40" />
          <span class="min-w-0">
            <span class="block truncate text-sm font-semibold">{{ auth.profile.display_name }}</span>
            <span class="block truncate text-xs text-gray-500 dark:text-gray-400">@{{ auth.profile.handle }}</span>
          </span>
        </RouterLink>
        <div
          v-else
          class="flex items-center gap-3 rounded-lg p-2 text-sm text-gray-600 dark:text-gray-300"
        >
          <UserAvatar :name="displayName()" :size="40" />
          <span class="truncate">{{ auth.account?.email }}</span>
        </div>

        <div class="my-1 border-t border-gray-100 dark:border-gray-800" />

        <RouterLink
          to="/settings"
          class="flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800"
          role="menuitem"
          @click="open = false"
        >
          <Settings class="h-4 w-4" /> {{ t("nav.settings") }}
        </RouterLink>

        <div class="flex items-center justify-between rounded-lg px-3 py-2 text-sm">
          <span>{{ t("settings.theme") }}</span><ThemeToggle />
        </div>
        <div class="flex items-center justify-between rounded-lg px-3 py-2 text-sm">
          <span>{{ t("settings.language") }}</span><LocaleToggle />
        </div>

        <div class="my-1 border-t border-gray-100 dark:border-gray-800" />

        <button
          class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-start text-sm text-red-600 transition hover:bg-red-50 dark:hover:bg-red-950/40"
          role="menuitem"
          @click="logout"
        >
          <LogOut class="h-4 w-4" /> {{ t("nav.logout") }}
        </button>
      </div>
    </template>
  </div>
</template>
