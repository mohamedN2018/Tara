<script setup lang="ts">
import { Bell, Home, Menu, MessageCircle, Search, Store, Users, UsersRound } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import MessagesPanel from "@/components/chat/MessagesPanel.vue";
import AppsMenu from "@/components/layout/AppsMenu.vue";
import CreateMenu from "@/components/layout/CreateMenu.vue";
import ProfileMenu from "@/components/layout/ProfileMenu.vue";
import TaraLogo from "@/components/brand/TaraLogo.vue";
import NotificationPanel from "@/components/notifications/NotificationPanel.vue";
import GlobalSearch from "@/components/search/GlobalSearch.vue";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { badgeText } from "@/lib/chat";
import { useChatUnreadStore } from "@/stores/chatUnread";
import { useNotificationStore } from "@/stores/notifications";
import { useUiStore } from "@/stores/ui";

const { t } = useI18n();
const ui = useUiStore();
const notifications = useNotificationStore();
const chatUnread = useChatUnreadStore();

const showNotifs = ref(false);
const showMessages = ref(false);
useEscapeKey(showNotifs, () => (showNotifs.value = false));
useEscapeKey(showMessages, () => (showMessages.value = false));

const navIcons = [
  { name: "home", to: "/home", icon: Home, label: "nav.home" },
  { name: "friends", to: "/friends", icon: Users, label: "nav.friends" },
  { name: "marketplace", to: "/marketplace", icon: Store, label: "nav.marketplace" },
  { name: "groups", to: "/groups", icon: UsersRound, label: "nav.groups" },
];
</script>

<template>
  <header
    class="fixed inset-x-0 top-0 z-40 flex h-16 items-center gap-3 border-b border-gray-200/70 bg-white/80 px-3 backdrop-blur-xl dark:border-gray-800/70 dark:bg-gray-950/80 sm:px-4"
  >
    <!-- Start: mobile menu + logo -->
    <div class="flex min-w-0 items-center gap-1.5 lg:w-60 xl:w-64">
      <button class="icon-btn h-9 w-9 bg-transparent dark:bg-transparent lg:hidden" :aria-label="t('nav.menu')" @click="ui.sidebarOpen = !ui.sidebarOpen">
        <Menu class="h-5 w-5" />
      </button>
      <RouterLink to="/home" class="rounded-xl px-1 py-1">
        <TaraLogo :size="30" :label="t('app.name')" />
      </RouterLink>
    </div>

    <!-- Search: recent, trending and live suggestions (components/search/GlobalSearch.vue) -->
    <GlobalSearch class="hidden min-w-0 flex-1 sm:block md:max-w-md lg:max-w-xl" />

    <!-- Primary nav on tablets; from lg the sidebar takes over -->
    <nav class="hidden h-full items-center gap-1 md:flex lg:hidden" :aria-label="t('nav.home')">
      <RouterLink
        v-for="n in navIcons"
        :key="n.name"
        :to="n.to"
        class="relative flex h-11 w-14 items-center justify-center rounded-xl text-gray-500 transition hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-900 dark:hover:text-white"
        active-class="!text-brand-600 dark:!text-brand-300 after:absolute after:inset-x-3 after:-bottom-[10px] after:h-[3px] after:rounded-full after:bg-tara-gradient"
        :aria-label="t(n.label)"
        :title="t(n.label)"
      >
        <component :is="n.icon" class="h-6 w-6" />
      </RouterLink>
    </nav>

    <!-- End: create, messages, notifications, apps, profile -->
    <div class="ms-auto flex items-center gap-1.5">
      <!-- Phones: the field does not fit the bar, so search opens its own page -->
      <RouterLink to="/search" class="icon-btn sm:hidden" :aria-label="t('search.openSearch')" :title="t('search.openSearch')">
        <Search class="h-5 w-5" />
      </RouterLink>
      <div class="hidden sm:block">
        <CreateMenu />
      </div>

      <!-- Messages dropdown (mobile uses the bottom bar instead) -->
      <div class="relative hidden sm:block">
        <button
          class="icon-btn relative"
          :class="showMessages ? '!bg-brand-50 !text-brand-700 dark:!bg-brand-950/70 dark:!text-brand-300' : ''"
          :aria-label="chatUnread.conversations > 0 ? t('messages.unreadBadge', chatUnread.conversations) : t('nav.messages')"
          aria-haspopup="menu"
          :aria-expanded="showMessages"
          @click="showMessages = !showMessages"
        >
          <MessageCircle class="h-5 w-5" />
          <span v-if="chatUnread.conversations > 0" class="badge absolute -end-1 -top-1 ring-2 ring-white dark:ring-gray-950" data-testid="messages-badge">
            {{ badgeText(chatUnread.conversations) }}
          </span>
        </button>
        <template v-if="showMessages">
          <div class="fixed inset-0 z-40" @click="showMessages = false" />
          <div class="popover absolute end-0 z-50 mt-2 w-[22rem] max-w-[92vw] p-2">
            <div class="flex items-center justify-between px-2 pb-2 pt-1">
              <h3 class="section-title">{{ t("nav.messages") }}</h3>
              <RouterLink to="/messages" class="text-xs font-semibold text-brand-600 dark:text-brand-300" @click="showMessages = false">
                {{ t("notifications.viewAll") }}
              </RouterLink>
            </div>
            <MessagesPanel :limit="6" @navigate="showMessages = false" />
          </div>
        </template>
      </div>

      <!-- Notifications dropdown -->
      <div class="relative">
        <button
          class="icon-btn relative"
          :class="showNotifs ? '!bg-brand-50 !text-brand-700 dark:!bg-brand-950/70 dark:!text-brand-300' : ''"
          :aria-label="notifications.unread > 0 ? t('nav.notificationsUnread', notifications.unread) : t('nav.notifications')"
          :aria-expanded="showNotifs"
          @click="showNotifs = !showNotifs"
        >
          <Bell class="h-5 w-5" />
          <span v-if="notifications.unread > 0" class="badge absolute -end-1 -top-1 ring-2 ring-white dark:ring-gray-950">
            {{ notifications.unread > 99 ? "99+" : notifications.unread }}
          </span>
        </button>

        <template v-if="showNotifs">
          <div class="fixed inset-0 z-40" @click="showNotifs = false" />
          <div class="popover absolute end-0 z-50 mt-2 w-[22rem] max-w-[92vw] p-2">
            <div class="flex items-center justify-between px-2 pb-2 pt-1">
              <h3 class="section-title">{{ t("notifications.title") }}</h3>
              <RouterLink to="/notifications" class="text-xs font-semibold text-brand-600 dark:text-brand-300" @click="showNotifs = false">
                {{ t("notifications.viewAll") }}
              </RouterLink>
            </div>
            <NotificationPanel :limit="6" @navigate="showNotifs = false" />
          </div>
        </template>
      </div>

      <!-- Apps grid: shortcuts to every section (available at all sizes) -->
      <AppsMenu />

      <ProfileMenu />
    </div>
  </header>
</template>
