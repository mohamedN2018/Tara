<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import EventDialog from "@/components/events/EventDialog.vue";
import { GROUP_REPORT_REASONS, type GroupReportReason, groupsService } from "@/services/groups";
import { REPORT_ERRORS } from "@/services/post";
import { useToastStore } from "@/stores/toasts";

// Reasons are a fixed list, so `group.reported` carries no free text.
const props = defineProps<{ groupRef: string }>();
const emit = defineEmits<{ close: []; reported: [] }>();

const { t } = useI18n();
const toasts = useToastStore();
const reason = ref<GroupReportReason | null>(null);
const sending = ref(false);

async function send() {
  if (!reason.value || sending.value) return;
  sending.value = true;
  try {
    await groupsService.report(props.groupRef, reason.value);
    toasts.success(t("groups.report.sent"));
    emit("reported");
  } catch (e) {
    toasts.error(e, REPORT_ERRORS);
  } finally {
    sending.value = false;
  }
}
</script>

<template>
  <EventDialog :title="t('groups.report.title')" @close="emit('close')">
    <fieldset class="space-y-1 overflow-y-auto">
      <legend class="mb-2 text-sm text-gray-600 dark:text-gray-300">{{ t("groups.report.prompt") }}</legend>
      <label
        v-for="r in GROUP_REPORT_REASONS"
        :key="r"
        class="flex cursor-pointer items-center gap-3 rounded-xl px-2 py-2 text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800"
      >
        <input v-model="reason" type="radio" name="group-report-reason" :value="r" class="accent-brand-600" />
        {{ t(`events.reasons.${r}`) }}
      </label>
    </fieldset>
    <div class="mt-3 flex justify-end gap-2">
      <button type="button" class="btn-ghost" @click="emit('close')">{{ t("feed.cancel") }}</button>
      <button type="button" class="btn-danger" :disabled="!reason || sending" @click="send">{{ t("groups.report.submit") }}</button>
    </div>
  </EventDialog>
</template>
