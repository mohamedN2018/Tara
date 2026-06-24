<script setup lang="ts">
import {
  Bell,
  Bookmark,
  Home,
  LayoutGrid,
  MessageCircle,
  Search,
  Settings,
  Shield,
  Store,
  User,
  UserCheck,
  Users,
} from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { RouteLocationRaw } from "vue-router";

import { useEscapeKey } from "@/lib/useEscapeKey";
import { useAuthStore } from "@/stores/auth";

const { t } = useI18n();
const auth = useAuthStore();

const open = ref(false);
useEscapeKey(open, () => (open.value = false));

interface AppLink {
  to: RouteLocationRaw;
  icon: typeof Home;
  label: string;
}

const profileTo = computed<RouteLocationRaw>(() => {
  if (auth.profile?.handle) return `/u/${auth.profile.handle}`;
  if (auth.account?.id) return { name: "profile-by-id", params: { id: auth.account.id } };
  return "/settings";
});

const links = computed<AppLink[]>(() => {
  const base: AppLink[] = [
    { to: "/home", icon: Home, label: "nav.home" },
    { to: "/friends", icon: Users, label: "nav.friends" },
    { to: "/connections", icon: UserCheck, label: "nav.connections" },
    { to: "/messages", icon: MessageCircle, label: "nav.messages" },
    { to: "/marketplace", icon: Store, label: "nav.marketplace" },
    { to: "/saved", icon: Bookmark, label: "nav.saved" },
    { to: "/notifications", icon: Bell, label: "nav.notifications" },
    { to: "/search", icon: Search, label: "nav.search" },
    { to: profileTo.value, icon: User, label: "nav.profile" },
    { to: "/settings", icon: Settings, label: "nav.settings" },
  ];
  if (auth.isStaff) base.push({ to: "/admin", icon: Shield, label: "nav.admin" });
  return base;
});
</script>

<template>
  <div class="relative">
    <button
      class="rounded-full bg-gray-100 p-2 text-gray-700 transition hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
      :class="open ? 'bg-brand-50 text-brand-600 dark:bg-brand-950/40' : ''"
      :aria-label="t('nav.menu')"
      aria-haspopup="menu"
      :aria-expanded="open"
      @click="open = !open"
    >
      <LayoutGrid class="h-5 w-5" />
    </button>

    <template v-if="open">
      <div class="fixed inset-0 z-40" @click="open = false" />
      <div class="card absolute end-0 z-50 mt-2 w-80 max-w-[92vw] p-2" role="menu">
        <h3 class="px-2 pb-2 text-sm font-bold">{{ t("nav.menu") }}</h3>
        <div class="grid grid-cols-3 gap-1">
          <RouterLink
            v-for="link in links"
            :key="link.label"
            :to="link.to"
            class="flex flex-col items-center gap-1.5 rounded-xl p-3 text-center transition hover:bg-gray-100 dark:hover:bg-gray-800"
            active-class="bg-brand-50 font-semibold dark:bg-brand-950/40"
            role="menuitem"
            @click="open = false"
          >
            <span
              class="flex h-11 w-11 items-center justify-center rounded-full bg-brand-50 text-brand-600 dark:bg-brand-950/40"
            >
              <component :is="link.icon" class="h-5 w-5" />
            </span>
            <span class="text-xs text-gray-700 dark:text-gray-200">{{ t(link.label) }}</span>
          </RouterLink>
        </div>
      </div>
    </template>
  </div>
</template>
