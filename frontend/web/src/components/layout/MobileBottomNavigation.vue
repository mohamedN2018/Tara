<script setup lang="ts">
import { Bell, Home, MessageCircle, Search, Users } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

import { useNotificationStore } from "@/stores/notifications";

const { t } = useI18n();
const notifications = useNotificationStore();

const items = [
  { name: "home", route: "/home", icon: Home, label: "nav.home" },
  { name: "friends", route: "/friends", icon: Users, label: "nav.friends" },
  { name: "messages", route: "/messages", icon: MessageCircle, label: "nav.messages" },
  { name: "notifications", route: "/notifications", icon: Bell, label: "nav.notifications" },
  { name: "search", route: "/search", icon: Search, label: "nav.search" },
];
</script>

<template>
  <nav
    class="fixed inset-x-0 bottom-0 z-30 flex items-stretch border-t border-gray-200 bg-white pb-[env(safe-area-inset-bottom)] dark:border-gray-800 dark:bg-gray-900 lg:hidden"
    :aria-label="t('nav.home')"
  >
    <RouterLink
      v-for="item in items"
      :key="item.name"
      :to="item.route"
      class="relative flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-medium text-gray-500"
      active-class="text-brand-600"
      :aria-label="t(item.label)"
    >
      <component :is="item.icon" class="h-5 w-5" />
      <span
        v-if="item.name === 'notifications' && notifications.unread > 0"
        class="absolute end-[28%] top-1 h-2 w-2 rounded-full bg-red-500"
      />
      {{ t(item.label) }}
    </RouterLink>
  </nav>
</template>
