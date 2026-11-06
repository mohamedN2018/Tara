<script setup lang="ts">
// A transcoded video (roadmap 5.3 / 5.7). Media decides who may watch: the
// player asks for a viewer-bound playlist token, then plays the HLS ladder with
// the browser's own HLS (Safari) or hls.js, which is only downloaded on the
// first play. Our own controls keep the scrubber right in Arabic: playback
// controls and the timeline stay left to right in every language (they follow
// the media, not the text: Material and Apple guidelines), so the range input
// must not inherit the page's dir="rtl" and run backwards.
//
// Delivery policy (08 §7.9, WP 4c.6-B3), from the surface's `delivery.video`:
// the playback token and the poster are asked for only once the player comes
// within `load_margin_vp` viewports; a player more than `unmount_beyond_vp`
// viewports away gives up its <video> and hls.js and shows its poster; feed
// players (those with a signal item) follow lib/playbackCoordinator
// (`muted_single`: one muted autoplay at a time, data-saver and reduced-motion
// respected). `preload="none"` stays.
import { AlertTriangle, Loader2, Maximize, Minimize, Pause, Play, VideoOff, Volume2, VolumeX } from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { delivery, type DeliverySurface } from "@/lib/delivery";
import { claim, type CoordinatedPlayer, noteUnmute, register, report, userPaused } from "@/lib/playbackCoordinator";
import type { SignalSurface } from "@/lib/signals";
import { bindWatchSignals } from "@/lib/videoSignals";
import { viaStorageProxy } from "@/services/media";
import { isProcessing, type Playback, videoService } from "@/services/video";

type HlsInstance = {
  loadSource(url: string): void;
  attachMedia(el: HTMLMediaElement): void;
  recoverMediaError(): void;
  destroy(): void;
  on(event: string, cb: (event: string, data: { fatal?: boolean; type?: string }) => void): void;
};

const props = withDefaults(
  defineProps<{
    mediaId: string;
    pollMs?: number;
    label?: string;
    /** Tara Intelligence (WP 2.8): `video:<post id>` / `reel:<post id>`; no signals without it. */
    signalItem?: string | null;
    signalSurface?: SignalSurface;
  }>(),
  { pollMs: 3000, label: "", signalItem: null, signalSurface: "link" },
);
const emit = defineEmits<{ status: [status: string] }>();
const { t, te } = useI18n();

type State = "loading" | "processing" | "failed" | "unavailable" | "ready" | "error";
const state = ref<State>("loading");
const info = ref<Playback | null>(null);
const el = ref<HTMLVideoElement | null>(null);
const root = ref<HTMLElement | null>(null);
const started = ref(false);
const playing = ref(false);
const waiting = ref(false);
const muted = ref(false);
const current = ref(0);
const duration = ref(0);
const fullscreen = ref(false);

let hls: HlsInstance | null = null;
let pollTimer: ReturnType<typeof setTimeout> | null = null;
let observer: IntersectionObserver | null = null;
let nearObserver: IntersectionObserver | null = null;
let farObserver: IntersectionObserver | null = null;

// The surface's delivery block (Home's for any other surface).
const BLOCK_OF: Partial<Record<SignalSurface, DeliverySurface>> = { home: "home", reels: "reels", video: "video" };
const policy = () => delivery(BLOCK_OF[props.signalSurface] ?? "home").video;
const observable = typeof IntersectionObserver !== "undefined";
// Without IntersectionObserver (old browsers, tests) the player loads at once, as before.
const active = ref(!observable);
const asked = ref(false);
const poster = computed(() => {
  const p = info.value as (Playback & { poster_480_url?: string | null }) | null;
  return p?.poster_480_url || p?.poster_url || undefined;
});
// Segment URLs expire every few minutes, so a long video needs many refreshes. A
// refresh counts as done once playback resumes (`playing`); a failure before
// that, or a second one within REFRESH_MIN_GAP_MS, is a real error, not a loop.
const REFRESH_MIN_GAP_MS = 10_000;
let refreshing = false;
let lastRefreshAt = -Infinity;
let disposed = false;

const ratio = computed(() => {
  const w = info.value?.width;
  const h = info.value?.height;
  return w && h ? `${w} / ${h}` : "16 / 9";
});
const failureText = computed(() => {
  const code = info.value?.failure_code || "other";
  const key = `video.failed.${code}`;
  return te(key) ? t(key) : t("video.failed.other");
});

function fmt(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
  const s = Math.floor(seconds % 60);
  const m = Math.floor(seconds / 60) % 60;
  const h = Math.floor(seconds / 3600);
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}
const positionText = computed(() => t("video.player.position", { current: fmt(current.value), total: fmt(duration.value) }));

