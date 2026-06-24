<script setup lang="ts">
import { Mic, Reply } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { relativeTime } from "@/lib/format";
import { useMediaUrls } from "@/lib/useMediaUrl";
import type { Message } from "@/types";

const props = defineProps<{
  message: Message;
  mine: boolean;
  replyTo?: Message | null;
  replyToName?: string;
}>();
defineEmits<{ reply: [message: Message] }>();
const { t } = useI18n();

const voiceNote = computed(() =>
  props.message.attachments.find((a) => a.kind === "voice" || props.message.type === "voice"),
);
const imageIds = computed(() =>
  props.message.attachments.filter((a) => a.kind === "image").map((a) => a.media_id),
);
const images = useMediaUrls(() => imageIds.value);

function preview(m: Message): string {
  if (m.body) return m.body;
  if (m.attachments.some((a) => a.kind === "image")) return `📷 ${t("messages.photo")}`;
  if (m.attachments.some((a) => a.kind === "voice")) return `🎤 ${t("messages.voiceNote")}`;
  return "…";
}
</script>

<template>
  <div class="group flex items-center gap-1" :class="mine ? 'justify-end' : 'justify-start'">
    <button
      v-if="mine"
      class="order-1 rounded-full p-1 text-gray-400 opacity-0 transition hover:bg-gray-100 group-hover:opacity-100 dark:hover:bg-gray-800"
      :aria-label="t('messages.reply')"
      :title="t('messages.reply')"
      @click="$emit('reply', message)"
    >
      <Reply class="h-4 w-4" />
    </button>

    <div
      class="max-w-[75%] overflow-hidden rounded-2xl text-sm"
      :class="
        mine
          ? 'order-2 rounded-ee-sm bg-brand-600 text-white'
          : 'rounded-es-sm bg-gray-100 text-gray-900 dark:bg-gray-800 dark:text-gray-100'
      "
    >
      <!-- Reply quote -->
      <div
        v-if="replyTo"
        class="mx-1 mt-1 rounded-lg border-s-2 px-2 py-1 text-xs"
        :class="mine ? 'border-white/60 bg-white/15' : 'border-brand-500 bg-black/5 dark:bg-white/10'"
      >
        <span class="block font-semibold">{{ replyToName }}</span>
        <span class="block truncate opacity-80">{{ preview(replyTo) }}</span>
      </div>

      <div v-if="images.length" class="grid gap-0.5" :class="images.length > 1 ? 'grid-cols-2' : 'grid-cols-1'">
        <img v-for="(src, i) in images" :key="i" :src="src" class="max-h-64 w-full object-cover" loading="lazy" decoding="async" alt="" />
      </div>

      <div class="px-3 py-2">
        <div v-if="voiceNote" class="flex items-center gap-2">
          <Mic class="h-4 w-4" />
          <span>{{ t("messages.voiceNote") }}</span>
        </div>
        <p v-else-if="message.body" class="whitespace-pre-wrap break-words">{{ message.body }}</p>
        <time class="mt-0.5 block text-[10px] opacity-70">
          {{ relativeTime(message.created_at) }}
          <span v-if="message.edited_at"> · {{ t("messages.edited") }}</span>
        </time>
      </div>
    </div>

    <button
      v-if="!mine"
      class="rounded-full p-1 text-gray-400 opacity-0 transition hover:bg-gray-100 group-hover:opacity-100 dark:hover:bg-gray-800"
      :aria-label="t('messages.reply')"
      :title="t('messages.reply')"
      @click="$emit('reply', message)"
    >
      <Reply class="h-4 w-4" />
    </button>
  </div>
</template>
