<script setup lang="ts">
import { useI18n } from "vue-i18n";

const { t } = useI18n();
</script>

<template>
  <div class="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
    <p class="text-6xl font-extrabold text-brand-600">404</p>
    <p class="text-gray-500">{{ t("states.notFound") }}</p>
    <RouterLink to="/home" class="btn-primary">{{ t("states.goHome") }}</RouterLink>
  </div>
</template>
