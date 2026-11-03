<script setup lang="ts">
import { useI18n } from "vue-i18n";

import TaraLogo from "@/components/brand/TaraLogo.vue";

const { t } = useI18n();
</script>

<template>
  <div class="relative flex min-h-screen flex-col items-center justify-center gap-5 overflow-hidden bg-gray-100 px-6 text-center dark:bg-gray-950">
    <div aria-hidden="true" class="pointer-events-none absolute h-[28rem] w-[28rem] rounded-full bg-brand-600/20 blur-3xl" />
    <TaraLogo variant="mark" :size="72" :label="t('app.name')" class="relative" />
    <p class="text-gradient relative font-display text-8xl font-extrabold leading-none">404</p>
    <p class="relative max-w-sm text-gray-600 dark:text-gray-300">{{ t("states.notFound") }}</p>
    <RouterLink to="/home" class="btn-gradient relative px-6 py-3">{{ t("states.goHome") }}</RouterLink>
  </div>
</template>
