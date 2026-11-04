<script setup lang="ts">
// Report one message to moderation (POST /messages/{id}/report/). Chat sends
// moderation a text snapshot only; the sender is never told who reported it.
import { X } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { chatService, MESSAGE_REPORT_REASONS, type MessageReportReason } from "@/services/chat";
import { useToastStore } from "@/stores/toasts";
import type { Message } from "@/types";

const props = defineProps<{ message: Message }>();
const emit = defineEmits<{ close: []; sent: [] }>();

const { t } = useI18n();
const toasts = useToastStore();
const reason = ref<MessageReportReason | "">("");
const sending = ref(false);
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);
useEscapeKey(
  computed(() => true),
  () => !sending.value && emit("close"),
);

async function submit() {
  if (!reason.value || sending.value) return;
  sending.value = true;
  try {
    await chatService.reportMessage(props.message.id, reason.value);
    toasts.success(t("messenger.reported"));
    emit("sent");
    emit("close");
  } catch (e) {
    toasts.error(e);
  } finally {
    sending.value = false;
  }
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[70] flex items-end justify-center bg-gray-950/60 backdrop-blur-sm sm:items-center sm:p-4">
      <div class="fixed inset-0" @click="!sending && emit('close')" />
      <form
        ref="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="message-report-title"
        tabindex="-1"
        class="card relative z-10 max-h-[92vh] w-full animate-pop-in overflow-y-auto rounded-b-none p-0 shadow-pop sm:max-w-md sm:rounded-2xl"
        data-testid="message-report-dialog"
        @submit.prevent="submit"
      >
        <div class="flex items-center justify-between border-b border-gray-100 px-4 py-3 dark:border-gray-800">
          <h2 id="message-report-title" class="text-lg font-bold">{{ t("messenger.reportTitle") }}</h2>
          <button type="button" class="rounded-full p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" :aria-label="t('messenger.cancel')" @click="emit('close')">
            <X class="h-5 w-5" />
          </button>
        </div>
        <div class="space-y-3 p-4">
          <p class="text-sm text-gray-600 dark:text-gray-300">{{ t("messenger.reportHint") }}</p>
          <blockquote v-if="message.body" class="line-clamp-3 rounded-lg bg-gray-100 px-3 py-2 text-sm dark:bg-gray-800" dir="auto">{{ message.body }}</blockquote>
          <fieldset>
            <legend class="mb-2 text-sm font-semibold">{{ t("messenger.reportReason") }}</legend>
            <div class="space-y-1">
              <label
                v-for="r in MESSAGE_REPORT_REASONS"
                :key="r"
                class="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2 hover:bg-gray-50 dark:hover:bg-gray-800/60"
              >
                <input v-model="reason" type="radio" name="message-report-reason" :value="r" class="h-4 w-4 accent-brand-600" />
                <span class="text-sm">{{ t(`messenger.reasons.${r}`) }}</span>
              </label>
            </div>
          </fieldset>
        </div>
        <div class="flex justify-end gap-2 border-t border-gray-100 px-4 py-3 dark:border-gray-800">
          <button type="button" class="btn-ghost" @click="emit('close')">{{ t("messenger.cancel") }}</button>
          <button type="submit" class="btn-primary" :disabled="!reason || sending" data-testid="message-report-send">{{ t("messenger.reportSend") }}</button>
        </div>
      </form>
    </div>
  </Teleport>
</template>
