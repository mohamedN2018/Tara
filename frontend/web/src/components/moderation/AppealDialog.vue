<script setup lang="ts">
import { computed, ref, useId } from "vue";
import { useI18n } from "vue-i18n";

import SafetyDialog from "@/components/moderation/SafetyDialog.vue";
import { useSafetyLabels } from "@/lib/safetyLabels";
import { APPEAL_ERRORS, APPEAL_TEXT_MAX, moderationService, type MyCase } from "@/services/moderation";
import { useToastStore } from "@/stores/toasts";

/** "Request review": the member explains why a decision about them is wrong (once per case). */
const props = defineProps<{ caseItem: MyCase }>();
const emit = defineEmits<{ close: []; sent: [] }>();

const { t } = useI18n();
const toasts = useToastStore();
const uid = useId();
const { decisionLabel, targetLabel } = useSafetyLabels();

const text = ref("");
const busy = ref(false);
const remaining = computed(() => APPEAL_TEXT_MAX - text.value.length);

async function submit() {
  const body = text.value.trim();
  if (!body || busy.value) return;
  busy.value = true;
  try {
    await moderationService.appeal(props.caseItem.id, body);
    toasts.success(t("safety.status.appealSent"));
    emit("sent");
  } catch (e) {
    toasts.error(e, APPEAL_ERRORS);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <SafetyDialog :title="t('safety.status.appealTitle')" testid="appeal-dialog" @close="!busy && emit('close')">
    <form :id="`${uid}-form`" class="space-y-3" @submit.prevent="submit">
      <p class="text-sm text-gray-600 dark:text-gray-300">
        {{ t("safety.status.appealIntro", { decision: decisionLabel(caseItem.decision), target: targetLabel(caseItem.target_type) }) }}
      </p>
      <div>
        <label :for="`${uid}-text`" class="label">{{ t("safety.status.appealLabel") }}</label>
        <textarea
          :id="`${uid}-text`"
          v-model="text"
          class="input min-h-32"
          dir="auto"
          required
          :maxlength="APPEAL_TEXT_MAX"
          :aria-describedby="`${uid}-hint`"
          data-testid="appeal-text"
        />
        <p :id="`${uid}-hint`" class="mt-1 flex justify-between gap-2 text-xs text-gray-500 dark:text-gray-400">
          <span>{{ t("safety.status.appealHint") }}</span>
          <span dir="ltr" class="tabular-nums">{{ remaining }}</span>
        </p>
      </div>
      <p class="text-xs text-gray-500 dark:text-gray-400">
        <RouterLink to="/legal/community-standards" class="font-semibold text-brand-700 hover:underline dark:text-brand-300">{{ t("safety.standards.learn") }}</RouterLink>
      </p>
    </form>
    <template #footer>
      <button type="button" class="btn-ghost" :disabled="busy" @click="emit('close')">{{ t("safety.cancel") }}</button>
      <button type="submit" :form="`${uid}-form`" class="btn-primary" :disabled="!text.trim() || busy" data-testid="appeal-send">
        {{ busy ? t("states.loading") : t("safety.status.appealSend") }}
      </button>
    </template>
  </SafetyDialog>
</template>
