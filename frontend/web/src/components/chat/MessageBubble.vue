<script setup lang="ts">
import { Check, CheckCheck, CornerUpRight, MoreHorizontal, Pin, PinOff, Reply, SmilePlus } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ChatAttachment from "@/components/chat/ChatAttachment.vue";
import VoicePlayer from "@/components/chat/VoicePlayer.vue";
import { type DeliveryStatus, reactionSummary, typePreview } from "@/lib/chat";
import { relativeTime } from "@/lib/format";
import { MESSAGE_REACTIONS, reactionByKey } from "@/lib/reactions";
import { useEscapeKey } from "@/lib/useEscapeKey";
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
  status?: DeliveryStatus | null;
  canEdit?: boolean;
  canDeleteForEveryone?: boolean;
}>();
const emit = defineEmits<{
  reply: [message: Message];
  react: [message: Message, type: string | null];
  pin: [message: Message, pinned: boolean];
  edit: [message: Message];
  forward: [message: Message];
  delete: [message: Message, scope: "me" | "everyone"];
}>();
const { t } = useI18n();

const ROW = "block w-full rounded-lg px-3 py-2 text-start text-sm hover:bg-gray-100 dark:hover:bg-gray-800";
const pickerOpen = ref(false);
const menuOpen = ref(false);
useEscapeKey(pickerOpen, () => (pickerOpen.value = false));
useEscapeKey(menuOpen, () => (menuOpen.value = false));
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
function act(fn: () => void) {
  menuOpen.value = false;
  fn();
}

const voiceNote = computed(() =>
  props.message.attachments.find((a) => a.kind === "voice" || a.kind === "audio"),
);
const visual = computed(() =>
  props.message.attachments.filter((a) => a.kind === "image" || a.kind === "video"),
);
const files = computed(() => props.message.attachments.filter((a) => a.kind === "file"));

// The quoted message: the loaded one if we have it, else the server's preview.
const quote = computed(() => {
  if (props.replyTo) {
    return { body: preview(props.replyTo), deleted: !!props.replyTo.deleted, unavailable: false };
  }
  const p = props.message.reply_preview;
  if (!p) return null;
  // The server cannot say whether a quote it withholds was deleted or predates
  // this member joining the group: either way it is just unavailable.
  return { body: p.deleted ? "" : p.body || typePreview(p.type, t), deleted: false, unavailable: !!p.deleted };
});

function preview(m: Message): string {
  if (m.deleted) return "";
  if (m.body) return m.body;
  return typePreview(m.attachments[0]?.kind ?? m.type, t);
}

const statusLabel = computed(() =>
  props.status ? t(`messages.status${props.status[0].toUpperCase()}${props.status.slice(1)}`) : "",
);
</script>

