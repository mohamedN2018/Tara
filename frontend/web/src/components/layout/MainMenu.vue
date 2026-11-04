<script setup lang="ts">
import { LayoutGrid, Search } from "lucide-vue-next";
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { RouteLocationRaw } from "vue-router";

import {
  type CreateItem,
  createItems,
  filterCreate,
  filterSections,
  menuSections,
} from "@/components/layout/menuCatalog";
import { handleMenuKey, menuItems, setRovingItem } from "@/components/layout/menuKeyboard";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";

/**
 * The main menu behind the top bar's grid button: every built service in the
 * spec's categories, a search-in-menu field, and a "Create" column. Driven by
 * menuCatalog.ts, so unbuilt modules and items the account may not use never show.
 */
const { t } = useI18n();
const auth = useAuthStore();

const open = ref(false);
const query = ref("");
const trigger = ref<HTMLButtonElement | null>(null);
const panel = ref<HTMLElement | null>(null);
const searchInput = ref<HTMLInputElement | null>(null);

const profileTo = computed<RouteLocationRaw>(() => {
  if (auth.profile?.handle) return `/u/${auth.profile.handle}`;
  if (auth.account?.id) return { name: "profile-by-id", params: { id: auth.account.id } };
  return "/settings";
});

const sections = computed(() =>
  filterSections(menuSections(auth.capabilities, "personal", { profile: profileTo.value }), query.value, t),
);
const creates = computed(() => filterCreate(createItems(auth.capabilities), query.value, t));
const empty = computed(() => sections.value.length === 0 && creates.value.length === 0);

// "Create > Post" opens the composer dialog (ComposerDialog, 2C) on the home feed.
const ui = useUiStore();
function onCreate(item: CreateItem) {
  close(false);
  if (item.id === "post") ui.requestCompose();
}

async function show() {
  open.value = true;
  query.value = "";
  await nextTick();
  if (panel.value) setRovingItem(menuItems(panel.value), null);
  searchInput.value?.focus();
}

function close(returnFocus = true) {
  if (!open.value) return;
  open.value = false;
  if (returnFocus) trigger.value?.focus();
}

function toggle() {
  if (open.value) close();
  else void show();
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") {
    e.preventDefault();
    e.stopPropagation();
    close();
    return;
  }
  if (panel.value && handleMenuKey(panel.value, e)) e.preventDefault();
}

/** Tab out of the panel closes it, as a menu does; focus stays where it went. */
function onFocusOut(e: FocusEvent) {
  const next = e.relatedTarget as Node | null;
  if (next && !panel.value?.contains(next) && next !== trigger.value) close(false);
}

function onTriggerKeydown(e: KeyboardEvent) {
  if (e.key === "ArrowDown" && !open.value) {
    e.preventDefault();
    void show();
  }
}

// The bar's backdrop blur makes `fixed` children relative to the bar, so the
// overlay above cannot cover the page: close on any press outside instead.
function onPointerDown(e: PointerEvent) {
  const target = e.target as Node | null;
  if (target && !panel.value?.contains(target) && !trigger.value?.contains(target)) close(false);
}
watch(open, (isOpen) => {
  if (isOpen) document.addEventListener("pointerdown", onPointerDown);
  else document.removeEventListener("pointerdown", onPointerDown);
});
onBeforeUnmount(() => document.removeEventListener("pointerdown", onPointerDown));

// After a search narrows the list, the first match is the one Tab reaches.
async function onSearch() {
  await nextTick();
  if (panel.value) setRovingItem(menuItems(panel.value), null);
}
</script>

