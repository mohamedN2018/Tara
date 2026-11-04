<script setup lang="ts">
import { X } from "lucide-vue-next";
import { ref, useId } from "vue";
import { useI18n } from "vue-i18n";

import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";

// The modal shell of the report, appeal and case dialogs: a bottom sheet on
// phones, centred on larger screens, focus kept inside, Escape to close.
withDefaults(defineProps<{ title: string; wide?: boolean; testid?: string }>(), { wide: false, testid: "safety-dialog" });
const emit = defineEmits<{ close: [] }>();

const { t } = useI18n();
const titleId = useId();
const dialog = ref<HTMLElement | null>(null);
useEscapeKey(ref(true), () => emit("close"));
useFocusTrap(dialog);
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-end justify-center bg-gray-950/60 p-0 backdrop-blur-sm sm:items-center sm:p-4">
    <div class="fixed inset-0" aria-hidden="true" @click="emit('close')" />
    <div
      ref="dialog"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId"
      tabindex="-1"
      class="card relative z-10 flex max-h-[88vh] w-full animate-pop-in flex-col rounded-b-none rounded-t-2xl p-4 shadow-pop sm:rounded-2xl sm:p-5"
      :class="wide ? 'sm:max-w-2xl' : 'sm:max-w-md'"
      :data-testid="testid"
    >
      <div class="mb-3 flex items-center justify-between gap-2 border-b border-gray-100 pb-3 dark:border-gray-800">
        <h2 :id="titleId" class="text-lg font-bold" dir="auto">{{ title }}</h2>
        <button type="button" class="icon-btn" :aria-label="t('safety.close')" @click="emit('close')">
          <X class="h-5 w-5" aria-hidden="true" />
        </button>
      </div>
      <div class="min-h-0 flex-1 overflow-y-auto">
        <slot />
      </div>
      <div v-if="$slots.footer" class="mt-3 flex flex-wrap justify-end gap-2 border-t border-gray-100 pt-3 dark:border-gray-800">
        <slot name="footer" />
      </div>
    </div>
  </div>
</template>
