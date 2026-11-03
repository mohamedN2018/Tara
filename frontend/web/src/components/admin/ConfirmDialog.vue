<script setup lang="ts">
import { X } from "lucide-vue-next";
import { computed, ref, toRef, watch } from "vue";
import { useI18n } from "vue-i18n";

import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { REASON_MAX, REASON_MIN, minUntilDay, reasonValid, untilFromDay } from "@/services/adminUsers";

/**
 * Confirmation for a staff action. With `needsReason` the confirm button stays
 * disabled until a reason is typed (it goes to the audit log or to identity);
 * with `withUntil` an optional end date is offered.
 */
const props = withDefaults(
  defineProps<{
    open: boolean;
    title: string;
    hint?: string;
    confirmLabel: string;
    needsReason?: boolean;
    withUntil?: boolean;
    danger?: boolean;
    busy?: boolean;
    testid?: string;
  }>(),
  { hint: "", needsReason: false, withUntil: false, danger: true, busy: false, testid: "confirm-dialog" },
);
const emit = defineEmits<{ confirm: [value: { reason: string; until: string | null }]; cancel: [] }>();

const { t } = useI18n();
const reason = ref("");
const day = ref("");
const dialog = ref<HTMLElement | null>(null);
const uid = `confirm-${Math.random().toString(36).slice(2, 9)}`;

useFocusTrap(dialog);
useEscapeKey(toRef(props, "open"), () => cancel());

watch(
  () => props.open,
  (open) => {
    if (open) {
      reason.value = "";
      day.value = "";
    }
  },
);

const canConfirm = computed(() => !props.busy && (!props.needsReason || reasonValid(reason.value)));
const tooShort = computed(() => props.needsReason && reason.value.length > 0 && !reasonValid(reason.value));

function cancel() {
  if (!props.busy) emit("cancel");
}

function confirm() {
  if (!canConfirm.value) return;
  emit("confirm", { reason: reason.value.trim(), until: props.withUntil ? untilFromDay(day.value) : null });
}
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-50 flex items-end justify-center bg-gray-950/60 p-0 backdrop-blur-sm sm:items-center sm:p-4">
    <div class="fixed inset-0" aria-hidden="true" @click="cancel" />
    <form
      ref="dialog"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="`${uid}-title`"
      :aria-describedby="hint ? `${uid}-hint` : undefined"
      tabindex="-1"
      class="card relative z-10 max-h-[92vh] w-full animate-pop-in overflow-y-auto rounded-b-none rounded-t-2xl p-4 shadow-pop sm:max-w-md sm:rounded-2xl sm:p-5"
      :data-testid="testid"
      @submit.prevent="confirm"
    >
      <div class="mb-2 flex items-start justify-between gap-3">
        <h2 :id="`${uid}-title`" class="text-lg font-bold" dir="auto">{{ title }}</h2>
        <button type="button" class="rounded-full p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" :aria-label="t('admin.users.cancel')" @click="cancel">
          <X class="h-5 w-5" aria-hidden="true" />
        </button>
      </div>
      <p v-if="hint" :id="`${uid}-hint`" class="mb-3 text-sm text-gray-600 dark:text-gray-300">{{ hint }}</p>
      <slot />

      <div v-if="needsReason" class="mb-3 flex flex-col gap-1 text-sm">
        <label :for="`${uid}-reason`">{{ t("admin.users.reasonLabel") }}</label>
        <textarea
          :id="`${uid}-reason`"
          v-model="reason"
          class="input min-h-20"
          dir="auto"
          :minlength="REASON_MIN"
          :maxlength="REASON_MAX"
          required
          :aria-invalid="tooShort ? 'true' : 'false'"
          :aria-describedby="`${uid}-reason-hint`"
        />
        <span :id="`${uid}-reason-hint`" class="text-xs" :class="tooShort ? 'text-red-600 dark:text-red-400' : 'text-gray-500 dark:text-gray-400'">
          {{ tooShort ? t("admin.users.reasonTooShort", { min: REASON_MIN }) : t("admin.users.reasonHint") }}
        </span>
      </div>

      <div v-if="withUntil" class="mb-3 flex flex-col gap-1 text-sm">
        <label :for="`${uid}-until`">{{ t("admin.users.suspend.until") }}</label>
        <input :id="`${uid}-until`" v-model="day" type="date" class="input" :min="minUntilDay()" :aria-describedby="`${uid}-until-hint`" />
        <span :id="`${uid}-until-hint`" class="text-xs text-gray-500 dark:text-gray-400">{{ t("admin.users.suspend.untilHint") }}</span>
      </div>

      <div class="mt-4 flex justify-end gap-2">
        <button type="button" class="btn-ghost" :disabled="busy" @click="cancel">{{ t("admin.users.cancel") }}</button>
        <button
          type="submit"
          :class="danger ? 'btn-danger' : 'btn-primary'"
          :disabled="!canConfirm"
        >
          {{ busy ? t("states.loading") : confirmLabel }}
        </button>
      </div>
    </form>
  </div>
</template>
