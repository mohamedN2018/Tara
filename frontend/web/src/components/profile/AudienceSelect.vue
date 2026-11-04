<script setup lang="ts">
import { Globe, Lock, Users } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

// The owner's per-field audience (globe / friends / lock) next to an About
// section. Writes PUT /profile/me/privacy/ through the parent.
const props = defineProps<{ field: string; modelValue: string; disabled?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();

const LEVELS = ["public", "friends_only", "private"] as const;
const { t } = useI18n();
const icon = computed(() => (props.modelValue === "private" ? Lock : props.modelValue === "friends_only" ? Users : Globe));
</script>

<template>
  <span class="relative inline-flex items-center" :title="t('people.about.audience', { level: t(`people.levels.${modelValue}`) })">
    <component :is="icon" class="pointer-events-none absolute start-2 h-3.5 w-3.5 text-gray-600 dark:text-gray-300" aria-hidden="true" />
    <select
      :value="modelValue"
      :disabled="disabled"
      class="cursor-pointer appearance-none rounded-lg border-0 bg-gray-100 py-1 pe-3 ps-7 text-xs font-semibold text-gray-700 hover:bg-gray-200 focus:ring-2 focus:ring-brand-400 disabled:opacity-60 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
      :aria-label="t('people.about.audienceFor', { field: t(`profile.privacyFields.${field}`) })"
      :data-testid="`audience-${field}`"
      @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
    >
      <option v-for="l in LEVELS" :key="l" :value="l">{{ t(`people.levels.${l}`) }}</option>
    </select>
  </span>
</template>
