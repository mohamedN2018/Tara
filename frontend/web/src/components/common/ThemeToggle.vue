<script setup lang="ts">
import { Monitor, Moon, Sun } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

import { type Theme, useUiStore } from "@/stores/ui";

const { t } = useI18n();
const ui = useUiStore();
const options: { value: Theme; icon: typeof Sun }[] = [
  { value: "light", icon: Sun },
  { value: "dark", icon: Moon },
  { value: "system", icon: Monitor },
];
</script>

<template>
  <div class="inline-flex rounded-full border border-gray-200 bg-white p-0.5 dark:border-gray-800 dark:bg-gray-900">
    <button
      v-for="opt in options"
      :key="opt.value"
      class="rounded-full p-1.5 transition"
      :class="
        ui.theme === opt.value
          ? 'bg-brand-600 text-white shadow-sm shadow-brand-600/40'
          : 'text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 dark:text-gray-400'
      "
      :aria-pressed="ui.theme === opt.value"
      :aria-label="t(`settings.${opt.value}`)"
      :title="t(`settings.${opt.value}`)"
      @click="ui.setTheme(opt.value)"
    >
      <component :is="opt.icon" class="h-4 w-4" />
    </button>
  </div>
</template>
