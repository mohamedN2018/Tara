<script setup lang="ts">
// The composer's video: pick one file, upload it for the transcoder, show
// "processing" until media says it is ready (or why it failed), then preview
// it with the real player. The post can be sent once `state` is "ready"; send
// `type: "video"` and `media_ids: [mediaId]` (post refuses anything else).
import { Film, X } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import VideoPlayer from "@/components/media/VideoPlayer.vue";
import { errorMessage } from "@/lib/errors";
import {
  MAX_VIDEO_BYTES,
  VIDEO_ACCEPT,
  type VideoAttachmentState,
  videoMime,
  videoService,
} from "@/services/video";

const props = withDefaults(defineProps<{ mediaId?: string | null; disabled?: boolean; showButton?: boolean }>(), {
  mediaId: null,
  disabled: false,
  showButton: true,
});
const emit = defineEmits<{
  "update:mediaId": [id: string | null];
  state: [state: VideoAttachmentState];
}>();
const { t } = useI18n();

const input = ref<HTMLInputElement | null>(null);
const state = ref<VideoAttachmentState>(props.mediaId ? "processing" : "idle");
const error = ref("");

function setState(next: VideoAttachmentState) {
  state.value = next;
  emit("state", next);
}

/** Open the file picker (for a composer that draws its own "Video" button). */
function pick() {
  if (!props.disabled && state.value !== "uploading") input.value?.click();
}

function uploadError(err: unknown): string {
  const code = (err as { response?: { data?: { error?: { code?: string } } } })?.response?.data?.error?.code;
  if (code === "video_quota_exceeded") return t("video.composer.quota");
  if (code === "video_too_large") return t("video.composer.tooBig", { size: Math.round(MAX_VIDEO_BYTES / 1024 / 1024) });
  if ((err as Error)?.message === "unsupported_video_type") return t("video.composer.badType");
  return errorMessage(err);
}

async function onFile(e: Event) {
  const el = e.target as HTMLInputElement;
  const file = el.files?.[0];
  el.value = ""; // the same file again still fires `change`
  if (!file) return;
  error.value = "";
  if (!videoMime(file)) {
    error.value = t("video.composer.badType");
    return;
  }
  if (file.size > MAX_VIDEO_BYTES) {
    error.value = t("video.composer.tooBig", { size: Math.round(MAX_VIDEO_BYTES / 1024 / 1024) });
    return;
  }
  setState("uploading");
  try {
    const asset = await videoService.upload(file);
    emit("update:mediaId", asset.id);
    setState("processing");
  } catch (err) {
    error.value = uploadError(err);
    setState("idle");
  }
}

// The player polls media while the video is processing and reports each status.
function onStatus(status: string) {
  if (status === "ready") setState("ready");
  else if (status === "failed") setState("failed");
  else setState("processing");
}

function remove() {
  emit("update:mediaId", null);
  error.value = "";
  setState("idle");
}

defineExpose({ pick, remove, state });
</script>

<template>
  <div data-testid="video-attachment" :data-state="state">
    <!-- Opened by the button (here or the composer's own); not a second control. -->
    <input
      ref="input"
      type="file"
      class="hidden"
      tabindex="-1"
      aria-hidden="true"
      :accept="VIDEO_ACCEPT"
      data-testid="composer-video-input"
      @change="onFile"
    />
    <button
      v-if="showButton && !mediaId && state !== 'uploading'"
      type="button"
      class="btn-ghost"
      :disabled="disabled"
      :title="t('video.composer.addLabel')"
      @click="pick"
    >
      <Film class="h-5 w-5 text-accent-500" aria-hidden="true" />
      <span class="text-sm">{{ t("video.composer.add") }}</span>
    </button>

    <p v-if="state === 'uploading'" class="mt-2 flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300" role="status">
      <span class="h-4 w-4 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" aria-hidden="true" />
      {{ t("video.composer.uploading") }}
    </p>

    <div v-if="mediaId" class="relative">
      <VideoPlayer :media-id="mediaId" class="!mt-2" @status="onStatus" />
      <button
        type="button"
        class="absolute end-2 top-4 z-10 rounded-full bg-black/60 p-1 text-white hover:bg-black/80"
        :aria-label="t('video.composer.remove')"
        data-testid="video-remove"
        @click="remove"
      >
        <X class="h-4 w-4" aria-hidden="true" />
      </button>
      <p v-if="state === 'ready'" class="mt-1 text-xs text-emerald-700 dark:text-emerald-400" role="status">{{ t("video.composer.ready") }}</p>
    </div>

    <p v-if="error" class="mt-2 text-xs text-red-500" role="alert">{{ error }}</p>
  </div>
</template>
