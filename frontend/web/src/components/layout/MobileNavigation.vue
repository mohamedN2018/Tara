<script setup lang="ts">
import { useI18n } from "vue-i18n";

import { navItems } from "./navItems";

const { t } = useI18n();
// Show the five most important destinations on the mobile bar.
const items = navItems.filter((i) => i.name !== "settings");
</script>

<template>
  <nav
    class="fixed inset-x-0 bottom-0 z-30 flex items-stretch border-t border-gray-200 bg-white pb-[env(safe-area-inset-bottom)] dark:border-gray-800 dark:bg-gray-950 lg:hidden"
  >
    <RouterLink
      v-for="item in items"
      :key="item.name"
      :to="item.route"
      class="flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-medium text-gray-500"
      active-class="text-brand-600"
    >
      <component :is="item.icon" class="h-5 w-5" />
      {{ t(item.labelKey) }}
    </RouterLink>
  </nav>
</template>
