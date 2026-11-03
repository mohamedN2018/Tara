<script setup lang="ts">
import { Inbox } from "lucide-vue-next";
</script>

<template>
  <div class="flex flex-col items-center justify-center gap-3 py-16 text-center text-gray-500 dark:text-gray-400">
    <span class="flex h-16 w-16 items-center justify-center rounded-2xl bg-tara-gradient-soft text-brand-600 ring-1 ring-brand-200/60 dark:text-brand-300 dark:ring-brand-900">
      <slot name="icon"><Inbox class="h-8 w-8" /></slot>
    </span>
    <p class="max-w-sm text-sm"><slot /></p>
    <slot name="action" />
  </div>
</template>
