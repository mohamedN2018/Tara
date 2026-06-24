<script setup lang="ts">
import { Shield } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { useAuthStore } from "@/stores/auth";

import { navItems } from "./navItems";

const { t } = useI18n();
const auth = useAuthStore();
</script>

<template>
  <nav class="flex flex-col gap-0.5 p-2" :aria-label="t('nav.home')">
    <!-- Profile shortcut -->
    <RouterLink
      v-if="auth.profile"
      :to="`/u/${auth.profile.handle}`"
      class="flex items-center gap-3 rounded-xl px-2 py-2 transition hover:bg-gray-200/60 dark:hover:bg-gray-800"
    >
      <UserAvatar :name="auth.profile.display_name" :media-id="auth.profile.avatar_media_id" :size="36" />
      <span class="truncate text-sm font-semibold">{{ auth.profile.display_name }}</span>
    </RouterLink>

    <RouterLink
      v-for="item in navItems"
      :key="item.name"
      :to="item.route"
      class="flex items-center gap-3 rounded-xl px-2 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-200/60 dark:text-gray-200 dark:hover:bg-gray-800"
      active-class="bg-brand-50 text-brand-700 dark:bg-brand-950/60 dark:text-brand-300"
    >
      <span class="flex h-9 w-9 items-center justify-center rounded-full bg-gray-100 dark:bg-gray-800">
        <component :is="item.icon" class="h-5 w-5" />
      </span>
      {{ t(item.labelKey) }}
    </RouterLink>

    <RouterLink
      v-if="auth.isStaff"
      to="/admin"
      class="flex items-center gap-3 rounded-xl px-2 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-200/60 dark:text-gray-200 dark:hover:bg-gray-800"
      active-class="bg-brand-50 text-brand-700 dark:bg-brand-950/60 dark:text-brand-300"
    >
      <span class="flex h-9 w-9 items-center justify-center rounded-full bg-gray-100 dark:bg-gray-800">
        <Shield class="h-5 w-5" />
      </span>
      {{ t("nav.admin") }}
    </RouterLink>

    <p class="px-3 pt-4 text-xs text-gray-400">{{ t("app.name") }} · © 2026</p>
  </nav>
</template>