<template>
  <div class="group flex items-center gap-1" :class="mine ? 'flex-row-reverse' : 'justify-start'">
    <div class="flex max-w-[75%] flex-col" :class="mine ? 'items-end' : 'items-start'">
      <span v-if="showSender && !mine" class="mb-0.5 px-1 text-[11px] font-medium text-gray-500 dark:text-gray-400" dir="auto">{{ senderName }}</span>
      <div
        class="max-w-full overflow-hidden rounded-2xl text-sm"
        :class="
          message.deleted
            ? 'border border-dashed border-gray-300 bg-transparent text-gray-500 dark:border-gray-700 dark:text-gray-400'
            : mine
              ? 'rounded-ee-sm bg-brand-600 text-white'
              : 'rounded-es-sm bg-gray-100 text-gray-900 dark:bg-gray-800 dark:text-gray-100'
        "
      >
        <template v-if="message.deleted">
          <p class="px-3 py-2 italic" data-testid="message-deleted">{{ t("messages.deleted") }}</p>
        </template>
        <template v-else>
          <p v-if="message.forwarded" class="flex items-center gap-1 px-3 pt-1.5 text-[11px] italic opacity-75">
            <CornerUpRight class="h-3 w-3 rtl:-scale-x-100" /> {{ t("messages.forwarded") }}
          </p>
          <!-- Reply quote -->
          <div
            v-if="quote"
            class="mx-1 mt-1 rounded-lg border-s-2 px-2 py-1 text-xs"
            :class="mine ? 'border-white/60 bg-white/15' : 'border-brand-500 bg-black/5 dark:bg-white/10'"
          >
            <span v-if="replyToName" class="block font-semibold">{{ replyToName }}</span>
            <span v-if="quote.unavailable" class="block italic opacity-80" data-testid="quote-unavailable">{{ t("messages.quoteUnavailable") }}</span>
            <span v-else-if="quote.deleted" class="block italic opacity-80">{{ t("messages.deleted") }}</span>
            <span v-else class="block truncate opacity-80" dir="auto">{{ quote.body }}</span>
          </div>

          <div v-if="visual.length" class="grid gap-0.5" :class="visual.length > 1 ? 'grid-cols-2' : 'grid-cols-1'">
            <ChatAttachment
              v-for="a in visual"
              :key="a.media_id"
              :message-id="message.id"
              :attachment="a"
              :alt="t('messages.photoFrom', { name: senderName ?? '' })"
            />
          </div>
          <div v-if="files.length" class="space-y-1 px-1 pt-1">
            <ChatAttachment v-for="a in files" :key="a.media_id" :message-id="message.id" :attachment="a" />
          </div>

          <div class="px-3 py-2">
            <VoicePlayer v-if="voiceNote" :media-id="voiceNote.media_id" :message-id="message.id" :duration-ms="voiceNote.duration_ms" />
            <p v-if="message.body" class="whitespace-pre-wrap break-words" dir="auto">{{ message.body }}</p>
            <time class="mt-0.5 flex items-center gap-1 text-[10px] opacity-70">
              {{ relativeTime(message.created_at) }}
              <span v-if="message.edited_at"> · {{ t("messages.edited") }}</span>
              <span v-if="status" class="inline-flex" :title="statusLabel" data-testid="message-status" :data-status="status">
                <span class="sr-only">{{ statusLabel }}</span>
                <CheckCheck v-if="status === 'read'" class="h-3.5 w-3.5 text-sky-300" aria-hidden="true" />
                <CheckCheck v-else-if="status === 'delivered'" class="h-3.5 w-3.5" aria-hidden="true" />
                <Check v-else class="h-3.5 w-3.5" aria-hidden="true" />
              </span>
            </time>
          </div>
        </template>
      </div>

      <div v-if="summary.length && !message.deleted" class="-mt-1 flex gap-1 px-1" data-testid="message-reactions">
        <button
          v-for="s in summary"
          :key="s.type"
          class="inline-flex items-center gap-0.5 rounded-full border border-gray-200 bg-white px-1.5 text-xs text-gray-700 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
          :class="mineReaction === s.type ? 'border-brand-400' : ''"
          :aria-label="`${t(`reactionTypes.${s.type}`)}: ${s.count}`"
          :aria-pressed="mineReaction === s.type"
          @click="choose(s.type)"
        >
          <span aria-hidden="true">{{ s.emoji }}</span>{{ s.count }}
        </button>
      </div>
    </div>

    <!-- Actions -->
    <div
      class="relative flex items-center opacity-0 transition focus-within:opacity-100 group-hover:opacity-100"
      :class="{ 'opacity-100': pickerOpen || menuOpen }"
    >
      <template v-if="!message.deleted">
        <button
          class="rounded-full p-1 text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
          :aria-label="t('messages.reply')"
          :title="t('messages.reply')"
          @click="$emit('reply', message)"
        >
          <Reply class="h-4 w-4 rtl:-scale-x-100" />
        </button>
        <button
          class="rounded-full p-1 text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
          :aria-label="t('messages.react')"
          :title="t('messages.react')"
          :aria-expanded="pickerOpen"
          @click="pickerOpen = !pickerOpen"
        >
          <SmilePlus class="h-4 w-4" />
        </button>
        <button
          v-if="canPin"
          class="rounded-full p-1 text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
          :aria-label="pinned ? t('messages.unpin') : t('messages.pin')"
          :title="pinned ? t('messages.unpin') : t('messages.pin')"
          @click="$emit('pin', message, !pinned)"
        >
          <PinOff v-if="pinned" class="h-4 w-4" />
          <Pin v-else class="h-4 w-4" />
        </button>
      </template>
      <button
        class="rounded-full p-1 text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
        :aria-label="t('messages.messageActions')"
        :title="t('messages.messageActions')"
        aria-haspopup="menu"
        :aria-expanded="menuOpen"
        data-testid="message-menu"
        @click="menuOpen = !menuOpen"
      >
        <MoreHorizontal class="h-4 w-4" />
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

      <template v-if="menuOpen">
        <div class="fixed inset-0 z-40" @click="menuOpen = false" />
        <div class="popover absolute bottom-full z-50 mb-1 w-48 p-1" :class="mine ? 'end-0' : 'start-0'" role="menu">
          <button v-if="canEdit" :class="ROW" role="menuitem" @click="act(() => emit('edit', message))">
            {{ t("messages.edit") }}
          </button>
          <button v-if="!message.deleted" :class="ROW" role="menuitem" @click="act(() => emit('forward', message))">
            {{ t("messages.forward") }}
          </button>
          <button :class="ROW" role="menuitem" @click="act(() => emit('delete', message, 'me'))">
            {{ t("messages.deleteForMe") }}
          </button>
          <button
            v-if="canDeleteForEveryone"
            :class="[ROW, 'text-red-600']"
            role="menuitem"
            @click="act(() => emit('delete', message, 'everyone'))"
          >
            {{ t("messages.deleteForEveryone") }}
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

