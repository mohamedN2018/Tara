<script setup lang="ts">
import { Download, FileText } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { formatBytes } from "@/lib/chat";
import { chatService } from "@/services/chat";
import type { MessageAttachment } from "@/types";

// One private chat attachment. Its URL comes from chat (membership-checked,
// presigned, short-lived), never from the public media endpoint.
const props = defineProps<{ messageId: string; attachment: MessageAttachment; alt?: string; compact?: boolean }>();
const { t, locale } = useI18n();

const url = ref<string | null>(null);
const failed = ref(false);
const busy = ref(false);

// `fresh` goes back to chat's cache, which re-mints a URL before it expires.
async function resolve(fresh = false): Promise<string | null> {
  if (url.value && !fresh) return url.value;
  busy.value = true;
  const signed = await chatService.attachmentUrl(props.messageId, props.attachment.media_id);
  busy.value = false;
  url.value = signed?.url ?? null;
  failed.value = !url.value;
  return url.value;
}

// Images and videos render straight away; a file only fetches its URL when opened.
onMounted(() => {
  if (props.attachment.kind === "image" || props.attachment.kind === "video") void resolve();
});

// A photo or video rendered long ago may hold an expired URL: retry once.
let retried = false;
function onMediaError() {
  url.value = null;
  if (retried) {
    failed.value = true;
    return;
  }
  retried = true;
  void resolve(true);
}

async function open() {
  const href = await resolve(true);
  if (href) window.open(href, "_blank", "noopener,noreferrer");
}
</script>

<template>
  <img
    v-if="attachment.kind === 'image' && url"
    :src="url"
    class="w-full object-cover"
    :class="compact ? 'aspect-square' : 'max-h-64'"
    loading="lazy"
    decoding="async"
    :alt="alt ?? t('messages.photo')"
    @error="onMediaError"
  />
  <video
    v-else-if="attachment.kind === 'video' && url"
    :src="url"
    class="w-full bg-black"
    :class="compact ? 'aspect-square object-cover' : 'max-h-72'"
    controls
    preload="metadata"
    playsinline
    data-testid="chat-video"
    @error="onMediaError"
  />
  <button
    v-else-if="attachment.kind === 'file'"
    type="button"
    class="flex w-full items-center gap-2 rounded-lg bg-black/5 px-3 py-2 text-start dark:bg-white/10"
    :disabled="busy"
    :aria-label="`${t('messages.download')}: ${attachment.file_name || t('messages.file')}`"
    data-testid="chat-file"
    @click="open"
  >
    <FileText class="h-6 w-6 shrink-0" />
    <span class="min-w-0 flex-1">
      <span class="block truncate text-sm font-medium" dir="auto">{{ attachment.file_name || t("messages.file") }}</span>
      <span class="block text-[11px] opacity-75" dir="ltr">{{ failed ? t("messages.attachmentUnavailable") : formatBytes(attachment.bytes, locale) }}</span>
    </span>
    <Download class="h-4 w-4 shrink-0" />
  </button>
  <div
    v-else-if="attachment.kind === 'image' || attachment.kind === 'video'"
    class="flex items-center justify-center bg-black/5 text-xs opacity-75 dark:bg-white/10"
    :class="compact ? 'aspect-square' : 'h-32'"
  >
    {{ failed ? t("messages.attachmentUnavailable") : t("states.loading") }}
  </div>
</template>
