<script setup lang="ts">
import { Monitor, Moon, Sun } from "lucide-vue-next";

import { type Theme, useUiStore } from "@/stores/ui";

const ui = useUiStore();
const options: { value: Theme; icon: typeof Sun }[] = [
  { value: "light", icon: Sun },
  { value: "dark", icon: Moon },
  { value: "system", icon: Monitor },
];
</script>

<template>
  <div class="inline-flex rounded-lg border border-gray-200 p-0.5 dark:border-gray-700">
    <button
      v-for="opt in options"
      :key="opt.value"
      class="rounded-md p-1.5 transition"
      :class="
        ui.theme === opt.value
          ? 'bg-brand-600 text-white'
          : 'text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800'
      "
      :aria-pressed="ui.theme === opt.value"
      @click="ui.setTheme(opt.value)"
    >
      <component :is="opt.icon" class="h-4 w-4" />
    </button>
  </div>
</template>
