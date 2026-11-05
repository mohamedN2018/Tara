<script setup lang="ts">
import { BarChart3, Inbox, Megaphone, Settings2, ShieldCheck, UsersRound } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { RouteLocationRaw } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { canEditPage, type Page } from "@/services/pages";

// "Manage Page" (plan 08): the Page team's shortcuts to tools that already
// exist (studio, the Page inbox, the ad centre, the Page's settings and team).
// Each entry shows only for the roles the server lets use it.
const props = defineProps<{ page: Page }>();
const emit = defineEmits<{ settings: []; transparency: [] }>();
const { t } = useI18n();

const INBOX_ROLES = ["owner", "admin", "editor", "moderator"];
const ADS_ROLES = ["owner", "admin", "advertiser"];
const STUDIO_ROLES = ["owner", "admin", "editor", "analyst"];
const role = computed(() => props.page.my_role ?? "");

interface Entry {
  key: string;
  icon: typeof Inbox;
  to?: RouteLocationRaw;
  action?: () => void;
}
const entries = computed<Entry[]>(() =>
  [
    STUDIO_ROLES.includes(role.value) && { key: "studio", icon: BarChart3, to: { name: "studio" } },
    INBOX_ROLES.includes(role.value) && { key: "inbox", icon: Inbox, to: { name: "page-inbox", params: { id: props.page.id } } },
    ADS_ROLES.includes(role.value) && { key: "ads", icon: Megaphone, to: { name: "ads" } },
    canEditPage(props.page) && { key: "settings", icon: Settings2, action: () => emit("settings") },
    { key: "team", icon: UsersRound, to: { name: "page", params: { handle: props.page.handle }, query: { tab: "team" } } },
    { key: "transparency", icon: ShieldCheck, action: () => emit("transparency") },
  ].filter(Boolean) as Entry[],
);
const row =
  "flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-start transition hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:hover:bg-gray-800";
</script>

<template>
  <nav v-if="page.my_role" class="card p-3" aria-labelledby="manage-page-title" data-testid="manage-page-rail">
    <div class="mb-2 flex items-center gap-3 px-1">
      <UserAvatar :name="page.name" :media-id="page.avatar_media_id" :size="40" />
      <div class="min-w-0">
        <h2 id="manage-page-title" class="text-lg font-bold">{{ t("profileTools.page.manage") }}</h2>
        <p class="truncate text-xs text-gray-600 dark:text-gray-400"><bdi>{{ page.name }}</bdi> · {{ t(`pages.roles.${page.my_role}`) }}</p>
      </div>
    </div>
    <ul class="space-y-0.5">
      <li v-for="e in entries" :key="e.key">
        <RouterLink v-if="e.to" :to="e.to" :class="row" :data-testid="`manage-page-${e.key}`">
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-700 dark:bg-brand-950/50 dark:text-brand-200">
            <component :is="e.icon" class="h-5 w-5" aria-hidden="true" />
          </span>
          <span class="min-w-0">
            <span class="block text-sm font-semibold">{{ t(`profileTools.page.${e.key}`) }}</span>
            <span class="block truncate text-xs text-gray-600 dark:text-gray-400">{{ t(`profileTools.page.${e.key}Hint`) }}</span>
          </span>
        </RouterLink>
        <button v-else type="button" :class="row" :data-testid="`manage-page-${e.key}`" @click="e.action?.()">
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-700 dark:bg-brand-950/50 dark:text-brand-200">
            <component :is="e.icon" class="h-5 w-5" aria-hidden="true" />
          </span>
          <span class="min-w-0">
            <span class="block text-sm font-semibold">{{ t(`profileTools.page.${e.key}`) }}</span>
            <span class="block truncate text-xs text-gray-600 dark:text-gray-400">{{ t(`profileTools.page.${e.key}Hint`) }}</span>
          </span>
        </button>
      </li>
    </ul>
  </nav>
</template>
