<script setup lang="ts">
// An on/off row: the label on the start side, a switch on the end side.
import { useId } from "vue";

defineProps<{ modelValue: boolean; label: string; hint?: string; disabled?: boolean; testid?: string }>();
const emit = defineEmits<{ "update:modelValue": [value: boolean] }>();
const id = useId();
</script>

<template>
  <div class="flex items-start justify-between gap-4 py-2">
    <div class="min-w-0">
      <span :id="`${id}-label`" class="block text-sm font-medium">{{ label }}</span>
      <span v-if="hint" :id="`${id}-hint`" class="mt-0.5 block text-xs text-gray-500 dark:text-gray-400">{{ hint }}</span>
    </div>
    <button
      type="button"
      role="switch"
      :aria-checked="modelValue"
      :aria-labelledby="`${id}-label`"
      :aria-describedby="hint ? `${id}-hint` : undefined"
      :disabled="disabled"
      :data-testid="testid"
      class="relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 disabled:opacity-60"
      :class="modelValue ? 'bg-brand-600' : 'bg-gray-300 dark:bg-gray-700'"
      @click="emit('update:modelValue', !modelValue)"
    >
      <span
        aria-hidden="true"
        class="inline-block h-5 w-5 rounded-full bg-white shadow transition"
        :class="modelValue ? 'translate-x-[1.375rem] rtl:-translate-x-[1.375rem]' : 'translate-x-0.5 rtl:-translate-x-0.5'"
      />
    </button>
  </div>
</template>