<template>
  <div class="relative">
    <button
      ref="trigger"
      class="icon-btn"
      :class="open ? '!bg-brand-50 !text-brand-700 dark:!bg-brand-950/70 dark:!text-brand-300' : ''"
      :aria-label="t('nav.menu')"
      :title="t('nav.menu')"
      aria-haspopup="dialog"
      :aria-expanded="open"
      aria-controls="main-menu"
      data-testid="main-menu-button"
      @click="toggle"
      @keydown="onTriggerKeydown"
    >
      <LayoutGrid class="h-5 w-5" />
    </button>

    <template v-if="open">
      <div class="fixed inset-0 z-40" aria-hidden="true" @click="close(false)" />
      <div
        id="main-menu"
        ref="panel"
        class="popover fixed end-3 top-[4.25rem] z-50 flex max-h-[calc(100dvh-5rem)] w-[min(42rem,calc(100vw-1.5rem))] flex-col overflow-hidden p-0"
        role="dialog"
        aria-labelledby="main-menu-title"
        data-testid="main-menu"
        @keydown="onKeydown"
        @focusout="onFocusOut"
      >
        <h2 id="main-menu-title" class="px-4 pb-2 pt-3 text-xl font-bold">{{ t("menu.title") }}</h2>

        <div class="grid min-h-0 flex-1 gap-3 overflow-y-auto px-3 pb-3 sm:grid-cols-[minmax(0,1fr)_13rem]">
          <!-- Services by category, with search-in-menu -->
          <div class="min-w-0 rounded-2xl bg-gray-50 p-2 dark:bg-gray-900/60">
            <div class="relative mb-1">
              <Search class="pointer-events-none absolute inset-y-0 start-3 my-auto h-4 w-4 text-gray-500 dark:text-gray-400" aria-hidden="true" />
              <input
                ref="searchInput"
                v-model="query"
                type="search"
                class="input h-10 rounded-full border-transparent bg-white ps-9 dark:border-transparent dark:bg-gray-800"
                dir="auto"
                :placeholder="t('menu.search')"
                :aria-label="t('menu.search')"
                aria-controls="main-menu-items"
                autocomplete="off"
                data-testid="main-menu-search"
                @input="onSearch"
              />
            </div>

            <div id="main-menu-items" role="menu" :aria-label="t('menu.title')" aria-orientation="vertical">
              <div
                v-for="section in sections"
                :key="section.category"
                role="group"
                :aria-label="t(section.labelKey)"
                class="border-b border-gray-200/70 py-1.5 last:border-0 dark:border-gray-800/70"
                :data-testid="`menu-section-${section.category}`"
              >
                <p class="px-2 pb-1 pt-1.5 text-sm font-bold text-gray-900 dark:text-white" aria-hidden="true">
                  {{ t(section.labelKey) }}
                </p>
                <RouterLink
                  v-for="item in section.items"
                  :key="item.id"
                  :to="item.to"
                  role="menuitem"
                  tabindex="-1"
                  class="flex items-center gap-3 rounded-xl p-2 transition hover:bg-gray-100 focus:outline-none focus-visible:bg-gray-100 focus-visible:ring-2 focus-visible:ring-brand-400 dark:hover:bg-gray-800 dark:focus-visible:bg-gray-800"
                  exact-active-class="bg-brand-50 dark:bg-brand-950/50"
                  :aria-describedby="item.descKey ? `menu-desc-${item.id}` : undefined"
                  :data-testid="`menu-item-${item.id}`"
                  @click="close(false)"
                >
                  <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-600 dark:bg-brand-950/60 dark:text-brand-300">
                    <component :is="item.icon" class="h-5 w-5" aria-hidden="true" />
                  </span>
                  <span class="min-w-0">
                    <span class="block truncate text-sm font-semibold text-gray-900 dark:text-gray-100">{{ t(item.labelKey) }}</span>
                    <span
                      v-if="item.descKey"
                      :id="`menu-desc-${item.id}`"
                      class="block truncate text-xs text-gray-500 dark:text-gray-400"
                    >{{ t(item.descKey) }}</span>
                  </span>
                </RouterLink>
              </div>
            </div>

            <p v-if="empty" class="px-3 py-6 text-center text-sm text-gray-500 dark:text-gray-400" role="status">
              {{ t("menu.noResults") }}
            </p>
          </div>

          <!-- Create: only the creation flows that exist -->
          <div v-if="creates.length" class="h-fit rounded-2xl bg-gray-50 p-2 dark:bg-gray-900/60">
            <p class="px-2 pb-1 pt-1.5 text-base font-bold" aria-hidden="true">{{ t("menu.create") }}</p>
            <div role="menu" :aria-label="t('menu.create')" aria-orientation="vertical">
              <RouterLink
                v-for="item in creates"
                :key="item.id"
                :to="item.route"
                role="menuitem"
                tabindex="-1"
                class="flex items-center gap-3 rounded-xl p-2 text-sm font-medium transition hover:bg-gray-100 focus:outline-none focus-visible:bg-gray-100 focus-visible:ring-2 focus-visible:ring-brand-400 dark:hover:bg-gray-800 dark:focus-visible:bg-gray-800"
                :data-testid="`menu-create-${item.id}`"
                @click="onCreate(item)"
              >
                <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gray-200/80 text-gray-800 dark:bg-gray-800 dark:text-gray-100">
                  <component :is="item.icon" class="h-5 w-5" aria-hidden="true" />
                </span>
                <span class="min-w-0 truncate">{{ t(item.labelKey) }}</span>
              </RouterLink>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
