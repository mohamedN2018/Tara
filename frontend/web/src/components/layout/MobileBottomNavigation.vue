<script setup lang="ts">
import { Bell, Clapperboard, Home, Menu, Plus, Users } from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { useNotificationStore } from "@/stores/notifications";
import { useUiStore } from "@/stores/ui";

const { t } = useI18n();
const router = useRouter();
const ui = useUiStore();
const notifications = useNotificationStore();

// Home, Friends | Create | Reels, Notifications, Menu (the menu is its own page on mobile).
const start = [
  { name: "home", route: "/home", icon: Home, label: "nav.home" },
  { name: "friends", route: "/friends", icon: Users, label: "nav.friends" },
];
const end = [
  { name: "reels", route: "/reels", icon: Clapperboard, label: "menu.items.reels" },
  { name: "notifications", route: "/notifications", icon: Bell, label: "nav.notifications" },
  { name: "menu", route: "/menu", icon: Menu, label: "nav.menu" },
];

function createPost() {
  ui.requestCompose();
  router.push("/home");
}
</script>

<template>
  <nav
    class="fixed inset-x-0 bottom-0 z-30 border-t border-gray-200/70 bg-white/90 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl dark:border-gray-800/70 dark:bg-gray-950/90 lg:hidden"
    :aria-label="t('shell.mobileNav')"
    data-testid="mobile-nav"
  >
    <div class="mx-auto flex max-w-lg items-stretch">
      <template v-for="group in [start, null, end]" :key="group ? group[0].name : 'create'">
        <template v-if="group">
          <RouterLink
            v-for="item in group"
            :key="item.name"
            :to="item.route"
            class="relative flex min-w-0 flex-1 flex-col items-center gap-1 py-2.5 text-[11px] font-semibold text-gray-500 transition dark:text-gray-400"
            active-class="!text-brand-600 dark:!text-brand-300"
            :data-testid="`mobile-tab-${item.name}`"
          >
            <component :is="item.icon" class="h-[22px] w-[22px]" aria-hidden="true" />
            <span
              v-if="item.name === 'notifications' && notifications.unread > 0"
              class="absolute end-[26%] top-1.5 h-2.5 w-2.5 rounded-full bg-accent-500 ring-2 ring-white dark:ring-gray-950"
              aria-hidden="true"
            />
            <span class="max-w-full truncate">{{ t(item.label) }}</span>
          </RouterLink>
        </template>
        <div v-else class="flex flex-1 items-center justify-center">
          <button
            type="button"
            class="-mt-5 flex h-12 w-12 items-center justify-center rounded-full bg-tara-gradient text-white shadow-glow ring-4 ring-white transition active:scale-95 dark:ring-gray-950"
            :aria-label="t('nav.createPost')"
            @click="createPost"
          >
            <Plus class="h-6 w-6" aria-hidden="true" />
          </button>
        </div>
      </template>
    </div>
  </nav>
</template>
