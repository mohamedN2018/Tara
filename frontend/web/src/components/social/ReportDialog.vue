<script setup lang="ts">
import { X } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { adminService } from "@/services/admin";
import { useToastStore } from "@/stores/toasts";

// "Find support or report": files POST /moderation/reports/file/ for a user or
// a page. The server refuses self-reports and throttles; moderation turns the
// report into a case the target can later appeal.
const props = defineProps<{ targetType: "user" | "page"; targetId: string; name: string }>();
const emit = defineEmits<{ close: []; sent: [] }>();

const REASONS = ["fake", "impersonation", "harassment", "hate", "spam", "violence", "nudity", "other"] as const;
const MAX = 200;

const { t } = useI18n();
const toasts = useToastStore();
const reason = ref<(typeof REASONS)[number] | "">("");
const details = ref("");
const sending = ref(false);
const dialog = ref<HTMLElement | null>(null);
const uid = `report-${Math.random().toString(36).slice(2, 9)}`;
useFocusTrap(dialog);
useEscapeKey(
  computed(() => true),
  () => !sending.value && emit("close"),
);

// The stored reason is short: the key, then whatever the reporter added.
const payloadReason = computed(() => {
  const extra = details.value.trim();
  return (extra ? `${reason.value}: ${extra}` : reason.value).slice(0, MAX);
});

async function submit() {
  if (!reason.value || sending.value) return;
  sending.value = true;
  try {
    await adminService.report({ target_type: props.targetType, target_id: props.targetId, reason: payloadReason.value });
    toasts.success(t("people.report.sent"));
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
        :aria-labelledby="`${uid}-title`"
        tabindex="-1"
        class="card relative z-10 max-h-[92vh] w-full animate-pop-in overflow-y-auto rounded-b-none p-0 shadow-pop sm:max-w-md sm:rounded-2xl"
        data-testid="report-dialog"
        @submit.prevent="submit"
      >
        <div class="flex items-center justify-between border-b border-gray-100 px-4 py-3 dark:border-gray-800">
          <h2 :id="`${uid}-title`" class="text-lg font-bold" dir="auto">{{ t("people.report.title", { name }) }}</h2>
          <button type="button" class="rounded-full p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" :aria-label="t('people.actions.cancel')" @click="emit('close')">
            <X class="h-5 w-5" />
          </button>
        </div>
        <div class="space-y-3 p-4">
          <p class="text-sm text-gray-600 dark:text-gray-300" dir="auto">{{ t("people.report.hint", { name }) }}</p>
          <fieldset>
            <legend class="mb-2 text-sm font-semibold">{{ t("people.report.reasonLabel") }}</legend>
            <div class="space-y-1">
              <label
                v-for="r in REASONS"
                :key="r"
                class="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800"
              >
                <input v-model="reason" type="radio" :name="`${uid}-reason`" :value="r" class="accent-brand-600" />
                {{ t(`people.report.reasons.${r}`) }}
              </label>
            </div>
          </fieldset>
          <div>
            <label :for="`${uid}-details`" class="mb-1 block text-sm font-medium">{{ t("people.report.details") }}</label>
            <textarea :id="`${uid}-details`" v-model="details" class="input min-h-20" rows="3" dir="auto" :maxlength="MAX - 20" />
          </div>
          <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("people.report.myReports") }}</p>
        </div>
        <div class="flex justify-end gap-2 border-t border-gray-100 px-4 py-3 dark:border-gray-800">
          <button type="button" class="btn-ghost" :disabled="sending" @click="emit('close')">{{ t("people.actions.cancel") }}</button>
          <button type="submit" class="btn-primary" :disabled="!reason || sending" data-testid="report-submit">
            {{ sending ? t("people.report.sending") : t("people.report.submit") }}
          </button>
        </div>
      </form>
    </div>
  </Teleport>
</template>
