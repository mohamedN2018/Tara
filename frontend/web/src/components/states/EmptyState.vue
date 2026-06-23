<script setup lang="ts">
import { Inbox } from "lucide-vue-next";
</script>

<template>
  <div class="flex flex-col items-center justify-center gap-3 py-16 text-center text-gray-500 dark:text-gray-400">
    <slot name="icon"><Inbox class="h-10 w-10 opacity-60" /></slot>
    <p class="max-w-sm text-sm"><slot /></p>
    <slot name="action" />
  </div>
</template>