function apply(p: Playback) {
  info.value = p;
  emit("status", p.status);
  if (p.duration_ms && !duration.value) duration.value = p.duration_ms / 1000;
  if (p.status === "ready") state.value = "ready";
  else if (p.status === "failed") state.value = "failed";
  else if (isProcessing(p.status)) {
    state.value = "processing";
    schedulePoll();
  }
}

function schedulePoll() {
  if (pollTimer || disposed) return;
  pollTimer = setTimeout(async () => {
    pollTimer = null;
    await load();
  }, props.pollMs);
}

async function load(): Promise<Playback | null> {
  asked.value = true;
  try {
    const p = await videoService.playback(props.mediaId);
    if (!disposed) apply(p);
    return p;
  } catch (err) {
    const status = (err as { response?: { status?: number } })?.response?.status;
    if (!disposed) state.value = status === 404 ? "unavailable" : "error";
    return null;
  }
}

/** Storage URLs inside the playlists, sent through the dev/e2e /__s3 proxy. */
function storageXhrSetup(xhr: XMLHttpRequest, url: string) {
  let target = url;
  try {
    if (new URL(url).origin !== window.location.origin) target = viaStorageProxy(url) ?? url;
  } catch {
    return;
  }
  if (target !== url) xhr.open("GET", target, true);
}
const storageProxied = viaStorageProxy("http://storage.invalid/x") !== "http://storage.invalid/x";

async function attach(p: Playback): Promise<void> {
  const video = el.value;
  if (!video || !p.hls_url) return;
  const native = !storageProxied && !!video.canPlayType("application/vnd.apple.mpegurl");
  if (native) {
    video.src = p.hls_url;
    return;
  }
  const { default: Hls } = await import("hls.js");
  // Unmounted (or the element replaced) while hls.js was downloading.
  if (disposed || el.value !== video) return;
  if (!Hls.isSupported()) {
    if (p.mp4_url) {
      video.src = p.mp4_url;
      return;
    }
    throw new Error("hls_unsupported");
  }
  hls?.destroy();
  const instance = new Hls({
    enableWorker: true,
    maxBufferLength: 30,
    ...(storageProxied ? { xhrSetup: storageXhrSetup } : {}),
  }) as unknown as HlsInstance;
  instance.on(Hls.Events.ERROR, (_event, data) => {
    if (!data.fatal) return;
    if (data.type === Hls.ErrorTypes.MEDIA_ERROR) instance.recoverMediaError();
    else void refresh();
  });
  instance.loadSource(p.hls_url);
  instance.attachMedia(video);
  hls = instance;
}

/** Segment URLs and the token expire: fetch a fresh playlist and resume where we were. */
async function refresh() {
  if (disposed) return;
  const now = Date.now();
  if (refreshing || now - lastRefreshAt < REFRESH_MIN_GAP_MS) {
    refreshing = false;
    state.value = "error";
    return;
  }
  refreshing = true;
  lastRefreshAt = now;
  const at = el.value?.currentTime ?? 0;
  const p = await load();
  if (disposed || !p || p.status !== "ready") return;
  await attach(p);
  if (disposed) return;
  if (el.value) {
    el.value.currentTime = at;
    void el.value.play().catch(() => {});
  }
}

async function play() {
  const video = el.value;
  if (!video || state.value !== "ready" || !info.value) return;
  if (!started.value) {
    started.value = true;
    waiting.value = true;
    try {
      await attach(info.value);
    } catch {
      if (!disposed) state.value = "error";
      return;
    }
    if (disposed) return;
  }
  try {
    await video.play();
  } catch {
    // Autoplay rules or a load error: the error handlers update the state.
  }
}

function toggle() {
  const video = el.value;
  if (!video) return;
  if (!started.value || video.paused) {
    if (coordinated) claim(self);
    void play();
  } else {
    video.pause();
    if (coordinated) userPaused(self);
  }
}

function seek(e: Event) {
  const video = el.value;
  const value = Number((e.target as HTMLInputElement).value);
  if (!video || !Number.isFinite(value)) return;
  video.currentTime = value;
  current.value = value;
}

function toggleMute() {
  if (!el.value) return;
  el.value.muted = !el.value.muted;
  muted.value = el.value.muted;
  // The viewer wants sound: the next video the policy starts keeps it (once).
  if (!muted.value && coordinated) noteUnmute();
}

async function toggleFullscreen() {
  const node = root.value;
  if (!node) return;
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else if (node.requestFullscreen) await node.requestFullscreen();
    else (el.value as HTMLVideoElement & { webkitEnterFullscreen?: () => void })?.webkitEnterFullscreen?.();
  } catch {
    // Fullscreen refused (iframe, user setting): nothing to do.
  }
}

