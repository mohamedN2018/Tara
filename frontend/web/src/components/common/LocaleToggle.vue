<script setup lang="ts">
import { Languages } from "lucide-vue-next";

import { useUiStore } from "@/stores/ui";

const ui = useUiStore();

function toggle() {
  ui.changeLocale(ui.locale === "ar" ? "en" : "ar");
}
</script>

<template>
  <button class="btn-ghost px-2" :title="ui.locale === 'ar' ? 'English' : 'العربية'" @click="toggle">
    <Languages class="h-4 w-4" />
    <span class="text-xs font-semibold uppercase">{{ ui.locale === "ar" ? "EN" : "ع" }}</span>
  </button>
</template>
