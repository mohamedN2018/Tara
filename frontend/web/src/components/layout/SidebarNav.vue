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
  <nav class="flex h-full flex-col gap-1 p-3">
    <RouterLink
      to="/home"
      class="mb-2 flex items-center gap-2 px-3 py-2 text-xl font-extrabold text-brand-600"
    >
      {{ t("app.name") }}
    </RouterLink>

    <RouterLink
      v-for="item in navItems"
      :key="item.name"
      :to="item.route"
      class="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-gray-700 transition hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-800"
      active-class="bg-brand-50 text-brand-700 dark:bg-brand-950 dark:text-brand-300"
    >
      <component :is="item.icon" class="h-5 w-5" />
      {{ t(item.labelKey) }}
    </RouterLink>

    <RouterLink
      v-if="auth.isStaff"
      to="/admin"
      class="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-gray-700 transition hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-800"
      active-class="bg-brand-50 text-brand-700 dark:bg-brand-950 dark:text-brand-300"
    >
      <Shield class="h-5 w-5" />
      {{ t("nav.admin") }}
    </RouterLink>

    <div class="mt-auto">
      <RouterLink
        v-if="auth.profile"
        :to="`/u/${auth.profile.handle}`"
        class="flex items-center gap-3 rounded-lg px-3 py-2.5 transition hover:bg-gray-100 dark:hover:bg-gray-800"
      >
        <UserAvatar
          :name="auth.profile.display_name"
          :media-id="auth.profile.avatar_media_id"
          :size="36"
        />
        <span class="min-w-0">
          <span class="block truncate text-sm font-medium">{{ auth.profile.display_name }}</span>
          <span class="block truncate text-xs text-gray-500">@{{ auth.profile.handle }}</span>
        </span>
      </RouterLink>
    </div>
  </nav>
</template>
