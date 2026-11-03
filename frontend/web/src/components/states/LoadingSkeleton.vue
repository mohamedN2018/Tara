<script setup lang="ts">
withDefaults(defineProps<{ rows?: number }>(), { rows: 3 });
</script>

<template>
  <div class="space-y-4" role="status" aria-busy="true">
    <div v-for="i in rows" :key="i" class="card p-4 sm:p-5">
      <div class="flex items-center gap-3">
        <div class="skeleton h-11 w-11 rounded-full" />
        <div class="flex-1 space-y-2">
          <div class="skeleton h-3 w-1/3" />
          <div class="skeleton h-3 w-1/4" />
        </div>
      </div>
      <div class="mt-4 space-y-2">
        <div class="skeleton h-3 w-full" />
        <div class="skeleton h-3 w-5/6" />
      </div>
    </div>
  </div>
</template>
