<script setup lang="ts">
// The settings centre's start column: title, a search over the sections, the
// Account centre card, then the grouped sections and the policy links.
import { ChevronRight, FileText, Search, ShieldCheck, UserRound } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import TaraLogo from "@/components/brand/TaraLogo.vue";

import { SETTINGS_GROUPS, type SettingsSection } from "./sections";

defineProps<{ active?: SettingsSection | null }>();

const { t } = useI18n();
const query = ref("");

const POLICIES = [
  { key: "terms", to: "/legal/terms" },
  { key: "privacy", to: "/legal/privacy" },
  { key: "community", to: "/legal/community-standards" },
] as const;

const norm = (s: string) => s.toLocaleLowerCase().trim();
const groups = computed(() => {
  const q = norm(query.value);
  return SETTINGS_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter(
      (i) =>
        !q ||
        norm(t(`settingsCenter.sections.${i.id}.title`)).includes(q) ||
        norm(t(`settingsCenter.sections.${i.id}.desc`)).includes(q),
    ),
  })).filter((g) => g.items.length);
});

const item =
  "flex w-full items-center gap-3 rounded-lg px-2 py-2 text-start transition hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:hover:bg-gray-800";
const bubble =
  "flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gray-200/80 text-gray-800 dark:bg-gray-800 dark:text-gray-100";
</script>

<template>
  <nav :aria-label="t('settingsCenter.navLabel')" data-testid="settings-nav">
    <h1 class="mb-3 px-2 font-display text-2xl font-bold">{{ t("settingsCenter.title") }}</h1>

    <label class="relative mb-3 block px-2">
      <span class="sr-only">{{ t("settingsCenter.searchLabel") }}</span>
      <Search class="pointer-events-none absolute start-5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500 dark:text-gray-400" aria-hidden="true" />
      <input
        v-model="query"
        type="search"
        class="input rounded-full bg-gray-100 ps-10 dark:bg-gray-800"
        :placeholder="t('settingsCenter.searchPlaceholder')"
        data-testid="settings-search"
      />
    </label>

    <!-- Account centre card -->
    <RouterLink
      to="/settings/account"
      class="mx-2 mb-4 block rounded-xl p-3 shadow-sm ring-1 ring-gray-200/80 transition hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:ring-gray-800 dark:hover:bg-gray-800/60"
      :class="active === 'account' ? 'bg-brand-50 dark:bg-brand-950/40' : 'bg-white dark:bg-gray-900'"
      :aria-current="active === 'account' ? 'page' : undefined"
      data-testid="settings-account-centre"
    >
      <span class="mb-1 flex items-center gap-2 text-sm font-bold text-brand-700 dark:text-brand-300">
        <span aria-hidden="true" class="inline-flex"><TaraLogo variant="mark" :size="20" /></span>
        {{ t("settingsCenter.overview.title") }}
      </span>
      <span class="block text-xs text-gray-600 dark:text-gray-400">{{ t("settingsCenter.overview.lead") }}</span>
      <span class="mt-2 flex flex-col gap-1 text-sm">
        <span class="flex items-center gap-2"><UserRound class="h-4 w-4" aria-hidden="true" />{{ t("settingsCenter.overview.personal") }}</span>
        <span class="flex items-center gap-2"><ShieldCheck class="h-4 w-4" aria-hidden="true" />{{ t("settingsCenter.overview.security") }}</span>
      </span>
      <span class="mt-2 block text-sm font-semibold text-brand-700 dark:text-brand-300">{{ t("settingsCenter.overview.open") }}</span>
    </RouterLink>

    <p v-if="!groups.length" class="px-2 text-sm text-gray-500 dark:text-gray-400">{{ t("settingsCenter.noMatches") }}</p>

    <div v-for="g in groups" :key="g.id" class="mb-2 border-t border-gray-200 pt-3 dark:border-gray-800">
      <h2 class="px-2 pb-1 text-base font-bold">{{ t(`settingsCenter.groups.${g.id}`) }}</h2>
      <ul>
        <li v-for="i in g.items" :key="i.id">
          <RouterLink
            :to="`/settings/${i.id}`"
            :class="[item, active === i.id ? 'bg-brand-50 dark:bg-brand-950/40' : '']"
            :aria-current="active === i.id ? 'page' : undefined"
            :data-testid="`settings-nav-${i.id}`"
          >
            <span :class="bubble"><component :is="i.icon" class="h-5 w-5" aria-hidden="true" /></span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-semibold">{{ t(`settingsCenter.sections.${i.id}.title`) }}</span>
              <span class="block truncate text-xs text-gray-600 dark:text-gray-300">{{ t(`settingsCenter.sections.${i.id}.desc`) }}</span>
            </span>
            <ChevronRight class="h-4 w-4 shrink-0 text-gray-400 lg:hidden rtl:rotate-180" aria-hidden="true" />
          </RouterLink>
        </li>
      </ul>
    </div>

    <div v-if="!query" class="border-t border-gray-200 pt-3 dark:border-gray-800">
      <h2 class="px-2 pb-1 text-base font-bold">{{ t("settingsCenter.groups.policies") }}</h2>
      <ul>
        <li v-for="p in POLICIES" :key="p.key">
          <RouterLink :to="p.to" :class="item">
            <span :class="bubble"><FileText class="h-5 w-5" aria-hidden="true" /></span>
            <span class="flex-1 text-sm font-semibold">{{ t(`settingsCenter.policies.${p.key}`) }}</span>
          </RouterLink>
        </li>
      </ul>
    </div>
  </nav>
</template>
