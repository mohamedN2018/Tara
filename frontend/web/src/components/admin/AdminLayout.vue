<script setup lang="ts">
import { Shield } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

import AdminNav from "@/components/admin/AdminNav.vue";
import AppShell from "@/components/layout/AppShell.vue";

/**
 * The admin console frame: the app's top bar, then the console rail of
 * sections (desktop) or chips (phones) beside the section's content. The
 * console rail replaces the app's main navigation column, as in other admin
 * consoles (the main menu stays one tap away in the top bar). Logical
 * properties only, so the rail sits on the start side in RTL.
 */
withDefaults(defineProps<{ title: string; subtitle?: string }>(), { subtitle: "" });
const { t } = useI18n();
</script>

<template>
  <AppShell :right="false" :left="false">
    <div class="lg:grid lg:grid-cols-[16rem_minmax(0,1fr)] lg:gap-6" data-testid="admin-console">
      <aside class="hidden lg:block">
        <div class="card sticky top-20 p-3">
          <p class="mb-2 flex items-center gap-2 px-2 text-xs font-bold uppercase tracking-wide text-gray-500 dark:text-gray-400">
            <Shield class="h-4 w-4 text-brand-600 dark:text-brand-300" aria-hidden="true" />
            {{ t("safety.console.title") }}
          </p>
          <AdminNav vertical />
        </div>
      </aside>
      <div class="min-w-0">
        <div class="mb-3 lg:hidden"><AdminNav /></div>
        <header class="mb-4 flex flex-wrap items-end justify-between gap-2">
          <div class="min-w-0">
            <h1 class="text-xl font-bold sm:text-2xl" dir="auto">{{ title }}</h1>
            <p v-if="subtitle" class="mt-0.5 text-sm text-gray-500 dark:text-gray-400">{{ subtitle }}</p>
          </div>
          <slot name="actions" />
        </header>
        <slot />
      </div>
    </div>
  </AppShell>
</template>
