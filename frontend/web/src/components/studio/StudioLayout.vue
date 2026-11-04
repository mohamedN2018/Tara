<script setup lang="ts">
import {
  BarChart3,
  CalendarDays,
  ChevronDown,
  Home,
  Library,
  MessageCircle,
  MessagesSquare,
  Newspaper,
  TrendingUp,
} from "lucide-vue-next";
import { onMounted, provide, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import AppNavbar from "@/components/layout/AppNavbar.vue";
import MobileBottomNavigation from "@/components/layout/MobileBottomNavigation.vue";
import ComposerDialog from "@/components/post/ComposerDialog.vue";
import StudioCreateMenu from "@/components/studio/StudioCreateMenu.vue";
import { type ComposeOptions, STUDIO_COMPOSER } from "@/components/studio/studioComposer";
import type { ComposerPost } from "@/services/composer";
import { useNotificationStore } from "@/stores/notifications";

/**
 * Tara Studio's own layout (reference 6): the top bar, a start-side studio
 * navigation (Home; Insights → Content performance; Content → Content
 * library, Planner; Engagement → Comments) with "Create post ▾"
 * pinned at its foot, and the child route on the rest of the width (the
 * studio pages are nested routes, so they inject the composer directly). On phones the
 * navigation becomes a row of tabs under the top bar. Only destinations that
 * exist are listed, and each shows only counters the post service keeps.
 */
const { t } = useI18n();
const route = useRoute();
const notifications = useNotificationStore();

const home = { name: "studio", to: "/studio", label: "studio.nav.home", icon: Home };
// The reference's collapsible sections, each with its real pages.
const sections = [
  {
    key: "insights",
    label: "studio.nav.insights",
    icon: BarChart3,
    items: [{ name: "studio-insights", to: "/studio/insights", label: "studio.nav.performance", icon: TrendingUp }],
  },
  {
    key: "content",
    label: "studio.nav.content",
    icon: Newspaper,
    items: [
      { name: "studio-library", to: "/studio/library", label: "studio.nav.library", icon: Library },
      { name: "studio-planner", to: "/studio/planner", label: "studio.nav.planner", icon: CalendarDays },
    ],
  },
  {
    key: "engagement",
    label: "studio.nav.engagement",
    icon: MessageCircle,
    items: [{ name: "studio-engagement", to: "/studio/engagement", label: "studio.nav.comments", icon: MessagesSquare }],
  },
];
// Phones and tablets: every page as one tab.
const items = [home, ...sections.flatMap((s) => s.items)];
const isActive = (name: string) => route.name === name;
const sectionActive = (key: string) => !!sections.find((s) => s.key === key)?.items.some((i) => isActive(i.name));
// Content starts open (as in the reference); a section holding the current page too.
const expanded = reactive<Record<string, boolean>>(
  Object.fromEntries(sections.map((s) => [s.key, s.key === "content" || sectionActive(s.key)])),
);

// ---- one composer for every studio page --------------------------------------------
const composing = ref(false);
const composeDraft = ref<ComposerPost | null>(null);
const composeAt = ref<string | null>(null);
const version = ref(0);
function open(options: ComposeOptions = {}) {
  composeDraft.value = options.draft ?? null;
  composeAt.value = options.scheduleAt ?? null;
  composing.value = true;
}
function touch() {
  version.value += 1;
}
provide(STUDIO_COMPOSER, { open, version, touch });

onMounted(() => {
  notifications.bind();
  notifications.refresh();
});

const row =
  "flex items-center gap-3 rounded-xl px-2 py-2 text-[15px] font-semibold text-gray-800 transition hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:text-gray-100 dark:hover:bg-gray-800/70";
const activeRow = "bg-brand-50 text-brand-700 dark:bg-gray-800 dark:text-white";
const tile = "flex h-10 w-10 shrink-0 items-center justify-center rounded-full";
const tileIdle = "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200";
const tileActive = "bg-brand-600 text-white";
</script>

<template>
  <div class="min-h-screen bg-gray-100 dark:bg-gray-950">
    <AppNavbar />

    <div class="flex pt-16" :inert="composing || undefined">
      <!-- Studio navigation (desktop): the start-side column of the reference. -->
      <aside
        class="sticky top-16 hidden h-[calc(100vh-4rem)] w-[20rem] shrink-0 flex-col border-e border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900 lg:flex xl:w-[22rem]"
        data-testid="studio-sidebar"
      >
        <p class="px-5 pb-2 pt-5 text-2xl font-extrabold tracking-tight text-gray-900 dark:text-white">{{ t("studio.title") }}</p>
        <nav class="flex-1 overflow-y-auto px-3" :aria-label="t('studio.navLabel')">
          <ul class="space-y-1">
            <li>
              <RouterLink to="/studio" :class="[row, isActive('studio') && activeRow]" :aria-current="isActive('studio') ? 'page' : undefined" data-testid="studio-nav-studio">
                <span :class="[tile, isActive('studio') ? tileActive : tileIdle]"><Home class="h-5 w-5" aria-hidden="true" /></span>
                <span class="flex-1">{{ t("studio.nav.home") }}</span>
              </RouterLink>
            </li>
            <li v-for="section in sections" :key="section.key">
              <button
                type="button"
                :class="[row, 'w-full text-start']"
                :aria-expanded="expanded[section.key]"
                :aria-controls="`studio-${section.key}-items`"
                :data-testid="`studio-nav-${section.key}`"
                @click="expanded[section.key] = !expanded[section.key]"
              >
                <span :class="[tile, sectionActive(section.key) ? 'bg-brand-100 text-brand-700 dark:bg-brand-950 dark:text-brand-300' : tileIdle]">
                  <component :is="section.icon" class="h-5 w-5" aria-hidden="true" />
                </span>
                <span class="flex-1">{{ t(section.label) }}</span>
                <ChevronDown class="h-5 w-5 text-gray-500 transition" :class="expanded[section.key] && 'rotate-180'" aria-hidden="true" />
              </button>
              <ul v-show="expanded[section.key]" :id="`studio-${section.key}-items`" class="mt-1 space-y-1 ps-6">
                <li v-for="item in section.items" :key="item.name">
                  <RouterLink
                    :to="item.to"
                    :class="[row, isActive(item.name) && activeRow]"
                    :aria-current="isActive(item.name) ? 'page' : undefined"
                    :data-testid="`studio-nav-${item.name}`"
                  >
                    <span :class="[tile, 'h-9 w-9', isActive(item.name) ? tileActive : tileIdle]">
                      <component :is="item.icon" class="h-5 w-5" aria-hidden="true" />
                    </span>
                    <span class="flex-1">{{ t(item.label) }}</span>
                  </RouterLink>
                </li>
              </ul>
            </li>
          </ul>
        </nav>
        <div class="border-t border-gray-200 p-4 dark:border-gray-800">
          <StudioCreateMenu @create="(at) => open({ scheduleAt: at })" />
        </div>
      </aside>

      <main class="min-w-0 flex-1 px-2 pb-28 pt-3 sm:px-4 lg:pb-8 lg:pt-4">
        <!-- Studio navigation (phones and tablets): tabs under the top bar. -->
        <!-- Equal columns, icon over a label that may wrap: every tab fits at 390px. -->
        <div class="mb-3 lg:hidden" data-testid="studio-tabs">
          <nav class="card grid grid-cols-5 gap-0.5 p-1" :aria-label="t('studio.navLabel')">
            <RouterLink
              v-for="item in items"
              :key="item.name"
              :to="item.to"
              class="flex min-w-0 flex-col items-center gap-1 rounded-xl px-0.5 py-1.5 text-center text-[11px] font-semibold leading-tight text-gray-700 transition hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:text-gray-200 dark:hover:bg-gray-800 sm:text-xs"
              :class="isActive(item.name) && 'bg-brand-50 text-brand-700 dark:bg-gray-800 dark:text-white'"
              :aria-current="isActive(item.name) ? 'page' : undefined"
              :data-testid="`studio-tab-${item.name}`"
            >
              <component :is="item.icon" class="h-5 w-5 shrink-0" aria-hidden="true" />
              <span class="w-full break-words">{{ t(item.label) }}</span>
            </RouterLink>
          </nav>
        </div>
        <RouterView />
        <div class="mt-4 lg:hidden">
          <StudioCreateMenu @create="(at) => open({ scheduleAt: at })" />
        </div>
      </main>
    </div>

    <MobileBottomNavigation />

    <ComposerDialog
      v-if="composing"
      :draft="composeDraft"
      :schedule-at="composeAt"
      @close="composing = false"
      @published="touch"
      @saved="touch"
    />
  </div>
</template>
