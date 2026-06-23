<script setup lang="ts">
import { useI18n } from "vue-i18n";

import LocaleToggle from "@/components/common/LocaleToggle.vue";
import ThemeToggle from "@/components/common/ThemeToggle.vue";

const { t } = useI18n();
</script>

<template>
  <div class="flex min-h-screen flex-col">
    <header class="flex items-center justify-between p-4">
      <span class="text-2xl font-extrabold text-brand-600">{{ t("app.name") }}</span>
      <div class="flex items-center gap-2">
        <LocaleToggle />
        <ThemeToggle />
      </div>
    </header>

    <main class="flex flex-1 flex-col items-center justify-center px-6 text-center">
      <h1 class="max-w-2xl text-4xl font-extrabold leading-tight sm:text-5xl">
        {{ t("landing.tagline") }}
      </h1>
      <div class="mt-8 flex gap-3">
        <RouterLink to="/register" class="btn-primary px-6 py-3 text-base">
          {{ t("landing.getStarted") }}
        </RouterLink>
        <RouterLink to="/login" class="btn-ghost px-6 py-3 text-base">
          {{ t("auth.login") }}
        </RouterLink>
      </div>
    </main>
  </div>
</template>
