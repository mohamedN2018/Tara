<script setup lang="ts">
import { Pause, Play } from "lucide-vue-next";
import { computed, onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";

import { chatService } from "@/services/chat";
import { mediaService } from "@/services/media";

// Chat voice notes are private: pass `messageId` and chat mints the URL.
const props = defineProps<{ mediaId: string; durationMs: number | null; messageId?: string }>();
const { t } = useI18n();

const audio = ref<HTMLAudioElement | null>(null);
const src = ref<string | null>(null);
const playing = ref(false);
const loading = ref(false);
const failed = ref(false);
const position = ref(0);
// Presigned URLs live ~15 minutes: a note not started yet gets a fresh one after this.
const SRC_TTL_MS = 10 * 60 * 1000;
let resolvedAt = 0;

function clock(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
const label = computed(() =>
  clock(playing.value || position.value ? position.value : (props.durationMs ?? 0) / 1000),
);

// The URL is presigned and short-lived, so it is resolved on demand, not on render.
async function toggle() {
  const el = audio.value;
  if (!el) return;
  if (playing.value) {
    el.pause();
    return;
  }
  failed.value = false;
  loading.value = true;
  try {
    if (!src.value || (el.currentTime === 0 && Date.now() - resolvedAt > SRC_TTL_MS)) {
      resolvedAt = Date.now();
      src.value = props.messageId
        ? ((await chatService.attachmentUrl(props.messageId, props.mediaId))?.url ?? null)
        : await mediaService.resolveUrl(props.mediaId);
      if (!src.value) throw new Error("media not ready");
      el.src = src.value;
    }
    await el.play();
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

function ended() {
  playing.value = false;
  position.value = 0;
}

onBeforeUnmount(() => audio.value?.pause());
</script>

<template>
  <div class="flex items-center gap-2" data-testid="voice-player">
    <button
      type="button"
      class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-black/10 transition hover:bg-black/20 disabled:opacity-50 dark:bg-white/15"
      :aria-label="playing ? t('messages.pauseVoice') : t('messages.playVoice')"
      :disabled="loading"
      @click="toggle"
    >
      <Pause v-if="playing" class="h-4 w-4" />
      <Play v-else class="h-4 w-4 rtl:-scale-x-100" />
    </button>
    <span class="text-xs tabular-nums" dir="ltr">{{ label }}</span>
    <span class="text-xs opacity-80">{{ failed ? t("messages.voiceUnavailable") : t("messages.voiceNote") }}</span>
    <audio
      ref="audio"
      preload="none"
      @play="playing = true"
      @pause="playing = false"
      @ended="ended"
      @timeupdate="position = ($event.target as HTMLAudioElement).currentTime"
    />
  </div>
</template>
