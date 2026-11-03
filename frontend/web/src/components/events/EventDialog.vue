<script setup lang="ts">
import { X } from "lucide-vue-next";
import { ref, useId } from "vue";
import { useI18n } from "vue-i18n";

import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";

// The modal shell the event dialogs share: a bottom sheet on phones, centred
// on larger screens, with focus kept inside and Escape to close.
defineProps<{ title: string }>();
const emit = defineEmits<{ close: [] }>();

const { t } = useI18n();
const titleId = useId();
const dialog = ref<HTMLElement | null>(null);
useEscapeKey(ref(true), () => emit("close"));
useFocusTrap(dialog);
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-end justify-center bg-gray-950/60 p-0 backdrop-blur-sm sm:items-center sm:p-4">
    <div class="fixed inset-0" @click="emit('close')" />
    <div
      ref="dialog"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId"
      tabindex="-1"
      class="card relative z-10 flex max-h-[85vh] w-full animate-pop-in flex-col rounded-b-none rounded-t-2xl p-4 shadow-pop sm:max-w-md sm:rounded-2xl sm:p-5"
    >
      <div class="mb-3 flex items-center justify-between gap-2">
        <h2 :id="titleId" class="text-lg font-bold">{{ title }}</h2>
        <button type="button" class="rounded-full p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" :aria-label="t('events.close')" @click="emit('close')">
          <X class="h-5 w-5" aria-hidden="true" />
        </button>
      </div>
      <slot />
    </div>
  </div>
</template>
