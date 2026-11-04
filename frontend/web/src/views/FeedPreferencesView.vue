<script setup lang="ts">
import { useI18n } from "vue-i18n";

import FeedPreferences from "@/components/feed/FeedPreferences.vue";
import AppShell from "@/components/layout/AppShell.vue";

const { t } = useI18n();
</script>

<template>
  <AppShell>
    <div class="mx-auto w-full max-w-[680px] space-y-4">
      <header class="px-1">
        <h1 class="text-2xl font-bold">{{ t("postsFeed.manage.title") }}</h1>
        <p class="text-sm text-gray-500 dark:text-gray-400">{{ t("postsFeed.manage.hint") }}</p>
      </header>
      <FeedPreferences />
    </div>
  </AppShell>
</template>
