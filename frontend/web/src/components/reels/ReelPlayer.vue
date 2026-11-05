<script setup lang="ts">
// One reel's video (roadmap 5.8), on the shared pipeline of 5.2/5.3: media hands
// out a viewer-bound playlist token, and the HLS ladder plays with the browser's
// own HLS (Safari) or hls.js (lazy). Unlike the post VideoPlayer there are no
// controls: the pager mounts at most three of these, the active one plays
// muted on its own and loops, and a tap pauses (the pager handles taps).
import { AlertTriangle, Loader2, VideoOff } from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { viaStorageProxy } from "@/services/media";
import { type Playback, videoService } from "@/services/video";

import { reelsMuted } from "./pager";

type HlsInstance = {
  loadSource(url: string): void;
  attachMedia(el: HTMLMediaElement): void;
  recoverMediaError(): void;
  destroy(): void;
  on(event: string, cb: (event: string, data: { fatal?: boolean; type?: string }) => void): void;
};

const props = withDefaults(defineProps<{ mediaId: string; active: boolean; label?: string; cover?: string | null }>(), {
  label: "",
  cover: null,
});
const emit = defineEmits<{ playing: []; paused: [] }>();
const { t } = useI18n();

type State = "loading" | "ready" | "unavailable" | "error";
const state = ref<State>("loading");
const info = ref<Playback | null>(null);
const el = ref<HTMLVideoElement | null>(null);
const paused = ref(true);
const progress = ref(0);
// The viewer paused this reel with a tap: it stays paused until tapped again.
const heldByViewer = ref(false);
let hls: HlsInstance | null = null;
let disposed = false;
let attached = false;

const poster = computed(() => props.cover || info.value?.poster_url || undefined);
const storageProxied = viaStorageProxy("http://storage.invalid/x") !== "http://storage.invalid/x";

function storageXhrSetup(xhr: XMLHttpRequest, url: string) {
  let target = url;
  try {
    if (new URL(url).origin !== window.location.origin) target = viaStorageProxy(url) ?? url;
  } catch {
    return;
  }
  if (target !== url) xhr.open("GET", target, true);
}

async function attach(p: Playback) {
  const video = el.value;
  if (!video || !p.hls_url || attached) return;
  attached = true;
  const native = !storageProxied && !!video.canPlayType("application/vnd.apple.mpegurl");
  if (native) {
    video.src = p.hls_url;
    return;
  }
  const { default: Hls } = await import("hls.js");
  if (disposed || el.value !== video) return;
  if (!Hls.isSupported()) {
    if (p.mp4_url) video.src = p.mp4_url;
    else state.value = "error";
    return;
  }
  const instance = new Hls({
    enableWorker: true,
    maxBufferLength: 10,
    ...(storageProxied ? { xhrSetup: storageXhrSetup } : {}),
  }) as unknown as HlsInstance;
  instance.on(Hls.Events.ERROR, (_event, data) => {
    if (!data.fatal) return;
    if (data.type === Hls.ErrorTypes.MEDIA_ERROR) instance.recoverMediaError();
    else state.value = "error";
  });
  instance.loadSource(p.hls_url);
  instance.attachMedia(video);
  hls = instance;
}

async function load() {
  try {
    const p = await videoService.playback(props.mediaId);
    if (disposed) return;
    info.value = p;
    if (p.status !== "ready") {
      state.value = "unavailable";
      return;
    }
    state.value = "ready";
    await attach(p);
    if (props.active) void play();
  } catch (err) {
    const status = (err as { response?: { status?: number } })?.response?.status;
    if (!disposed) state.value = status === 404 ? "unavailable" : "error";
  }
}

async function play() {
  const video = el.value;
  if (!video || state.value !== "ready") return;
  video.muted = reelsMuted.value;
  try {
    await video.play();
  } catch {
    // Autoplay refused even muted (a browser setting): the viewer taps to play.
    paused.value = true;
  }
}

function pause() {
  el.value?.pause();
}

/** A tap on the reel: pause or resume. */
function toggle() {
  const video = el.value;
  if (!video) return;
  if (video.paused) {
    heldByViewer.value = false;
    void play();
  } else {
    heldByViewer.value = true;
    pause();
  }
}

watch(
  () => props.active,
  (active) => {
    if (active && !heldByViewer.value) void play();
    else if (!active) {
      pause();
      heldByViewer.value = false;
    }
  },
);
watch(reelsMuted, (muted) => {
  if (el.value) el.value.muted = muted;
});

function onTime() {
  const video = el.value;
  if (!video || !Number.isFinite(video.duration) || video.duration <= 0) return;
  progress.value = Math.min(1, video.currentTime / video.duration);
}

onMounted(() => void load());
onBeforeUnmount(() => {
  disposed = true;
  hls?.destroy();
  hls = null;
});

defineExpose({ toggle, play, pause, paused, state });
</script>

<template>
  <div class="relative h-full w-full bg-black" data-testid="reel-player" :data-state="state" :data-paused="paused ? 'true' : 'false'">
    <video
      ref="el"
      class="h-full w-full object-contain"
      :poster="poster"
      :aria-label="label || t('reels.player')"
      playsinline
      loop
      muted
      preload="auto"
      data-testid="reel-video"
      @play="paused = false"
      @playing="emit('playing')"
      @pause="
        paused = true;
        emit('paused');
      "
      @timeupdate="onTime"
    />
    <div v-if="state !== 'ready'" class="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-gray-950/80 p-4 text-center text-sm text-white" role="status">
      <Loader2 v-if="state === 'loading'" class="h-8 w-8 animate-spin text-brand-300" aria-hidden="true" />
      <VideoOff v-else-if="state === 'unavailable'" class="h-8 w-8 text-gray-400" aria-hidden="true" />
      <AlertTriangle v-else class="h-8 w-8 text-accent-400" aria-hidden="true" />
      <p class="font-semibold">
        {{ state === "loading" ? t("reels.loadingVideo") : state === "unavailable" ? t("reels.unavailable") : t("reels.playbackError") }}
      </p>
    </div>
    <!-- Media time runs left to right in every language. -->
    <div class="pointer-events-none absolute inset-x-0 bottom-0 h-1 bg-white/20" dir="ltr" aria-hidden="true">
      <div class="h-full bg-white" :style="{ width: `${progress * 100}%` }" />
    </div>
  </div>
</template>
