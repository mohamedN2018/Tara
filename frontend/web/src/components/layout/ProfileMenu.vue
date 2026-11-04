<script setup lang="ts">
import { ArrowLeft, ChevronDown, ChevronRight, Globe, HelpCircle, KeyRound, ListFilter, Lock, LogOut, Moon, Settings } from "lucide-vue-next";
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { RouteLocationRaw } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { MENU_CATALOG, hasItem } from "@/components/layout/menuCatalog";
import { handleMenuKey, menuItems, setRovingItem } from "@/components/layout/menuKeyboard";
import type { Locale } from "@/i18n";
import { useAuthStore } from "@/stores/auth";
import { usePresenceStore } from "@/stores/presence";
import { type Theme, useUiStore } from "@/stores/ui";

const { t } = useI18n();
const auth = useAuthStore();
const presence = usePresenceStore();
const ui = useUiStore();

const open = ref(false);
// "main" lists the account actions; "display" holds theme and language;
// "settings" is the Settings & privacy panel (the settings centre's sections).
type View = "main" | "display" | "settings";
const view = ref<View>("main");
let openedFrom: Exclude<View, "main"> = "display";

const SETTINGS_LINKS = [
  { to: "/settings", key: "nav.settings", icon: Settings, testid: "profile-menu-settings-all" },
  { to: "/settings/privacy", key: "menu.items.privacyCenter", icon: Lock, testid: "profile-menu-privacy" },
  { to: "/settings/security", key: "menu.items.securityCenter", icon: KeyRound, testid: "profile-menu-security" },
  { to: "/settings/content", key: "settingsCenter.sections.content.title", icon: ListFilter, testid: "profile-menu-content" },
  { to: "/settings/display#language", key: "settings.language", icon: Globe, testid: "profile-menu-language" },
] as const;
const trigger = ref<HTMLButtonElement | null>(null);
const panel = ref<HTMLElement | null>(null);

const displayName = () => auth.profile?.display_name || auth.account?.email?.split("@")[0] || "?";

const profileTo = computed<RouteLocationRaw | null>(() => {
  if (auth.profile?.handle) return `/u/${auth.profile.handle}`;
  if (auth.account?.id) return { name: "profile-by-id", params: { id: auth.account.id } };
  return null;
});

// Help & support: the help centre once it exists (menuCatalog `built`), else the Support inbox.
const help = computed(() => {
  const id = ["helpCenter", "support"].find((key) => hasItem(key, auth.capabilities));
  return id ? MENU_CATALOG.find((i) => i.id === id)?.route ?? null : null;
});

const THEMES: { value: Theme; label: string }[] = [
  { value: "light", label: "settings.light" },
  { value: "dark", label: "settings.dark" },
  { value: "system", label: "settings.system" },
];
const LOCALES: { value: Locale; label: string }[] = [
  { value: "ar", label: "العربية" },
  { value: "en", label: "English" },
];

async function focusFirst() {
  await nextTick();
  if (!panel.value) return;
  const items = menuItems(panel.value);
  setRovingItem(items, items[0] ?? null);
  items[0]?.focus();
}

function show() {
  view.value = "main";
  open.value = true;
  void focusFirst();
}

function close(returnFocus = true) {
  if (!open.value) return;
  open.value = false;
  if (returnFocus) trigger.value?.focus();
}

function toggle() {
  if (open.value) close();
  else show();
}

async function openView(next: View) {
  if (next !== "main") openedFrom = next;
  view.value = next;
  await nextTick();
  if (next === "main") {
    // Back on the main list: focus returns to the entry that opened the sub-view.
    const entry = panel.value?.querySelector<HTMLElement>(`[data-testid="profile-menu-${openedFrom}"]`);
    if (entry && panel.value) {
      setRovingItem(menuItems(panel.value), entry);
      entry.focus();
      return;
    }
  }
  void focusFirst();
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") {
    e.preventDefault();
    e.stopPropagation();
    if (view.value !== "main") void openView("main");
    else close();
    return;
  }
  if (panel.value && handleMenuKey(panel.value, e)) e.preventDefault();
}

function onFocusOut(e: FocusEvent) {
  const next = e.relatedTarget as Node | null;
  if (next && !panel.value?.contains(next) && next !== trigger.value) close(false);
}

