<script setup lang="ts">
// A filter chip (ported from QTech's FilterChip.vue).
// A button with aria-pressed: it toggles a view of the current page, so nothing
// navigates and nothing submits. The count sits inside the chip; a chip that
// could only return nothing is not rendered by the caller at all.
import { Check } from "lucide-vue-next";

withDefaults(defineProps<{ label: string; active?: boolean; count?: number | null }>(), {
  active: false,
  count: null,
});
defineEmits<{ toggle: [] }>();
</script>

<template>
  <button
    type="button"
    class="chip min-h-9 shrink-0 text-xs"
    :class="{ 'chip-active': active }"
    :aria-pressed="active"
    @click="$emit('toggle')"
  >
    <Check v-if="active" class="h-3.5 w-3.5" aria-hidden="true" />
    <span dir="auto">{{ label }}</span>
    <span
      v-if="count !== null"
      class="rounded-full px-1.5 text-[11px] font-bold tabular-nums"
      :class="active ? 'bg-white/20' : 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400'"
    >
      {{ count }}
    </span>
  </button>
</template>
