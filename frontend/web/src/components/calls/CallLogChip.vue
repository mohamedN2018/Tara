<script setup lang="ts">
// A call-log system message ("Missed voice call", "Video call · 3:12") as a
// centred chip, with a call-back button while calls are on. Any other system
// message shows as plain muted text, never as HTML.
import { Phone, PhoneMissed, Video } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { callLogKey, formatDuration, parseCallLog } from "@/lib/callLog";
import { relativeTime } from "@/lib/format";
import { useCallStore } from "@/stores/calls";
import type { Message } from "@/types";

const props = defineProps<{ message: Message; selfId: string; conversationId: string; callable?: boolean }>();
const { t } = useI18n();
const calls = useCallStore();

const log = computed(() => parseCallLog(props.message.body));
const text = computed(() => {
  if (!log.value) return props.message.body;
  const viewerIsCaller = props.message.sender_id === props.selfId;
  return t(callLogKey(log.value, viewerIsCaller), { duration: formatDuration(log.value.seconds) });
});
const missed = computed(() => log.value && log.value.outcome !== "ended");
</script>

<template>
  <div class="my-2 flex justify-center" data-testid="call-log">
    <div
      class="flex items-center gap-2 rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-600 dark:bg-gray-800 dark:text-gray-300"
      :class="missed && message.sender_id !== selfId ? 'text-red-600 dark:text-red-400' : ''"
    >
      <template v-if="log">
        <PhoneMissed v-if="missed" class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <Video v-else-if="log.kind === 'video'" class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <Phone v-else class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      </template>
      <span dir="auto">{{ text }}</span>
      <time class="text-[10px] text-gray-400" :datetime="message.created_at">{{ relativeTime(message.created_at) }}</time>
      <button
        v-if="log && callable && calls.enabled && !calls.busy"
        type="button"
        class="ms-1 rounded-full px-2 py-0.5 font-medium text-brand-600 hover:bg-brand-50 dark:text-brand-300 dark:hover:bg-brand-950"
        :aria-label="log.kind === 'video' ? t('calls.callBackVideo') : t('calls.callBackVoice')"
        @click="calls.start(conversationId, log.kind)"
      >
        {{ t("calls.callBack") }}
      </button>
    </div>
  </div>
</template>
