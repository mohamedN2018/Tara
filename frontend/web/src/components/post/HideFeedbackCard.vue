<script setup lang="ts">
import { CheckCircle2, Clock, EyeOff, Undo2 } from "lucide-vue-next";
import { onMounted, ref, useId } from "vue";
import { useI18n } from "vue-i18n";

import { HIDE_REASONS, type HideReason } from "@/services/feed";

// Takes a hidden post's place in the feed (plan 08, 2B): undo, why, and snooze.
const props = withDefaults(
  defineProps<{
    postId: string;
    authorName: string;
    reason?: HideReason | null;
    snoozed?: boolean;
    /** The author can be snoozed (not the viewer, not a page post). */
    canSnooze?: boolean;
    busy?: boolean;
  }>(),
  { reason: null, snoozed: false, canSnooze: true, busy: false },
);
const emit = defineEmits<{ undo: []; reason: [reason: HideReason]; snooze: []; unsnooze: [] }>();

const { t } = useI18n();
const titleId = useId();
const root = ref<HTMLElement | null>(null);

// Keyboard users land on the card that replaced the post they were on.
onMounted(() => root.value?.focus({ preventScroll: true }));

const REASON_KEY: Record<HideReason, string> = {
  not_interested: "homeFeed.hide.reasons.notInterested",
  spam: "homeFeed.hide.reasons.spam",
  sexual: "homeFeed.hide.reasons.sexual",
  annoying: "homeFeed.hide.reasons.annoying",
  dislike_creator: "homeFeed.hide.reasons.dislikeCreator",
  other: "homeFeed.hide.reasons.other",
};

function choose(r: HideReason) {
  if (props.busy || r === props.reason) return;
  emit("reason", r);
}
</script>

<template>
  <section
    ref="root"
    class="card space-y-4 p-4 outline-none sm:p-5"
    tabindex="-1"
    :aria-labelledby="titleId"
    data-testid="hide-feedback"
    :data-post-id="postId"
  >
    <div class="flex items-start gap-3">
      <EyeOff class="mt-0.5 h-5 w-5 shrink-0 text-gray-500 dark:text-gray-400" aria-hidden="true" />
      <div class="min-w-0 flex-1">
        <h3 :id="titleId" class="text-[15px] font-bold">{{ t("homeFeed.hide.title") }}</h3>
        <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("homeFeed.hide.hint") }}</p>
      </div>
      <button type="button" class="btn-ghost shrink-0" :disabled="busy" @click="emit('undo')">
        <Undo2 class="h-4 w-4 rtl:-scale-x-100" aria-hidden="true" data-testid="undo-icon" />
        {{ t("homeFeed.undo") }}
      </button>
    </div>

    <div>
      <p class="mb-2 text-sm font-semibold">{{ t("homeFeed.hide.why") }}</p>
      <div class="flex flex-wrap gap-2" role="group" :aria-label="t('homeFeed.hide.why')">
        <button
          v-for="r in HIDE_REASONS"
          :key="r"
          type="button"
          class="rounded-full px-3.5 py-1.5 text-sm font-medium transition disabled:opacity-60"
          :class="
            reason === r
              ? 'bg-brand-600 text-white'
              : 'bg-gray-100 text-gray-800 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700'
          "
          :aria-pressed="reason === r"
          :disabled="busy"
          @click="choose(r)"
        >
          {{ t(REASON_KEY[r]) }}
        </button>
      </div>
      <p v-if="reason" class="mt-2 flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-300" role="status">
        <CheckCircle2 class="h-4 w-4 text-green-600" aria-hidden="true" /> {{ t("homeFeed.hide.thanks") }}
      </p>
    </div>

    <div v-if="canSnooze" class="border-t border-gray-100 pt-3 dark:border-gray-800">
      <p class="mb-1 text-sm font-semibold">{{ t("homeFeed.hide.otherSteps") }}</p>
      <div v-if="snoozed" class="flex items-center gap-3 py-1.5 text-sm" role="status">
        <Clock class="h-5 w-5 shrink-0" aria-hidden="true" />
        <span class="min-w-0 flex-1" dir="auto">{{ t("homeFeed.hide.snoozed", { name: authorName }) }}</span>
        <button type="button" class="btn-ghost shrink-0" :disabled="busy" @click="emit('unsnooze')">
          <Undo2 class="h-4 w-4 rtl:-scale-x-100" aria-hidden="true" /> {{ t("homeFeed.undo") }}
        </button>
      </div>
      <button
        v-else
        type="button"
        class="-mx-2 flex w-[calc(100%+1rem)] items-center gap-3 rounded-lg px-2 py-2 text-start text-sm font-medium transition hover:bg-gray-100 disabled:opacity-60 dark:hover:bg-gray-800"
        :disabled="busy"
        @click="emit('snooze')"
      >
        <Clock class="h-5 w-5 shrink-0" aria-hidden="true" />
        <span dir="auto">{{ t("homeFeed.hide.snooze", { name: authorName }) }}</span>
      </button>
    </div>
  </section>
</template>