function onTriggerKeydown(e: KeyboardEvent) {
  if ((e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") && !open.value) {
    e.preventDefault();
    show();
  }
}

// The bar's backdrop blur makes `fixed` children relative to the bar, so the
// overlay cannot cover the page: close on any press outside instead.
function onPointerDown(e: PointerEvent) {
  const target = e.target as Node | null;
  if (target && !panel.value?.contains(target) && !trigger.value?.contains(target)) close(false);
}
watch(open, (isOpen) => {
  if (isOpen) document.addEventListener("pointerdown", onPointerDown);
  else document.removeEventListener("pointerdown", onPointerDown);
});
onBeforeUnmount(() => document.removeEventListener("pointerdown", onPointerDown));

async function logout() {
  open.value = false;
  await auth.logout();
}

const row =
  "flex w-full items-center gap-3 rounded-lg px-2 py-2 text-start text-sm font-medium transition hover:bg-gray-100 focus:outline-none focus-visible:bg-gray-100 focus-visible:ring-2 focus-visible:ring-brand-400 dark:hover:bg-gray-800 dark:focus-visible:bg-gray-800";
const bubble =
  "flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gray-200/80 text-gray-800 dark:bg-gray-800 dark:text-gray-100";
</script>

<template>
  <div class="relative">
    <button
      ref="trigger"
      class="flex items-center gap-1 rounded-full p-0.5 transition hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:hover:bg-gray-800"
      :aria-label="t('nav.profile')"
      aria-haspopup="menu"
      :aria-expanded="open"
      aria-controls="profile-menu"
      data-testid="profile-menu-button"
      @click="toggle"
      @keydown="onTriggerKeydown"
    >
      <span class="relative">
        <UserAvatar :name="displayName()" :media-id="auth.profile?.avatar_media_id" :size="34" />
        <span
          class="absolute -end-0 -bottom-0 h-2.5 w-2.5 rounded-full border-2 border-white dark:border-gray-900"
          :class="presence.connected ? 'bg-green-500' : 'bg-gray-400'"
          :title="presence.connected ? t('presence.online') : t('presence.offline')"
        />
      </span>
      <ChevronDown class="hidden h-4 w-4 text-gray-500 sm:block dark:text-gray-400" aria-hidden="true" />
    </button>

    <template v-if="open">
      <div class="fixed inset-0 z-40" aria-hidden="true" @click="close(false)" />
      <div
        id="profile-menu"
        ref="panel"
        class="popover absolute end-0 z-50 mt-2 w-80 max-w-[calc(100vw-1.5rem)] overflow-hidden p-2"
        role="menu"
        :aria-label="view === 'main' ? t('nav.profile') : view === 'settings' ? t('profileMenu.settingsPrivacy') : t('profileMenu.display')"
        aria-orientation="vertical"
        data-testid="profile-menu"
        @keydown="onKeydown"
        @focusout="onFocusOut"
      >
        <template v-if="view === 'main'">
          <!-- Profile card -->
          <RouterLink
            v-if="profileTo"
            :to="profileTo"
            role="menuitem"
            tabindex="-1"
            class="mb-1 flex items-center gap-3 rounded-xl p-2 shadow-sm ring-1 ring-gray-200/70 transition hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:ring-gray-800 dark:hover:bg-gray-800"
            data-testid="profile-menu-profile"
            @click="close(false)"
          >
            <UserAvatar :name="displayName()" :media-id="auth.profile?.avatar_media_id" :size="40" />
            <span class="min-w-0">
              <span class="block truncate text-sm font-semibold">{{ displayName() }}</span>
              <span class="block truncate text-xs text-gray-500 dark:text-gray-400">{{ t("profileMenu.seeProfile") }}</span>
            </span>
          </RouterLink>

          <div role="separator" class="my-1 border-t border-gray-100 dark:border-gray-800" />

          <button
            type="button"
            role="menuitem"
            tabindex="-1"
            :class="row"
            aria-haspopup="menu"
            data-testid="profile-menu-settings"
            @click="openView('settings')"
          >
            <span :class="bubble"><Settings class="h-5 w-5" aria-hidden="true" /></span>
            <span class="flex-1">{{ t("profileMenu.settingsPrivacy") }}</span>
            <ChevronRight class="h-5 w-5 text-gray-500 rtl:rotate-180 dark:text-gray-400" aria-hidden="true" />
          </button>

          <RouterLink v-if="help" :to="help" role="menuitem" tabindex="-1" :class="row" data-testid="profile-menu-help" @click="close(false)">
            <span :class="bubble"><HelpCircle class="h-5 w-5" aria-hidden="true" /></span>
            <span class="flex-1">{{ t("profileMenu.help") }}</span>
          </RouterLink>

          <button
            type="button"
            role="menuitem"
            tabindex="-1"
            :class="row"
            aria-haspopup="menu"
            data-testid="profile-menu-display"
            @click="openView('display')"
          >
            <span :class="bubble"><Moon class="h-5 w-5" aria-hidden="true" /></span>
            <span class="flex-1">{{ t("profileMenu.display") }}</span>
            <ChevronRight class="h-5 w-5 text-gray-500 rtl:rotate-180 dark:text-gray-400" aria-hidden="true" />
          </button>

          <button type="button" role="menuitem" tabindex="-1" :class="row" data-testid="profile-menu-logout" @click="logout">
            <span :class="bubble"><LogOut class="h-5 w-5" aria-hidden="true" /></span>
            <span class="flex-1">{{ t("nav.logout") }}</span>
          </button>
        </template>

        <template v-else-if="view === 'settings'">
          <!-- Settings & privacy: the settings centre's main destinations -->
          <div class="mb-1 flex items-center gap-2">
            <button
              type="button"
              role="menuitem"
              tabindex="-1"
              class="icon-btn h-9 w-9 bg-transparent dark:bg-transparent"
              :aria-label="t('profileMenu.back')"
              data-testid="profile-menu-back"
              @click="openView('main')"
            >
              <ArrowLeft class="h-5 w-5 rtl:rotate-180" aria-hidden="true" />
            </button>
            <h3 class="text-lg font-bold" aria-hidden="true">{{ t("profileMenu.settingsPrivacy") }}</h3>
          </div>
          <RouterLink
            v-for="l in SETTINGS_LINKS"
            :key="l.to"
            :to="l.to"
            role="menuitem"
            tabindex="-1"
            :class="row"
            :data-testid="l.testid"
            @click="close(false)"
          >
            <span :class="bubble"><component :is="l.icon" class="h-5 w-5" aria-hidden="true" /></span>
            <span class="flex-1">{{ t(l.key) }}</span>
          </RouterLink>
        </template>

        <template v-else>
          <!-- Display & accessibility: the theme and language the old toggles set -->
          <div class="mb-1 flex items-center gap-2">
            <button
              type="button"
              role="menuitem"
              tabindex="-1"
              class="icon-btn h-9 w-9 bg-transparent dark:bg-transparent"
              :aria-label="t('profileMenu.back')"
              data-testid="profile-menu-back"
              @click="openView('main')"
            >
              <ArrowLeft class="h-5 w-5 rtl:rotate-180" aria-hidden="true" />
            </button>
            <h3 class="text-lg font-bold" aria-hidden="true">{{ t("profileMenu.display") }}</h3>
          </div>

          <div role="group" :aria-label="t('settings.theme')" class="py-1">
            <p class="px-2 pb-1 text-sm font-semibold" aria-hidden="true">{{ t("settings.theme") }}</p>
            <button
              v-for="opt in THEMES"
              :key="opt.value"
              type="button"
              role="menuitemradio"
              tabindex="-1"
              :aria-checked="ui.theme === opt.value"
              :class="row"
              :data-testid="`profile-menu-theme-${opt.value}`"
              @click="ui.setTheme(opt.value)"
            >
              <span class="flex-1">{{ t(opt.label) }}</span>
              <span
                class="h-4 w-4 rounded-full border-2"
                :class="ui.theme === opt.value ? 'border-brand-600 bg-brand-600 ring-2 ring-inset ring-white dark:ring-gray-900' : 'border-gray-400'"
                aria-hidden="true"
              />
            </button>
          </div>

          <div role="separator" class="my-1 border-t border-gray-100 dark:border-gray-800" />

          <div role="group" :aria-label="t('settings.language')" class="py-1">
            <p class="px-2 pb-1 text-sm font-semibold" aria-hidden="true">{{ t("settings.language") }}</p>
            <button
              v-for="opt in LOCALES"
              :key="opt.value"
              type="button"
              role="menuitemradio"
              tabindex="-1"
              :aria-checked="ui.locale === opt.value"
              :lang="opt.value"
              :class="row"
              :data-testid="`profile-menu-locale-${opt.value}`"
              @click="ui.changeLocale(opt.value)"
            >
              <span class="flex-1">{{ opt.label }}</span>
              <span
                class="h-4 w-4 rounded-full border-2"
                :class="ui.locale === opt.value ? 'border-brand-600 bg-brand-600 ring-2 ring-inset ring-white dark:ring-gray-900' : 'border-gray-400'"
                aria-hidden="true"
              />
            </button>
          </div>
        </template>
      </div>
    </template>
  </div>
</template>
