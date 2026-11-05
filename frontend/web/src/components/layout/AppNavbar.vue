<script setup lang="ts">
import { Bell, CalendarDays, Home, Menu, MonitorPlay, Search, Store, Users, UsersRound } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import MessengerDropdown from "@/components/chat/MessengerDropdown.vue";
import MainMenu from "@/components/layout/MainMenu.vue";
import ProfileMenu from "@/components/layout/ProfileMenu.vue";
import TaraLogo from "@/components/brand/TaraLogo.vue";
import NotificationPanel from "@/components/notifications/NotificationPanel.vue";
import GlobalSearch from "@/components/search/GlobalSearch.vue";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useNotificationStore } from "@/stores/notifications";
import { useUiStore } from "@/stores/ui";

const { t } = useI18n();
const ui = useUiStore();
const notifications = useNotificationStore();

const showNotifs = ref(false);
useEscapeKey(showNotifs, () => (showNotifs.value = false));

// Centre tabs. Video opens the videos module (reels are reached from there and
// from the menu); there is no gaming tab because that module does not exist.
const navIcons = [
  { name: "home", to: "/home", icon: Home, label: "nav.home" },
  { name: "friends", to: "/friends", icon: Users, label: "nav.friends" },
  { name: "videos", to: "/videos", icon: MonitorPlay, label: "menu.items.videos" },
  { name: "marketplace", to: "/marketplace", icon: Store, label: "nav.marketplace" },
  { name: "groups", to: "/groups", icon: UsersRound, label: "nav.groups" },
  { name: "events", to: "/events", icon: CalendarDays, label: "nav.events" },
];
</script>

<template>
  <!-- Three columns keep the tabs centred whatever the two sides hold -->
  <header
    class="fixed inset-x-0 top-0 z-40 grid h-16 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2 border-b border-gray-200/70 bg-white/80 px-3 backdrop-blur-xl dark:border-gray-800/70 dark:bg-gray-950/80 sm:px-4"
    data-testid="top-bar"
  >
    <!-- Start: mobile menu, logo and search -->
    <div class="col-start-1 flex min-w-0 items-center gap-1.5">
      <button class="icon-btn h-9 w-9 shrink-0 bg-transparent dark:bg-transparent lg:hidden" :aria-label="t('menu.sidebar')" :aria-expanded="ui.sidebarOpen" @click="ui.sidebarOpen = !ui.sidebarOpen">
        <Menu class="h-5 w-5" />
      </button>
      <RouterLink to="/home" class="shrink-0 rounded-xl px-1 py-1">
        <TaraLogo :size="30" :label="t('app.name')" />
      </RouterLink>
      <!-- Search: recent, trending and live suggestions (components/search/GlobalSearch.vue) -->
      <GlobalSearch class="hidden min-w-0 flex-1 sm:block lg:max-w-xs xl:max-w-sm" />
    </div>

    <!-- Centre: icon tabs from md up, each with a tooltip and an underline when active -->
    <nav class="col-start-2 hidden h-full items-stretch md:flex" :aria-label="t('menu.primaryNav')" data-testid="top-tabs">
      <RouterLink
        v-for="n in navIcons"
        :key="n.name"
        v-slot="{ isActive }"
        :to="n.to"
        class="group relative flex h-full w-12 items-center justify-center text-gray-500 hover:text-gray-900 focus:outline-none dark:text-gray-400 dark:hover:text-white lg:w-[4.5rem] xl:w-24 2xl:w-28"
        active-class="!text-brand-600 dark:!text-brand-300"
        :aria-label="t(n.label)"
        :data-testid="`top-tab-${n.name}`"
      >
        <span
          class="flex h-12 w-full items-center justify-center rounded-xl transition group-focus-visible:ring-2 group-focus-visible:ring-brand-400"
          :class="isActive ? '' : 'group-hover:bg-gray-100 dark:group-hover:bg-gray-900'"
        >
          <component :is="n.icon" class="h-6 w-6" :stroke-width="isActive ? 2.4 : 2" aria-hidden="true" />
        </span>
        <span
          v-if="isActive"
          class="absolute inset-x-1 bottom-0 h-[3px] rounded-t-full bg-brand-600 dark:bg-brand-400"
          aria-hidden="true"
          data-testid="top-tab-underline"
        />
        <!-- Tooltip: the link is named by aria-label, so this stays out of the a11y tree -->
        <span
          class="pointer-events-none absolute top-full z-50 mt-1 whitespace-nowrap rounded-lg bg-gray-900/90 px-2.5 py-1 text-xs font-medium text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-hover:delay-300 group-focus-visible:opacity-100 dark:bg-gray-700"
          aria-hidden="true"
          data-testid="top-tab-tooltip"
        >{{ t(n.label) }}</span>
      </RouterLink>
    </nav>

    <!-- End: main menu, messages, notifications, profile -->
    <div class="col-start-3 flex items-center justify-end gap-1.5">
      <!-- Phones: the field does not fit the bar, so search opens its own page -->
      <RouterLink to="/search" class="icon-btn sm:hidden" :aria-label="t('search.openSearch')" :title="t('search.openSearch')">
        <Search class="h-5 w-5" />
      </RouterLink>

      <!-- Main menu: every service by category, plus the Create column -->
      <MainMenu />

      <!-- Messenger: dropdown from sm up, a link to the inbox on phones (components/chat/MessengerDropdown.vue) -->
      <MessengerDropdown />

      <!-- Notifications dropdown -->
      <div class="relative">
        <button
          class="icon-btn relative"
          :class="showNotifs ? '!bg-brand-50 !text-brand-700 dark:!bg-brand-950/70 dark:!text-brand-300' : ''"
          :aria-label="notifications.unread > 0 ? t('nav.notificationsUnread', notifications.unread) : t('nav.notifications')"
          :title="t('nav.notifications')"
          :aria-expanded="showNotifs"
          @click="showNotifs = !showNotifs"
        >
          <Bell class="h-5 w-5" />
          <span v-if="notifications.unread > 0" class="badge absolute -end-1 -top-1 !bg-accent-700 ring-2 ring-white dark:ring-gray-950">
            {{ notifications.unread > 99 ? "99+" : notifications.unread }}
          </span>
        </button>

        <template v-if="showNotifs">
          <div class="fixed inset-0 z-40" @click="showNotifs = false" />
          <div class="popover absolute end-0 z-50 mt-2 max-h-[calc(100vh-5rem)] w-[22rem] max-w-[92vw] overflow-y-auto overscroll-contain p-2" data-testid="notif-dropdown">
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

      <ProfileMenu />
    </div>
  </header>
</template>
