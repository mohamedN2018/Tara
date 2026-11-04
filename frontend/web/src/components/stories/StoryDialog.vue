<script setup lang="ts">
import { X } from "lucide-vue-next";
import { ref, useId } from "vue";

import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";

// The modal shell the story dialogs share: a bottom sheet on phones, centred on
// larger screens, focus kept inside, Escape to close. It sits above the story
// viewer, so a report or the viewer list opens on top of a playing story.
// `inline` keeps it inside the parent dialog (no teleport), so the two focus traps agree.
withDefaults(defineProps<{ title: string; closeLabel: string; wide?: boolean; inline?: boolean }>(), {
  wide: false,
  inline: false,
});
const emit = defineEmits<{ close: [] }>();

const titleId = useId();
const dialog = ref<HTMLElement | null>(null);
useEscapeKey(ref(true), () => emit("close"));
useFocusTrap(dialog);
</script>

<template>
  <Teleport to="body" :disabled="inline">
    <div class="fixed inset-0 z-[90] flex items-end justify-center bg-gray-950/60 p-0 backdrop-blur-sm sm:items-center sm:p-4">
      <div class="fixed inset-0" @click="emit('close')" />
      <div
        ref="dialog"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        tabindex="-1"
        class="card relative z-10 flex max-h-[90vh] w-full animate-pop-in flex-col rounded-b-none rounded-t-2xl p-4 shadow-pop sm:rounded-2xl sm:p-5"
        :class="wide ? 'sm:max-w-3xl' : 'sm:max-w-md'"
      >
        <div class="mb-3 flex items-center justify-between gap-2">
          <h2 :id="titleId" class="text-lg font-bold">{{ title }}</h2>
          <button
            type="button"
            class="rounded-full p-1.5 text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
            :aria-label="closeLabel"
            @click="emit('close')"
          >
            <X class="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <slot />
      </div>
    </div>
  </Teleport>
</template>
