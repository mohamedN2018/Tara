<script setup lang="ts">
import { CornerUpLeft, FileText, Mic, Paperclip, Pencil, Send, Square, Trash2, X } from "lucide-vue-next";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { ATTACH_ACCEPT, type AttachmentKind, attachmentKind, formatBytes, tooLarge } from "@/lib/chat";
import { useVoiceRecorder, type VoiceNote } from "@/lib/useVoiceRecorder";
import { chatService } from "@/services/chat";
import { useToastStore } from "@/stores/toasts";
import type { Message } from "@/types";

export interface ComposerAttachment {
  media_id: string;
  kind: AttachmentKind;
  file_name: string;
  bytes: number;
  preview: string | null;
}

const props = defineProps<{ replyingTo?: Message | null; replyingToName?: string; editing?: Message | null }>();
const emit = defineEmits<{
  send: [payload: { body: string; attachment: ComposerAttachment | null }];
  saveEdit: [payload: { message: Message; body: string }];
  voice: [note: VoiceNote];
  typing: [];
  cancelReply: [];
  cancelEdit: [];
}>();

const { t, locale } = useI18n();
const toasts = useToastStore();
const body = ref("");
const attachment = ref<ComposerAttachment | null>(null);
const uploading = ref(false);
let sent: ComposerAttachment | null = null;
const voice = useVoiceRecorder();

// Editing puts the message's text in the box; leaving edit mode clears it.
watch(
  () => props.editing,
  (m, previous) => {
    if (m) body.value = m.body;
    else if (previous) body.value = "";
  },
);

async function startRecording() {
  try {
    await voice.start();
  } catch {
    toasts.push({ text: t("messages.micDenied"), icon: "error" });
  }
}

async function finishRecording() {
  const note = await voice.stop();
  if (note) emit("voice", note);
}

const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

async function onFile(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  const kind = attachmentKind(file);
  if (!kind) {
    toasts.push({ text: t("messages.unsupportedFile"), icon: "error" });
    return;
  }
  if (tooLarge(kind, file.size)) {
    toasts.push({ text: t("messages.fileTooLarge"), icon: "error" });
    return;
  }
  uploading.value = true;
  try {
    // Private upload: only chat, after a membership check, hands out its URL.
    const asset = await chatService.upload(file, kind);
    attachment.value = {
      media_id: asset.id,
      kind,
      file_name: file.name,
      bytes: file.size,
      preview: kind === "file" ? null : URL.createObjectURL(file),
    };
  } catch {
    // Keep the composer usable for text.
    toasts.push({ text: t("errors.uploadFailed"), icon: "error" });
  } finally {
    uploading.value = false;
  }
}

function clearAttachment() {
  attachment.value = null;
}

function submit() {
  const text = body.value.trim();
  if (props.editing) {
    if (!text && !props.editing.attachments.length) return;
    emit("saveEdit", { message: props.editing, body: text });
    return;
  }
  if ((!text && !attachment.value) || uploading.value) return;
  sent = attachment.value;
  emit("send", { body: text, attachment: attachment.value });
  body.value = "";
  clearAttachment();
}

/** Put a message back after a failed send so nothing typed is lost. */
function restore(text: string, mediaId: string | null) {
  if (!body.value) body.value = text;
  if (mediaId && mediaId === sent?.media_id) attachment.value = sent;
}
defineExpose({ restore });
</script>

