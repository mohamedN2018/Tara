<script setup lang="ts">
import { Mic } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { relativeTime } from "@/lib/format";
import type { Message } from "@/types";

const props = defineProps<{ message: Message; mine: boolean }>();
const { t } = useI18n();

const voiceNote = computed(() =>
  props.message.attachments.find((a) => a.kind === "voice" || props.message.type === "voice"),
);
</script>

<template>
  <div class="flex" :class="mine ? 'justify-end' : 'justify-start'">
    <div
      class="max-w-[75%] rounded-2xl px-3 py-2 text-sm"
      :class="
        mine
          ? 'rounded-ee-sm bg-brand-600 text-white'
          : 'rounded-es-sm bg-gray-100 text-gray-900 dark:bg-gray-800 dark:text-gray-100'
      "
    >
      <div v-if="voiceNote" class="flex items-center gap-2">
        <Mic class="h-4 w-4" />
        <span>{{ t("messages.voiceNote") }}</span>
      </div>
      <p v-else class="whitespace-pre-wrap break-words">{{ message.body }}</p>
      <time class="mt-0.5 block text-[10px] opacity-70">{{ relativeTime(message.created_at) }}</time>
    </div>
  </div>
</template>
