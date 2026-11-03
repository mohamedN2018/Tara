<script setup lang="ts">
import { X } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { chatService } from "@/services/chat";
import { useToastStore } from "@/stores/toasts";
import type { Conversation, Message } from "@/types";

const MAX_TARGETS = 5;

const props = defineProps<{
  message: Message;
  conversations: Conversation[];
  titleOf: (c: Conversation) => string;
}>();
const emit = defineEmits<{ close: []; done: [copies: Message[]] }>();

const { t } = useI18n();
const toasts = useToastStore();
const open = ref(true);
useEscapeKey(open, () => emit("close"));
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);

const chosen = ref<string[]>([]);
const busy = ref(false);

function toggle(id: string) {
  if (chosen.value.includes(id)) chosen.value = chosen.value.filter((c) => c !== id);
  else if (chosen.value.length < MAX_TARGETS) chosen.value = [...chosen.value, id];
}

async function submit() {
  if (!chosen.value.length || busy.value) return;
  busy.value = true;
  try {
    const copies = await chatService.forward(props.message.id, chosen.value);
    toasts.push({ text: t("messages.forwardSent"), icon: "success" });
    emit("done", copies);
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-end justify-center bg-gray-950/60 p-0 backdrop-blur-sm sm:items-center sm:p-4">
    <div class="fixed inset-0" @click="emit('close')" />
    <div
      ref="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="forward-title"
      tabindex="-1"
      class="card relative z-10 max-h-[92vh] w-full animate-pop-in overflow-y-auto rounded-b-none rounded-t-2xl p-4 shadow-pop sm:max-w-md sm:rounded-2xl sm:p-5"
    >
      <div class="mb-3 flex items-center justify-between">
        <h2 id="forward-title" class="text-lg font-bold">{{ t("messages.forwardTo") }}</h2>
        <button class="rounded-full p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" :aria-label="t('messages.close')" @click="emit('close')">
          <X class="h-5 w-5" />
        </button>
      </div>
      <ul class="max-h-80 space-y-1 overflow-y-auto" data-testid="forward-targets">
        <li v-for="c in conversations" :key="c.id">
          <label class="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-800/50">
            <input
              type="checkbox"
              class="h-4 w-4"
              :checked="chosen.includes(c.id)"
              :disabled="!chosen.includes(c.id) && chosen.length >= MAX_TARGETS"
              @change="toggle(c.id)"
            />
            <UserAvatar :name="titleOf(c)" :size="32" />
            <span class="min-w-0 flex-1 truncate text-sm" dir="auto">{{ titleOf(c) }}</span>
          </label>
        </li>
      </ul>
      <button class="btn-primary mt-4 w-full justify-center" :disabled="busy || !chosen.length" @click="submit">
        {{ t("messages.forward") }}
      </button>
    </div>
  </div>
</template>
