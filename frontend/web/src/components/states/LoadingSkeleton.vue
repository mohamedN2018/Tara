<script setup lang="ts">
withDefaults(defineProps<{ rows?: number }>(), { rows: 3 });
</script>

<template>
  <div class="space-y-4" role="status" aria-busy="true">
    <div v-for="i in rows" :key="i" class="card animate-pulse p-4">
      <div class="flex items-center gap-3">
        <div class="h-10 w-10 rounded-full bg-gray-200 dark:bg-gray-800" />
        <div class="flex-1 space-y-2">
          <div class="h-3 w-1/3 rounded bg-gray-200 dark:bg-gray-800" />
          <div class="h-3 w-1/4 rounded bg-gray-200 dark:bg-gray-800" />
        </div>
      </div>
      <div class="mt-4 space-y-2">
        <div class="h-3 w-full rounded bg-gray-200 dark:bg-gray-800" />
        <div class="h-3 w-5/6 rounded bg-gray-200 dark:bg-gray-800" />
      </div>
    </div>
  </div>
</template>
