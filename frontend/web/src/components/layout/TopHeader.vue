<script setup lang="ts">
import { Bell, LogOut, Menu } from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import LocaleToggle from "@/components/common/LocaleToggle.vue";
import ThemeToggle from "@/components/common/ThemeToggle.vue";
import { useAuthStore } from "@/stores/auth";
import { useNotificationStore } from "@/stores/notifications";
import { useUiStore } from "@/stores/ui";

const { t } = useI18n();
const router = useRouter();
const auth = useAuthStore();
const ui = useUiStore();
const notifications = useNotificationStore();

async function logout() {
  await auth.logout();
  router.push({ name: "login" });
}
</script>

<template>
  <header
    class="sticky top-0 z-30 flex items-center gap-3 border-b border-gray-200 bg-white/80 px-4 py-2.5 backdrop-blur dark:border-gray-800 dark:bg-gray-950/80"
  >
    <button class="btn-ghost px-2 lg:hidden" @click="ui.sidebarOpen = !ui.sidebarOpen">
      <Menu class="h-5 w-5" />
    </button>

    <span class="text-lg font-extrabold text-brand-600 lg:hidden">{{ t("app.name") }}</span>

    <div class="flex-1" />

    <RouterLink to="/notifications" class="btn-ghost relative px-2" :aria-label="t('nav.notifications')">
      <Bell class="h-5 w-5" />
      <span
        v-if="notifications.unread > 0"
        class="absolute -end-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white"
      >
        {{ notifications.unread > 99 ? "99+" : notifications.unread }}
      </span>
    </RouterLink>

    <LocaleToggle />
    <ThemeToggle />

    <button class="btn-ghost px-2" :title="t('nav.logout')" @click="logout">
      <LogOut class="h-5 w-5" />
    </button>
  </header>
</template>
