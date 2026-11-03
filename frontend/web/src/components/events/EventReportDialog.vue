<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import { REPORT_ERRORS } from "@/services/post";
import { eventsService, REPORT_REASONS, type ReportReason } from "@/services/events";
import { useToastStore } from "@/stores/toasts";

import EventDialog from "./EventDialog.vue";

// Reasons are a fixed list, so the report on the bus carries no free text.
const props = defineProps<{ eventId: string }>();
const emit = defineEmits<{ close: []; reported: [] }>();

const { t } = useI18n();
const toasts = useToastStore();
const reason = ref<ReportReason | null>(null);
const sending = ref(false);

async function send() {
  if (!reason.value || sending.value) return;
  sending.value = true;
  try {
    await eventsService.report(props.eventId, reason.value);
    toasts.success(t("events.reportSent"));
    emit("reported");
  } catch (e) {
    toasts.error(e, REPORT_ERRORS);
  } finally {
    sending.value = false;
  }
}
</script>

<template>
  <EventDialog :title="t('events.reportTitle')" @close="emit('close')">
    <fieldset class="space-y-1 overflow-y-auto">
      <legend class="mb-2 text-sm text-gray-600 dark:text-gray-300">{{ t("events.reportPrompt") }}</legend>
      <label
        v-for="r in REPORT_REASONS"
        :key="r"
        class="flex cursor-pointer items-center gap-3 rounded-xl px-2 py-2 text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800"
      >
        <input v-model="reason" type="radio" name="event-report-reason" :value="r" class="accent-brand-600" />
        {{ t(`events.reasons.${r}`) }}
      </label>
    </fieldset>
    <div class="mt-3 flex justify-end gap-2">
      <button type="button" class="btn-ghost" @click="emit('close')">{{ t("feed.cancel") }}</button>
      <button type="button" class="btn-danger" :disabled="!reason || sending" @click="send">{{ t("events.report") }}</button>
    </div>
  </EventDialog>
</template>
