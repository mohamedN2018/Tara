<script setup lang="ts">
import { Pin, PinOff, Reply, SmilePlus } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import VoicePlayer from "@/components/chat/VoicePlayer.vue";
import { reactionSummary } from "@/lib/chat";
import { relativeTime } from "@/lib/format";
import { MESSAGE_REACTIONS, reactionByKey } from "@/lib/reactions";
import { useMediaUrls } from "@/lib/useMediaUrl";
import type { Message } from "@/types";

const props = defineProps<{
  message: Message;
  mine: boolean;
  replyTo?: Message | null;
  replyToName?: string;
  senderName?: string;
  showSender?: boolean;
  selfId?: string;
  canPin?: boolean;
  pinned?: boolean;
}>();
const emit = defineEmits<{
  reply: [message: Message];
  react: [message: Message, type: string | null];
  pin: [message: Message, pinned: boolean];
}>();
const { t } = useI18n();

const pickerOpen = ref(false);
const mineReaction = computed(
  () => props.message.reactions.find((r) => r.account_id === props.selfId)?.type ?? null,
);
const summary = computed(() =>
  reactionSummary(props.message.reactions).map((s) => ({ ...s, emoji: reactionByKey(s.type)?.emoji })),
);
function choose(type: string) {
  pickerOpen.value = false;
  emit("react", props.message, type === mineReaction.value ? null : type);
}

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
    <template v-if="mine">
    <div class="relative flex items-center opacity-0 transition focus-within:opacity-100 group-hover:opacity-100" :class="{ 'opacity-100': pickerOpen }">
      <button
        class="rounded-full p-1 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 dark:text-gray-400"
        :aria-label="t('messages.reply')"
        :title="t('messages.reply')"
        @click="$emit('reply', message)"
      >
        <Reply class="h-4 w-4" />
      </button>
      <button
        class="rounded-full p-1 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 dark:text-gray-400"
        :aria-label="t('messages.react')"
        :title="t('messages.react')"
        :aria-expanded="pickerOpen"
        @click="pickerOpen = !pickerOpen"
      >
        <SmilePlus class="h-4 w-4" />
      </button>
      <button
        v-if="canPin"
        class="rounded-full p-1 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 dark:text-gray-400"
        :aria-label="pinned ? t('messages.unpin') : t('messages.pin')"
        :title="pinned ? t('messages.unpin') : t('messages.pin')"
        @click="$emit('pin', message, !pinned)"
      >
        <PinOff v-if="pinned" class="h-4 w-4" />
        <Pin v-else class="h-4 w-4" />
      </button>
      <template v-if="pickerOpen">
        <div class="fixed inset-0 z-40" @click="pickerOpen = false" />
        <div class="absolute bottom-full z-50 mb-1 flex gap-1 rounded-full border border-gray-100 bg-white px-2 py-1 shadow-lg dark:border-gray-700 dark:bg-gray-800" :class="mine ? 'end-0' : 'start-0'">
          <button
            v-for="r in MESSAGE_REACTIONS"
            :key="r.key"
            type="button"
            class="text-xl leading-none transition hover:scale-125"
            :class="mineReaction === r.key ? 'rounded-full bg-brand-100 dark:bg-brand-950' : ''"
            :aria-label="t(r.labelKey)"
            :title="t(r.labelKey)"
            @click="choose(r.key)"
          >
            {{ r.emoji }}
          </button>
        </div>
      </template>
    </div>
    </template>

    <div class="flex max-w-[75%] flex-col" :class="mine ? 'items-end' : 'items-start'">
      <span v-if="showSender && !mine" class="mb-0.5 px-1 text-[11px] font-medium text-gray-500 dark:text-gray-400" dir="auto">{{ senderName }}</span>
    <div
      class="max-w-full overflow-hidden rounded-2xl text-sm"
      :class="
        mine
          ? 'rounded-ee-sm bg-brand-600 text-white'
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
        <span class="block truncate opacity-80" dir="auto">{{ preview(replyTo) }}</span>
      </div>

      <div v-if="images.length" class="grid gap-0.5" :class="images.length > 1 ? 'grid-cols-2' : 'grid-cols-1'">
        <img v-for="(src, i) in images" :key="i" :src="src" class="max-h-64 w-full object-cover" loading="lazy" decoding="async" :alt="t('messages.photoFrom', { name: senderName ?? '' })" />
      </div>

      <div class="px-3 py-2">
        <VoicePlayer v-if="voiceNote" :media-id="voiceNote.media_id" :duration-ms="voiceNote.duration_ms" />
        <p v-else-if="message.body" class="whitespace-pre-wrap break-words" dir="auto">{{ message.body }}</p>
        <time class="mt-0.5 block text-[10px] opacity-70">
          {{ relativeTime(message.created_at) }}
          <span v-if="message.edited_at"> · {{ t("messages.edited") }}</span>
        </time>
      </div>
    </div>

    <div v-if="summary.length" class="-mt-1 flex gap-1 px-1" data-testid="message-reactions">
      <button
        v-for="s in summary"
        :key="s.type"
        class="inline-flex items-center gap-0.5 rounded-full border border-gray-200 bg-white px-1.5 text-xs text-gray-700 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
        :class="mineReaction === s.type ? 'border-brand-400' : ''"
        :aria-label="t(`reactionTypes.${s.type}`)"
        @click="choose(s.type)"
      >
        <span aria-hidden="true">{{ s.emoji }}</span>{{ s.count }}
      </button>
    </div>
    </div>

    <template v-if="!mine">
    <div class="relative flex items-center opacity-0 transition focus-within:opacity-100 group-hover:opacity-100" :class="{ 'opacity-100': pickerOpen }">
      <button
        class="rounded-full p-1 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 dark:text-gray-400"
        :aria-label="t('messages.reply')"
        :title="t('messages.reply')"
        @click="$emit('reply', message)"
      >
        <Reply class="h-4 w-4" />
      </button>
      <button
        class="rounded-full p-1 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 dark:text-gray-400"
        :aria-label="t('messages.react')"
        :title="t('messages.react')"
        :aria-expanded="pickerOpen"
        @click="pickerOpen = !pickerOpen"
      >
        <SmilePlus class="h-4 w-4" />
      </button>
      <button
        v-if="canPin"
        class="rounded-full p-1 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 dark:text-gray-400"
        :aria-label="pinned ? t('messages.unpin') : t('messages.pin')"
        :title="pinned ? t('messages.unpin') : t('messages.pin')"
        @click="$emit('pin', message, !pinned)"
      >
        <PinOff v-if="pinned" class="h-4 w-4" />
        <Pin v-else class="h-4 w-4" />
      </button>
      <template v-if="pickerOpen">
        <div class="fixed inset-0 z-40" @click="pickerOpen = false" />
        <div class="absolute bottom-full z-50 mb-1 flex gap-1 rounded-full border border-gray-100 bg-white px-2 py-1 shadow-lg dark:border-gray-700 dark:bg-gray-800" :class="mine ? 'end-0' : 'start-0'">
          <button
            v-for="r in MESSAGE_REACTIONS"
            :key="r.key"
            type="button"
            class="text-xl leading-none transition hover:scale-125"
            :class="mineReaction === r.key ? 'rounded-full bg-brand-100 dark:bg-brand-950' : ''"
            :aria-label="t(r.labelKey)"
            :title="t(r.labelKey)"
            @click="choose(r.key)"
          >
            {{ r.emoji }}
          </button>
        </div>
      </template>
    </div>
    </template>
  </div>
</template>
