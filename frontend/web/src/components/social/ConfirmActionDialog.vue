<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";

// A small "are you sure?" for people actions (unfriend, block).
const props = withDefaults(
  defineProps<{ title: string; hint?: string; confirmLabel: string; busy?: boolean; danger?: boolean }>(),
  { hint: "", busy: false, danger: true },
);
const emit = defineEmits<{ confirm: []; cancel: [] }>();

const { t } = useI18n();
const dialog = ref<HTMLElement | null>(null);
const uid = `cad-${Math.random().toString(36).slice(2, 9)}`;
useFocusTrap(dialog);
useEscapeKey(
  computed(() => true),
  () => !props.busy && emit("cancel"),
);
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[70] flex items-end justify-center bg-gray-950/60 backdrop-blur-sm sm:items-center sm:p-4">
      <div class="fixed inset-0" @click="!busy && emit('cancel')" />
      <div
        ref="dialog"
        role="alertdialog"
        aria-modal="true"
        :aria-labelledby="`${uid}-title`"
        :aria-describedby="hint ? `${uid}-hint` : undefined"
        tabindex="-1"
        class="card relative z-10 w-full animate-pop-in rounded-b-none p-5 shadow-pop sm:max-w-md sm:rounded-2xl"
        data-testid="confirm-action"
      >
        <h2 :id="`${uid}-title`" class="text-lg font-bold" dir="auto">{{ title }}</h2>
        <p v-if="hint" :id="`${uid}-hint`" class="mt-2 text-sm text-gray-600 dark:text-gray-300">{{ hint }}</p>
        <div class="mt-5 flex justify-end gap-2">
          <button type="button" class="btn-ghost" :disabled="busy" @click="emit('cancel')">{{ t("people.actions.cancel") }}</button>
          <button type="button" :class="danger ? 'btn-danger' : 'btn-primary'" :disabled="busy" @click="emit('confirm')">
            {{ confirmLabel }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
