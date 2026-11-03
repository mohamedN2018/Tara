<script setup lang="ts">
import {
  Bell,
  Clock,
  FileText,
  Home,
  Menu,
  MessageCircle,
  Search,
  Store,
  User,
  Users,
} from "lucide-vue-next";
import { onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import MessagesPanel from "@/components/chat/MessagesPanel.vue";
import AppsMenu from "@/components/layout/AppsMenu.vue";
import CreateMenu from "@/components/layout/CreateMenu.vue";
import ProfileMenu from "@/components/layout/ProfileMenu.vue";
import NotificationPanel from "@/components/notifications/NotificationPanel.vue";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { type Suggestion, searchService } from "@/services/search";
import { useNotificationStore } from "@/stores/notifications";
import { useUiStore } from "@/stores/ui";

const { t } = useI18n();
const router = useRouter();
const ui = useUiStore();
const notifications = useNotificationStore();

const showNotifs = ref(false);
const showMessages = ref(false);
useEscapeKey(showNotifs, () => (showNotifs.value = false));
useEscapeKey(showMessages, () => (showMessages.value = false));

// --- Search: live autocomplete (real /search/autocomplete/) + recent history.
const RECENT_KEY = "tara.recentSearches";
const q = ref("");
const suggestions = ref<Suggestion[]>([]);
const showSearch = ref(false);
useEscapeKey(showSearch, () => (showSearch.value = false));

function loadRecent(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    return Array.isArray(raw) ? raw.filter((x) => typeof x === "string").slice(0, 6) : [];
  } catch {
    return [];
  }
}
const recent = ref<string[]>(loadRecent());

function rememberTerm(term: string) {
  recent.value = [term, ...recent.value.filter((r) => r !== term)].slice(0, 6);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(recent.value));
  } catch {
    // Storage may be unavailable (private mode) — recents are best-effort.
  }
}
function clearRecent() {
  recent.value = [];
  try {
    localStorage.removeItem(RECENT_KEY);
  } catch {
    // ignore
  }
}

let suggestTimer: number | null = null;
watch(q, (val) => {
  if (suggestTimer) window.clearTimeout(suggestTimer);
  const term = val.trim();
  if (term.length < 2) {
    suggestions.value = [];
    return;
  }
  // Debounce autocomplete so we don't fire a request per keystroke.
  suggestTimer = window.setTimeout(async () => {
    try {
      suggestions.value = await searchService.suggest(term);
    } catch {
      suggestions.value = []; // Endpoint optional; fall back to free-text search.
    }
  }, 250);
});
onBeforeUnmount(() => {
  if (suggestTimer) window.clearTimeout(suggestTimer);
});

function go(term: string) {
  const value = term.trim();
  if (!value) return;
  q.value = value;
  rememberTerm(value);
  showSearch.value = false;
  router.push({ name: "search", query: { q: value } });
}
function submitSearch() {
  go(q.value);
}

// Person suggestions jump straight to that profile; everything else runs a
// full-text search.
function pickSuggestion(s: Suggestion) {
  rememberTerm(s.title);
  showSearch.value = false;
  q.value = s.title;
  if (s.type === "user" && s.id) {
    router.push({ name: "profile-by-id", params: { id: s.id } });
  } else {
    router.push({ name: "search", query: { q: s.title } });
  }
}

function iconFor(type: string) {
  if (type === "user") return User;
  if (type === "listing") return Store;
  return FileText;
}

const navIcons = [
  { name: "home", to: "/home", icon: Home, label: "nav.home" },
  { name: "friends", to: "/friends", icon: Users, label: "nav.friends" },
  { name: "marketplace", to: "/marketplace", icon: Store, label: "nav.marketplace" },
];
</script>