function onFullscreenChange() {
  fullscreen.value = document.fullscreenElement === root.value;
}

function onKey(e: KeyboardEvent) {
  if (e.target instanceof HTMLInputElement) return; // the scrubber has its own keys
  if (e.key === " " || e.key === "k") {
    e.preventDefault();
    toggle();
  } else if (e.key === "m") toggleMute();
}

/** Playback resumed: the last refresh worked, so the next expiry may refresh again. */
function onPlaying() {
  waiting.value = false;
  refreshing = false;
}

async function retry() {
  refreshing = false;
  lastRefreshAt = -Infinity;
  started.value = false;
  state.value = "loading";
  hls?.destroy();
  hls = null;
  await load();
}

// The coordinator's view of this player (feed players only: they carry a signal item).
const coordinated = !!props.signalItem;
const self: CoordinatedPlayer = {
  ratio: 0,
  policy,
  autoplay: async (mute: boolean) => {
    const video = el.value;
    if (!video || state.value !== "ready" || !info.value) return false;
    video.muted = mute;
    muted.value = mute;
    await play();
    if (!video.paused) return true;
    if (!mute) return self.autoplay(true); // sound refused by the browser: muted then
    return false;
  },
  pause: () => {
    if (el.value && !el.value.paused) el.value.pause();
  },
};
let unregister: (() => void) | null = null;

/** Far away: give the <video> and hls.js back, keep the poster. */
function park() {
  if (!active.value) return;
  self.pause();
  hls?.destroy();
  hls = null;
  started.value = false;
  playing.value = false;
  waiting.value = false;
  active.value = false;
}

function observeDistance(node: HTMLElement) {
  const vh = window.innerHeight || 800;
  const p = policy();
  nearObserver = new IntersectionObserver(
    ([entry]) => {
      if (!entry?.isIntersecting) return;
      active.value = true;
      if (!asked.value) void load();
    },
    { rootMargin: `${Math.round(p.load_margin_vp * vh)}px 0px` },
  );
  nearObserver.observe(node);
  farObserver = new IntersectionObserver(
    ([entry]) => {
      if (entry && !entry.isIntersecting) park();
    },
    { rootMargin: `${Math.round(p.unmount_beyond_vp * vh)}px 0px` },
  );
  farObserver.observe(node);
}

onMounted(() => {
  if (!observable) void load();
  document.addEventListener("fullscreenchange", onFullscreenChange);
  if (observable && root.value) {
    observeDistance(root.value);
    // Leaving the screen pauses, like a feed should; feed players report how visible they are.
    observer = new IntersectionObserver(
      ([entry]) => {
        const ratio = entry?.isIntersecting ? entry.intersectionRatio : 0;
        if (ratio < policy().pause_below && el.value && !el.value.paused) el.value.pause();
        if (coordinated) report(self, ratio);
      },
      { threshold: [0, 0.1, 0.25, 0.4, 0.6, 0.8, 1] },
    );
    observer.observe(root.value);
  }
  if (coordinated) unregister = register(self);
});

watch(
  () => props.mediaId,
  () => {
    if (active.value || !observable) void retry();
    else asked.value = false; // asked for again when it comes near
  },
);

// Watch signals from what really played (start, progress, complete, rewatch, skip).
let unbindSignals: (() => void) | null = null;
watch(
  [el, () => props.signalItem, () => props.signalSurface],
  ([video, item, surface]) => {
    unbindSignals?.();
    unbindSignals = video && item ? bindWatchSignals(video, { item, surface }) : null;
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  unbindSignals?.();
  unbindSignals = null;
  disposed = true;
  if (pollTimer) clearTimeout(pollTimer);
  observer?.disconnect();
  nearObserver?.disconnect();
  farObserver?.disconnect();
  unregister?.();
  document.removeEventListener("fullscreenchange", onFullscreenChange);
  hls?.destroy();
  hls = null;
});

defineExpose({ play, state });
</script>

