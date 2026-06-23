<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

defineProps<{ message?: string }>();
defineEmits<{ retry: [] }>();

const { t } = useI18n();
</script>

<template>
  <div class="flex flex-col items-center justify-center gap-3 py-16 text-center">
    <AlertTriangle class="h-10 w-10 text-amber-500" />
    <p class="max-w-sm text-sm text-gray-600 dark:text-gray-300">
      {{ message || t("states.error") }}
    </p>
    <button class="btn-ghost" @click="$emit('retry')">{{ t("states.retry") }}</button>
  </div>
</template>
