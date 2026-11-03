<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

defineProps<{ message?: string }>();
defineEmits<{ retry: [] }>();

const { t } = useI18n();
</script>

<template>
  <div class="flex flex-col items-center justify-center gap-3 py-16 text-center">
    <span class="flex h-16 w-16 items-center justify-center rounded-2xl bg-amber-50 text-amber-500 ring-1 ring-amber-200 dark:bg-amber-950/40 dark:ring-amber-900">
      <AlertTriangle class="h-8 w-8" />
    </span>
    <p class="max-w-sm text-sm text-gray-600 dark:text-gray-300">
      {{ message || t("states.error") }}
    </p>
    <button class="btn-soft" @click="$emit('retry')">{{ t("states.retry") }}</button>
  </div>
</template>