<template>
  <div
    ref="root"
    class="relative mt-3 w-full overflow-hidden rounded-2xl bg-black text-white"
    :style="{ aspectRatio: ratio, maxHeight: '75vh' }"
    data-testid="video-player"
    :data-state="state"
    :data-loaded="asked ? '1' : '0'"
    @keydown="onKey"
  >
    <!-- Far away (or not near yet): no <video>; the poster once known. -->
    <img
      v-if="!active && poster"
      :src="poster"
      alt=""
      class="h-full w-full object-contain"
      loading="lazy"
      decoding="async"
      data-poster
    />
    <video
      v-if="active"
      ref="el"
      class="h-full w-full object-contain"
      :poster="poster"
      playsinline
      preload="none"
      :aria-label="label || t('video.player.label')"
      data-testid="video-element"
      @click="toggle"
      @play="playing = true"
      @pause="playing = false"
      @playing="onPlaying"
      @waiting="waiting = true"
      @canplay="waiting = false"
      @timeupdate="current = el?.currentTime ?? 0"
      @loadedmetadata="duration = Number.isFinite(el?.duration) ? (el?.duration ?? 0) : duration"
      @error="state === 'ready' && started ? refresh() : undefined"
    />

    <!-- Loading, processing, failed, unavailable: a centred message over the dark frame. -->
    <div
      v-if="state !== 'ready'"
      class="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-gray-900/90 p-4 text-center text-sm"
      role="status"
      :aria-live="state === 'processing' ? 'polite' : undefined"
    >
      <template v-if="state === 'loading' || state === 'processing'">
        <Loader2 class="h-7 w-7 animate-spin text-brand-300" aria-hidden="true" />
        <p class="font-semibold">{{ state === "loading" ? t("video.player.loading") : t("video.player.processing") }}</p>
        <p v-if="state === 'processing'" class="text-xs text-gray-300">{{ t("video.player.processingHint") }}</p>
      </template>
      <template v-else-if="state === 'failed'">
        <AlertTriangle class="h-7 w-7 text-accent-400" aria-hidden="true" />
        <p class="font-semibold">{{ t("video.failed.title") }}</p>
        <p class="text-xs text-gray-300" data-testid="video-failure">{{ failureText }}</p>
      </template>
      <template v-else-if="state === 'unavailable'">
        <VideoOff class="h-7 w-7 text-gray-400" aria-hidden="true" />
        <p class="font-semibold">{{ t("video.player.unavailable") }}</p>
      </template>
      <template v-else>
        <AlertTriangle class="h-7 w-7 text-accent-400" aria-hidden="true" />
        <p class="font-semibold">{{ t("video.player.playbackError") }}</p>
        <button type="button" class="btn-ghost text-white hover:bg-white/10" @click="retry">{{ t("video.player.retry") }}</button>
      </template>
    </div>

    <template v-else>
      <button
        v-if="!playing && !waiting"
        type="button"
        class="absolute inset-0 m-auto flex h-16 w-16 items-center justify-center rounded-full bg-black/55 text-white shadow-lg transition hover:bg-brand-600 focus:outline-none focus-visible:ring-4 focus-visible:ring-brand-400"
        :aria-label="t('video.player.play')"
        data-testid="video-play"
        @click="toggle"
      >
        <Play class="h-8 w-8" aria-hidden="true" />
      </button>
      <Loader2 v-else-if="waiting" class="pointer-events-none absolute inset-0 m-auto h-10 w-10 animate-spin text-white/80" aria-hidden="true" />

      <div
        v-if="started"
        class="absolute inset-x-0 bottom-0 flex items-center gap-2 bg-gradient-to-t from-black/80 to-transparent px-3 pb-2 pt-6"
        dir="ltr"
        data-testid="video-controls"
      >
        <button type="button" class="rounded-full p-1.5 hover:bg-white/15 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300" :aria-label="playing ? t('video.player.pause') : t('video.player.play')" @click="toggle">
          <Pause v-if="playing" class="h-5 w-5" aria-hidden="true" />
          <Play v-else class="h-5 w-5" aria-hidden="true" />
        </button>
        <input
          type="range"
          class="video-scrubber h-1 min-w-0 flex-1 cursor-pointer"
          min="0"
          :max="duration || 0"
          step="0.1"
          :value="current"
          dir="ltr"
          :aria-label="t('video.player.seek')"
          :aria-valuetext="positionText"
          data-testid="video-scrubber"
          @input="seek"
        />
        <span class="shrink-0 text-xs tabular-nums" dir="ltr" data-testid="video-time">{{ fmt(current) }} / {{ fmt(duration) }}</span>
        <button type="button" class="rounded-full p-1.5 hover:bg-white/15 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300" :aria-label="muted ? t('video.player.unmute') : t('video.player.mute')" :aria-pressed="muted" @click="toggleMute">
          <VolumeX v-if="muted" class="h-5 w-5" aria-hidden="true" />
          <Volume2 v-else class="h-5 w-5" aria-hidden="true" />
        </button>
        <button type="button" class="rounded-full p-1.5 hover:bg-white/15 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300" :aria-label="fullscreen ? t('video.player.exitFullscreen') : t('video.player.fullscreen')" @click="toggleFullscreen">
          <Minimize v-if="fullscreen" class="h-5 w-5" aria-hidden="true" />
          <Maximize v-else class="h-5 w-5" aria-hidden="true" />
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.video-scrubber {
  accent-color: #a855f7;
}
</style>