<template>
  <div class="border-t border-gray-200 p-3 dark:border-gray-800">
    <div
      v-if="editing"
      class="mb-2 flex items-center gap-2 rounded-lg border-s-2 border-amber-500 bg-gray-50 px-3 py-1.5 text-xs dark:bg-gray-800/60"
      data-testid="editing-bar"
    >
      <Pencil class="h-4 w-4 shrink-0 text-amber-500" />
      <span class="min-w-0 flex-1 font-semibold">{{ t("messages.editing") }}</span>
      <button class="rounded-full p-0.5 text-gray-500 hover:bg-gray-200 dark:text-gray-400 dark:hover:bg-gray-700" :aria-label="t('messages.cancelEdit')" @click="emit('cancelEdit')">
        <X class="h-4 w-4" />
      </button>
    </div>
    <div
      v-else-if="replyingTo"
      class="mb-2 flex items-center gap-2 rounded-lg border-s-2 border-brand-500 bg-gray-50 px-3 py-1.5 text-xs dark:bg-gray-800/60"
    >
      <CornerUpLeft class="h-4 w-4 shrink-0 text-brand-500" />
      <span class="min-w-0 flex-1">
        <span class="font-semibold">{{ t("messages.replyingTo", { name: replyingToName }) }}</span>
        <span class="block truncate text-gray-500 dark:text-gray-400" dir="auto">{{ replyingTo.body || `📎 ${t("messages.file")}` }}</span>
      </span>
      <button class="rounded-full p-0.5 text-gray-500 hover:bg-gray-200 dark:text-gray-400 dark:hover:bg-gray-700" :aria-label="t('messages.cancelReply')" @click="emit('cancelReply')">
        <X class="h-4 w-4" />
      </button>
    </div>

    <div v-if="attachment && !editing" class="mb-2" data-testid="composer-attachment">
      <div class="relative inline-block">
        <img v-if="attachment.kind === 'image' && attachment.preview" :src="attachment.preview" class="h-20 w-20 rounded-lg object-cover" :alt="t('messages.photo')" />
        <video v-else-if="attachment.kind === 'video' && attachment.preview" :src="attachment.preview" class="h-20 w-28 rounded-lg bg-black object-cover" muted />
        <span v-else class="flex max-w-xs items-center gap-2 rounded-lg bg-gray-100 px-3 py-2 text-sm dark:bg-gray-800">
          <FileText class="h-5 w-5 shrink-0" />
          <span class="min-w-0 truncate" dir="auto">{{ attachment.file_name }}</span>
          <span class="shrink-0 text-xs text-gray-500" dir="ltr">{{ formatBytes(attachment.bytes, locale) }}</span>
        </span>
        <button
          class="absolute -end-1.5 -top-1.5 rounded-full bg-black/60 p-0.5 text-white"
          :aria-label="t('messages.removeAttachment')"
          @click="clearAttachment"
        >
          <X class="h-3.5 w-3.5" />
        </button>
      </div>
    </div>

    <div v-if="voice.recording.value" class="flex items-center gap-3" role="status">
      <span class="h-2.5 w-2.5 animate-pulse rounded-full bg-red-500" aria-hidden="true" />
      <span class="text-sm">{{ t("messages.recording") }}</span>
      <span class="text-sm tabular-nums" dir="ltr">{{ clock(voice.seconds.value) }}</span>
      <span class="flex-1" />
      <button type="button" class="btn-ghost px-2" :aria-label="t('messages.cancelRecording')" @click="voice.cancel()">
        <Trash2 class="h-4 w-4" />
      </button>
      <button type="button" class="btn-primary px-3" :aria-label="t('messages.stopAndSend')" @click="finishRecording">
        <Square class="h-4 w-4" />
      </button>
    </div>

    <form v-else class="flex items-center gap-2" @submit.prevent="submit">
      <label
        v-if="!editing"
        class="shrink-0 cursor-pointer rounded-full p-2 text-gray-500 transition focus-within:ring-2 focus-within:ring-brand-400 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
        :class="uploading ? 'opacity-50' : ''"
        :title="t('messages.attachFile')"
      >
        <Paperclip class="h-5 w-5" />
        <input type="file" :accept="ATTACH_ACCEPT" class="sr-only" :aria-label="t('messages.attachFile')" :disabled="uploading" @change="onFile" />
      </label>
      <input
        v-model="body"
        class="input"
        dir="auto"
        :aria-label="t('messages.placeholder')"
        :placeholder="uploading ? t('profile.uploading') : t('messages.placeholder')"
        @input="$emit('typing')"
        @keydown.esc="editing && emit('cancelEdit')"
      />
      <button
        v-if="voice.supported && !body.trim() && !attachment && !editing"
        type="button"
        class="shrink-0 rounded-full p-2 text-gray-500 transition hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
        :aria-label="t('messages.recordVoice')"
        :title="t('messages.recordVoice')"
        :disabled="uploading"
        @click="startRecording"
      >
        <Mic class="h-5 w-5" />
      </button>
      <button type="submit" class="btn-primary px-3" :aria-label="t('messages.send')" :disabled="uploading || (!body.trim() && !attachment && !editing)">
        <Send class="h-4 w-4 rtl:-scale-x-100" />
      </button>
    </form>
  </div>
</template>
