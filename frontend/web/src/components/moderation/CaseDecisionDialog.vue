<script setup lang="ts">
import { computed, ref, useId } from "vue";
import { useI18n } from "vue-i18n";

import SafetyDialog from "@/components/moderation/SafetyDialog.vue";
import { ACTION_REASON_MAX, adminService, caseActions, ENFORCING_ACTIONS, type ModerationCase } from "@/services/admin";
import { useToastStore } from "@/stores/toasts";

/**
 * A moderator's decision on a case: one of the actions the server allows for
 * the target type, with an optional reason. The reason is kept with the
 * decision and shown to the owner in their Support inbox, so it is written
 * for them. `initial` preselects an action (the card's quick buttons).
 */
const props = withDefaults(defineProps<{ caseItem: ModerationCase; initial?: string }>(), { initial: "" });
const emit = defineEmits<{ close: []; done: [action: string] }>();

const { t } = useI18n();
const toasts = useToastStore();
const uid = useId();

const actions = computed(() => caseActions(props.caseItem.target_type));
const action = ref(actions.value.includes(props.initial) ? props.initial : "");
const reason = ref("");
const busy = ref(false);
const enforcing = computed(() => ENFORCING_ACTIONS.includes(action.value));

async function submit() {
  if (!action.value || busy.value) return;
  busy.value = true;
  try {
    await adminService.actionCase(props.caseItem.id, action.value, reason.value.trim());
    toasts.success(t("safety.mod.decision.done"));
    emit("done", action.value);
  } catch (e) {
    toasts.error(e, { conflict: "safety.mod.decision.conflict", not_found: "safety.mod.decision.gone" });
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <SafetyDialog :title="t('safety.mod.decision.title')" testid="case-decision-dialog" @close="!busy && emit('close')">
    <form :id="`${uid}-form`" class="space-y-4" @submit.prevent="submit">
      <fieldset>
        <legend class="mb-2 text-sm font-semibold">{{ t("safety.mod.decision.choose") }}</legend>
        <div class="space-y-1.5">
          <label
            v-for="a in actions"
            :key="a"
            class="flex cursor-pointer items-start gap-3 rounded-xl border border-gray-100 p-3 hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-800/60"
            :class="action === a ? 'border-brand-400 bg-brand-50/60 dark:border-brand-700 dark:bg-brand-950/30' : ''"
          >
            <input v-model="action" type="radio" class="mt-1 accent-brand-600" :name="`${uid}-action`" :value="a" :data-testid="`decision-${a}`" />
            <span class="min-w-0">
              <span class="block font-medium">{{ t(`safety.mod.actions.${a}`) }}</span>
              <span class="block text-sm text-gray-500 dark:text-gray-400">{{ t(`safety.mod.actionHints.${a}`) }}</span>
            </span>
          </label>
        </div>
      </fieldset>
      <div>
        <label :for="`${uid}-reason`" class="label">{{ t("safety.mod.decision.reason") }}</label>
        <textarea
          :id="`${uid}-reason`"
          v-model="reason"
          class="input min-h-24"
          dir="auto"
          :maxlength="ACTION_REASON_MAX"
          :aria-describedby="`${uid}-reason-hint`"
          data-testid="decision-reason"
        />
        <p :id="`${uid}-reason-hint`" class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ t("safety.mod.decision.reasonHint") }}</p>
      </div>
    </form>
    <template #footer>
      <button type="button" class="btn-ghost" :disabled="busy" @click="emit('close')">{{ t("safety.cancel") }}</button>
      <button
        type="submit"
        :form="`${uid}-form`"
        :class="enforcing ? 'btn-danger' : 'btn-primary'"
        :disabled="!action || busy"
        data-testid="decision-confirm"
      >
        {{ busy ? t("states.loading") : action ? t(`safety.mod.actions.${action}`) : t("safety.mod.decision.confirm") }}
      </button>
    </template>
  </SafetyDialog>
</template>