<template>
  <header
    class="fixed inset-x-0 top-0 z-40 flex h-14 items-center gap-2 border-b border-gray-200 bg-white/90 px-3 backdrop-blur dark:border-gray-800 dark:bg-gray-900/90"
  >
    <!-- Left: mobile menu + logo + search -->
    <div class="flex items-center gap-2">
      <button
        class="rounded-full p-2 text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800 lg:hidden"
        :aria-label="t('nav.menu')"
        @click="ui.sidebarOpen = !ui.sidebarOpen"
      >
        <Menu class="h-5 w-5" />
      </button>
      <RouterLink to="/home" class="text-xl font-extrabold text-brand-600">{{ t("app.name") }}</RouterLink>

      <!-- Search with live suggestions + recent history -->
      <div class="relative hidden w-48 sm:block md:w-72">
        <form role="search" @submit.prevent="submitSearch">
          <Search class="pointer-events-none absolute inset-y-0 start-3 my-auto h-4 w-4 text-gray-400" />
          <input
            v-model="q"
            type="search"
            class="input rounded-full bg-gray-100 ps-9 dark:bg-gray-800"
            :placeholder="t('search.placeholder')"
            :aria-label="t('nav.search')"
            autocomplete="off"
            @focus="showSearch = true"
          />
        </form>

        <template v-if="showSearch">
          <div class="fixed inset-0 z-30" @click="showSearch = false" />
          <div class="card absolute inset-x-0 z-40 mt-2 max-h-[70vh] overflow-y-auto p-1.5">
            <!-- Typing → live suggestions -->
            <template v-if="q.trim().length >= 2">
              <button
                v-for="s in suggestions"
                :key="s.id"
                type="button"
                class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-start text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800"
                @mousedown.prevent="pickSuggestion(s)"
              >
                <span
                  class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-100 text-gray-500 dark:bg-gray-800"
                >
                  <component :is="iconFor(s.type)" class="h-4 w-4" />
                </span>
                <span class="min-w-0 flex-1">
                  <span class="block truncate font-medium" dir="auto">{{ s.title }}</span>
                  <span v-if="s.snippet" class="block truncate text-xs text-gray-400" dir="auto">{{ s.snippet }}</span>
                </span>
              </button>
              <p class="px-3 py-2 text-xs text-gray-400">{{ t("search.hint") }}</p>
            </template>

            <!-- Empty input → recent searches -->
            <template v-else-if="recent.length">
              <div class="flex items-center justify-between px-3 py-1">
                <span class="text-xs font-semibold text-gray-400">{{ t("search.recent") }}</span>
                <button
                  type="button"
                  class="text-xs font-medium text-brand-600"
                  @mousedown.prevent="clearRecent"
                >
                  {{ t("search.clear") }}
                </button>
              </div>
              <button
                v-for="r in recent"
                :key="r"
                type="button"
                class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-start text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800"
                @mousedown.prevent="go(r)"
              >
                <Clock class="h-4 w-4 text-gray-400" />
                <span class="truncate">{{ r }}</span>
              </button>
            </template>

            <p v-else class="px-3 py-2 text-xs text-gray-400">{{ t("search.hint") }}</p>
          </div>
        </template>
      </div>
    </div>

    <!-- Center: primary nav (desktop) with active underline -->
    <nav class="hidden h-full flex-1 items-center justify-center md:flex" :aria-label="t('nav.home')">
      <RouterLink
        v-for="n in navIcons"
        :key="n.name"
        :to="n.to"
        class="relative flex h-14 items-center px-8 text-gray-500 transition hover:bg-gray-100 dark:hover:bg-gray-800"
        active-class="text-brand-600 after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:rounded-full after:bg-brand-600"
        :aria-label="t(n.label)"
        :title="t(n.label)"
      >
        <component :is="n.icon" class="h-6 w-6" />
      </RouterLink>
    </nav>

    <!-- Right: create, messages, notifications, apps, profile -->
    <div class="ms-auto flex items-center gap-1">
      <!-- Create menu (post / listing); the bottom bar keeps mobile lean -->
      <div class="hidden sm:block">
        <CreateMenu />
      </div>

      <!-- Messages dropdown (mobile uses the bottom bar instead) -->
      <div class="relative hidden sm:block">
        <button
          class="rounded-full bg-gray-100 p-2 text-gray-700 transition hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
          :aria-label="t('nav.messages')"
          aria-haspopup="menu"
          :aria-expanded="showMessages"
          @click="showMessages = !showMessages"
        >
          <MessageCircle class="h-5 w-5" />
        </button>
        <template v-if="showMessages">
          <div class="fixed inset-0 z-40" @click="showMessages = false" />
          <div class="card absolute end-0 z-50 mt-2 w-80 max-w-[92vw] p-2">
            <div class="flex items-center justify-between px-2 pb-1">
              <h3 class="text-sm font-bold">{{ t("nav.messages") }}</h3>
              <RouterLink
                to="/messages"
                class="text-xs font-medium text-brand-600"
                @click="showMessages = false"
              >
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
          class="relative rounded-full bg-gray-100 p-2 text-gray-700 transition hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
          :aria-label="t('nav.notifications')"
          aria-haspopup="menu"
          :aria-expanded="showNotifs"
          @click="showNotifs = !showNotifs"
        >
          <Bell class="h-5 w-5" />
          <span
            v-if="notifications.unread > 0"
            class="absolute -end-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white"
          >
            {{ notifications.unread > 99 ? "99+" : notifications.unread }}
          </span>
        </button>

        <template v-if="showNotifs">
          <div class="fixed inset-0 z-40" @click="showNotifs = false" />
          <div class="card absolute end-0 z-50 mt-2 w-80 max-w-[92vw] p-2">
            <div class="flex items-center justify-between px-2 pb-1">
              <h3 class="text-sm font-bold">{{ t("notifications.title") }}</h3>
              <RouterLink
                to="/notifications"
                class="text-xs font-medium text-brand-600"
                @click="showNotifs = false"
              >
                {{ t("notifications.viewAll") }}
              </RouterLink>
            </div>
            <NotificationPanel :limit="6" />
          </div>
        </template>
      </div>

      <!-- Apps grid: shortcuts to every section (available at all sizes) -->
      <AppsMenu />

      <ProfileMenu />
    </div>
  </header>
</template>
