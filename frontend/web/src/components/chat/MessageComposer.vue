<script setup lang="ts">
import { CornerUpLeft, ImagePlus, Mic, Send, Square, Trash2, X } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import { useVoiceRecorder, type VoiceNote } from "@/lib/useVoiceRecorder";
import { mediaService } from "@/services/media";
import { useToastStore } from "@/stores/toasts";
import type { Message } from "@/types";

defineProps<{ replyingTo?: Message | null; replyingToName?: string }>();
const emit = defineEmits<{
  send: [payload: { body: string; mediaId: string | null }];
  voice: [note: VoiceNote];
  typing: [];
  cancelReply: [];
}>();

const { t } = useI18n();
const toasts = useToastStore();
const body = ref("");
const mediaId = ref<string | null>(null);
const preview = ref<string | null>(null);
const uploading = ref(false);
let sent: { mediaId: string | null; preview: string | null } | null = null;
const voice = useVoiceRecorder();

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
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file) return;
  uploading.value = true;
  try {
    const asset = await mediaService.upload(file, "image");
    mediaId.value = asset.id;
    preview.value = URL.createObjectURL(file);
  } catch {
    // Keep the composer usable for text.
    toasts.push({ text: t("errors.uploadFailed"), icon: "error" });
  } finally {
    uploading.value = false;
  }
}

function clearAttachment() {
  mediaId.value = null;
  preview.value = null;
}

function submit() {
  const text = body.value.trim();
  if ((!text && !mediaId.value) || uploading.value) return;
  sent = { mediaId: mediaId.value, preview: preview.value };
  emit("send", { body: text, mediaId: mediaId.value });
  body.value = "";
  clearAttachment();
}

/** Put a message back after a failed send so nothing typed is lost. */
function restore(text: string, attachment: string | null) {
  if (!body.value) body.value = text;
  if (attachment && attachment === sent?.mediaId) {
    mediaId.value = sent.mediaId;
    preview.value = sent.preview;
  }
}
defineExpose({ restore });
</script>

<template>
  <div class="border-t border-gray-200 p-3 dark:border-gray-800">
    <div
      v-if="replyingTo"
      class="mb-2 flex items-center gap-2 rounded-lg border-s-2 border-brand-500 bg-gray-50 px-3 py-1.5 text-xs dark:bg-gray-800/60"
    >
      <CornerUpLeft class="h-4 w-4 shrink-0 text-brand-500" />
      <span class="min-w-0 flex-1">
        <span class="font-semibold">{{ t("messages.replyingTo", { name: replyingToName }) }}</span>
        <span class="block truncate text-gray-500" dir="auto">{{ replyingTo.body || `📷 ${t("messages.photo")}` }}</span>
      </span>
      <button class="rounded-full p-0.5 text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700" :aria-label="t('messages.cancelReply')" @click="emit('cancelReply')">
        <X class="h-4 w-4" />
      </button>
    </div>

    <div v-if="preview" class="mb-2">
      <div class="relative inline-block">
        <img :src="preview" class="h-20 w-20 rounded-lg object-cover" :alt="t('messages.photo')" />
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
        class="shrink-0 cursor-pointer rounded-full p-2 text-gray-500 transition focus-within:ring-2 focus-within:ring-brand-300 hover:bg-gray-100 dark:hover:bg-gray-800"
        :class="uploading ? 'opacity-50' : ''"
        :title="t('messages.attachImage')"
      >
        <ImagePlus class="h-5 w-5" />
        <input type="file" accept="image/*" class="sr-only" :aria-label="t('messages.attachImage')" @change="onFile" />
      </label>
      <input
        v-model="body"
        class="input"
        dir="auto"
        :aria-label="t('messages.placeholder')"
        :placeholder="uploading ? t('profile.uploading') : t('messages.placeholder')"
        @input="$emit('typing')"
      />
      <button
        v-if="voice.supported && !body.trim() && !mediaId"
        type="button"
        class="shrink-0 rounded-full p-2 text-gray-500 transition hover:bg-gray-100 dark:hover:bg-gray-800"
        :aria-label="t('messages.recordVoice')"
        :title="t('messages.recordVoice')"
        :disabled="uploading"
        @click="startRecording"
      >
        <Mic class="h-5 w-5" />
      </button>
      <button type="submit" class="btn-primary px-3" :aria-label="t('messages.send')" :disabled="uploading || (!body.trim() && !mediaId)">
        <Send class="h-4 w-4 rtl:-scale-x-100" />
      </button>
    </form>
  </div>
</template>
