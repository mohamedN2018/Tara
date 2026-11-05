<script setup lang="ts">
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Maximize2,
  Minimize2,
  PanelRightClose,
  PanelRightOpen,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref, useSlots, watch } from "vue";
import { useI18n } from "vue-i18n";

import { downloadMedia } from "@/lib/downloadMedia";
import { type Direction, keyToDelta, pageDirection, stepIndex, swipeToDelta } from "@/lib/mediaViewer";
import { clampPan, MAX_ZOOM, type Point, stepZoom } from "@/lib/photoFrame";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { useMediaList } from "@/lib/useMediaList";
import { useToastStore } from "@/stores/toasts";

// Full-screen photo viewer (QTech's "theater", rewritten): the parent keeps the
// open index in the URL; this component only shows it and asks to move.
// A parent may fill the `panel` slot (author, text, reactions, comments): it
// sits beside the photo on wide screens and over its lower part on phones.
// Zoom (buttons, + / - keys, double-click, drag to pan) and full screen are built in.
const props = defineProps<{ mediaIds: string[]; index: number; authorName: string }>();
const emit = defineEmits<{ go: [index: number]; close: [] }>();
const { t } = useI18n();
const slots = useSlots();
const hasPanel = computed(() => !!slots.panel);

const urls = useMediaList(() => props.mediaIds);
const toasts = useToastStore();

// Download the photo on screen through its signed URL (media decides who may).
const downloading = ref(false);
async function download() {
  const id = props.mediaIds[props.index];
  if (!id || downloading.value) return;
  downloading.value = true;
  try {
    await downloadMedia(id);
  } catch {
    toasts.push({ text: t("postsFeed.media.downloadFailed"), icon: "error" });
  } finally {
    downloading.value = false;
  }
}
const total = computed(() => props.mediaIds.length);
const many = computed(() => total.value > 1);
const dir = ref<Direction>(pageDirection());
// Which way the photo slides in, from the reading direction and the move.
const moved = ref<1 | -1>(1);
const shift = computed(() => `${(dir.value === "rtl" ? -1 : 1) * 44}px`);

const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);
useEscapeKey(ref(true), () => emit("close"));

// ---- the details panel: open by default on wide screens ----
const wide = () => typeof window !== "undefined" && !!window.matchMedia?.("(min-width: 1024px)").matches;
const panelOpen = ref(wide());

// ---- zoom and pan ----
const zoom = ref(1);
const pan = ref<Point>({ x: 0, y: 0 });
const stage = ref<HTMLElement | null>(null);
const zoomed = computed(() => zoom.value > 1);
function stageBox() {
  const r = stage.value?.getBoundingClientRect();
  return { width: r?.width ?? 0, height: r?.height ?? 0 };
}
function setZoom(next: number) {
  zoom.value = next;
  pan.value = next > 1 ? clampPan(pan.value, next, stageBox()) : { x: 0, y: 0 };
}
const zoomIn = () => setZoom(stepZoom(zoom.value, 1));
const zoomOut = () => setZoom(stepZoom(zoom.value, -1));
const toggleZoom = () => setZoom(zoomed.value ? 1 : 2);
// Every photo starts unzoomed.
watch(
  () => props.index,
  () => setZoom(1),
);
let dragFrom: { x: number; y: number; pan: Point } | null = null;
function onPointerDown(e: PointerEvent) {
  if (!zoomed.value || (e.target as HTMLElement | null)?.closest?.("button")) return;
  dragFrom ={ x: e.clientX, y: e.clientY, pan: { ...pan.value } };
  (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
}
function onPointerMove(e: PointerEvent) {
  if (!dragFrom) return;
  pan.value = clampPan(
    { x: dragFrom.pan.x + e.clientX - dragFrom.x, y: dragFrom.pan.y + e.clientY - dragFrom.y },
    zoom.value,
    stageBox(),
  );
}
function onPointerUp() {
  dragFrom = null;
}
const photoStyle = computed(() =>
  zoomed.value ? { transform: `translate(${pan.value.x}px, ${pan.value.y}px) scale(${zoom.value})` } : undefined,
);

// ---- full screen, where the browser allows it ----
const canFullscreen = ref(false);
const isFullscreen = ref(false);
function onFullscreenChange() {
  isFullscreen.value = !!document.fullscreenElement;
}
async function toggleFullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await dialog.value?.requestFullscreen?.();
  } catch {
    // Refused (an iframe, a browser policy): the viewer stays as it is.
  }
}

function move(delta: number) {
  if (!many.value || !delta) return;
  moved.value = delta > 0 ? 1 : -1;
  emit("go", stepIndex(props.index, delta, total.value));
}
function jump(i: number) {
  if (i === props.index) return;
  moved.value = i > props.index ? 1 : -1;
  emit("go", i);
}

function onKey(e: KeyboardEvent) {
  // Typing a comment in the panel never moves or zooms the photo.
  const el = e.target as HTMLElement | null;
  if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))) return;
  if (e.key === "+" || e.key === "=") {
    e.preventDefault();
    zoomIn();
    return;
  }
  if (e.key === "-") {
    e.preventDefault();
    zoomOut();
    return;
  }
  if (e.key === "Home" || e.key === "End") {
    e.preventDefault();
    jump(e.key === "Home" ? 0 : total.value - 1);
    return;
  }
  const delta = keyToDelta(e.key, dir.value);
  if (delta) {
    e.preventDefault();
    move(delta);
  }
}

let startX = 0;
let startY = 0;
function onTouchStart(e: TouchEvent) {
  startX = e.changedTouches[0].clientX;
  startY = e.changedTouches[0].clientY;
}
function onTouchEnd(e: TouchEvent) {
  if (zoomed.value) return; // a zoomed photo pans instead
  const dx = e.changedTouches[0].clientX - startX;
  const dy = e.changedTouches[0].clientY - startY;
  move(swipeToDelta(dx, dir.value, dy));
}

let overflow = "";
onMounted(() => {
  dir.value = pageDirection();
  window.addEventListener("keydown", onKey);
  overflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";
  canFullscreen.value = !!document.fullscreenEnabled && typeof dialog.value?.requestFullscreen === "function";
  document.addEventListener("fullscreenchange", onFullscreenChange);
});
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKey);
  document.removeEventListener("fullscreenchange", onFullscreenChange);
  document.body.style.overflow = overflow;
  if (document.fullscreenElement && document.fullscreenElement === dialog.value) {
    void document.exitFullscreen().catch(() => {});
  }
});

const alt = (i: number) => t("post.imageAlt", { n: i + 1, name: props.authorName });
</script>

<template>
  <Teleport to="body">
    <div
      ref="dialog"
      role="dialog"
      aria-modal="true"
      :aria-label="t('post.viewer.title', { name: authorName })"
      tabindex="-1"
      class="fixed inset-0 z-[70] flex bg-gray-950/95 text-white focus:outline-none"
      data-testid="media-theater"
    >
      <div class="relative flex min-w-0 flex-1 flex-col">
        <div class="flex items-center justify-between gap-2 p-3 sm:gap-3 sm:p-4">
          <button
            type="button"
            class="inline-flex h-11 w-11 items-center justify-center rounded-full bg-white/15 transition hover:bg-white/25 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300"
            :aria-label="t('post.viewer.close')"
            @click="emit('close')"
          >
            <X class="h-6 w-6" />
          </button>
          <span
            v-if="many"
            class="rounded-full bg-black/50 px-3 py-1 text-sm font-semibold tabular-nums"
            aria-live="polite"
          >{{ t("post.viewer.counter", { n: index + 1, total }) }}</span>
          <div class="ms-auto flex items-center gap-1.5 sm:gap-2">
            <button
              type="button"
              class="theater-tool"
              :disabled="zoom <= 1"
              :aria-label="t('profileTools.theater.zoomOut')"
              data-testid="theater-zoom-out"
              @click="zoomOut"
            >
              <ZoomOut class="h-5 w-5" aria-hidden="true" />
            </button>
            <span class="sr-only" aria-live="polite" data-testid="theater-zoom-level">{{ t("profileTools.theater.zoomLevel", { pct: Math.round(zoom * 100) }) }}</span>
            <button
              type="button"
              class="theater-tool"
              :disabled="zoom >= MAX_ZOOM"
              :aria-label="t('profileTools.theater.zoomIn')"
              data-testid="theater-zoom-in"
              @click="zoomIn"
            >
              <ZoomIn class="h-5 w-5" aria-hidden="true" />
            </button>
            <button
              v-if="canFullscreen"
              type="button"
              class="theater-tool"
              :aria-label="isFullscreen ? t('profileTools.theater.exitFullscreen') : t('profileTools.theater.fullscreen')"
              :aria-pressed="isFullscreen"
              data-testid="theater-fullscreen"
              @click="toggleFullscreen"
            >
              <component :is="isFullscreen ? Minimize2 : Maximize2" class="h-5 w-5" aria-hidden="true" />
            </button>
            <button
              type="button"
              class="inline-flex h-11 items-center gap-2 rounded-full bg-white/15 px-3 text-sm font-semibold transition hover:bg-white/25 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 disabled:opacity-60 sm:px-4"
              :disabled="downloading"
              data-testid="theater-download"
              @click="download"
            >
              <Download class="h-5 w-5" aria-hidden="true" />
              <span class="sr-only sm:not-sr-only">{{ t("postsFeed.media.download") }}</span>
            </button>
            <button
              v-if="hasPanel"
              type="button"
              class="theater-tool"
              :aria-label="panelOpen ? t('profileTools.theater.hideDetails') : t('profileTools.theater.showDetails')"
              :aria-expanded="panelOpen"
              aria-controls="theater-panel"
              data-testid="theater-panel-toggle"
              @click="panelOpen = !panelOpen"
            >
              <component :is="panelOpen ? PanelRightClose : PanelRightOpen" class="h-5 w-5 rtl:-scale-x-100" aria-hidden="true" />
            </button>
          </div>
        </div>

        <div
          ref="stage"
          class="relative min-h-0 flex-1 select-none overflow-hidden"
          :class="zoomed ? 'cursor-grab touch-none active:cursor-grabbing' : ''"
          :style="{ '--theater-shift': shift }"
          data-testid="theater-stage"
          :data-zoom="zoom"
          @click.self="!zoomed && emit('close')"
          @dblclick="toggleZoom"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="onPointerUp"
          @touchstart.passive="onTouchStart"
          @touchend.passive="onTouchEnd"
        >
          <Transition :name="moved > 0 ? 'theater-next' : 'theater-prev'">
            <div v-if="urls[index]" :key="index" class="pointer-events-none absolute inset-0 flex items-center justify-center">
              <img
                :src="urls[index] ?? undefined"
                :alt="alt(index)"
                class="max-h-full max-w-full object-contain transition-transform duration-150 motion-reduce:transition-none"
                :style="photoStyle"
                draggable="false"
                data-testid="theater-photo"
              />
            </div>
            <span v-else :key="`wait-${index}`" class="absolute inset-0 m-auto h-10 w-10 animate-spin rounded-full border-4 border-white/20 border-t-white" role="status" :aria-label="t('states.loading')" />
          </Transition>

          <!-- Previous sits at the reading start, next at the end; icons mirror in RTL. -->
          <button
            v-if="many"
            type="button"
            class="absolute start-2 top-1/2 inline-flex h-12 w-12 -translate-y-1/2 items-center justify-center rounded-full bg-white/15 transition hover:bg-white/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 active:scale-90 sm:start-4"
            :aria-label="t('post.viewer.prev')"
            @click="move(-1)"
            @dblclick.stop
          >
            <ChevronLeft class="h-7 w-7 rtl:-scale-x-100" />
          </button>
          <button
            v-if="many"
            type="button"
            class="absolute end-2 top-1/2 inline-flex h-12 w-12 -translate-y-1/2 items-center justify-center rounded-full bg-white/15 transition hover:bg-white/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 active:scale-90 sm:end-4"
            :aria-label="t('post.viewer.next')"
            @click="move(1)"
            @dblclick.stop
          >
            <ChevronRight class="h-7 w-7 rtl:-scale-x-100" />
          </button>
        </div>

        <div v-if="many" class="flex shrink-0 justify-center gap-2 overflow-x-auto p-3">
          <button
            v-for="(id, i) in mediaIds"
            :key="id"
            type="button"
            class="h-14 w-14 shrink-0 overflow-hidden rounded-lg ring-2 transition focus:outline-none focus-visible:ring-brand-300"
            :class="i === index ? 'scale-105 ring-white' : 'opacity-50 ring-transparent hover:opacity-100'"
            :aria-label="t('post.viewer.thumb', { n: i + 1 })"
            :aria-current="i === index ? 'true' : undefined"
            @click="jump(i)"
          >
            <img v-if="urls[i]" :src="urls[i] ?? undefined" class="h-full w-full object-cover" alt="" />
            <span v-else class="block h-full w-full bg-white/10" />
          </button>
        </div>
      </div>

      <!-- The post beside the photo (wide screens), or over its lower part (phones). -->
      <aside
        v-if="hasPanel"
        v-show="panelOpen"
        id="theater-panel"
        class="absolute inset-x-0 bottom-0 z-10 flex max-h-[70%] flex-col overflow-hidden rounded-t-2xl bg-white text-gray-900 shadow-2xl lg:static lg:max-h-none lg:w-[360px] lg:shrink-0 lg:rounded-none xl:w-[400px] dark:bg-gray-900 dark:text-gray-100"
        :aria-label="t('profileTools.theater.panel')"
        data-testid="theater-panel"
      >
        <div class="min-h-0 flex-1 overflow-y-auto p-4">
          <slot name="panel" />
        </div>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.theater-tool {
  display: inline-flex;
  height: 2.75rem;
  width: 2.75rem;
  align-items: center;
  justify-content: center;
  border-radius: 9999px;
  background-color: rgb(255 255 255 / 0.15);
  transition: background-color 0.15s ease;
}
.theater-tool:hover:not(:disabled) {
  background-color: rgb(255 255 255 / 0.25);
}
.theater-tool:disabled {
  opacity: 0.4;
}
.theater-tool:focus {
  outline: none;
}
.theater-tool:focus-visible {
  box-shadow: 0 0 0 2px #d8b4fe;
}
.theater-next-enter-active,
.theater-next-leave-active,
.theater-prev-enter-active,
.theater-prev-leave-active {
  transition:
    opacity 0.3s ease,
    transform 0.4s cubic-bezier(0.22, 1, 0.36, 1);
}
/* --theater-shift is +44px in LTR and -44px in RTL, so "next" always comes
   in from the reading end and leaves towards the reading start. */
.theater-next-enter-from,
.theater-prev-leave-to {
  opacity: 0;
  transform: translateX(var(--theater-shift)) scale(0.98);
}
.theater-next-leave-to,
.theater-prev-enter-from {
  opacity: 0;
  transform: translateX(calc(var(--theater-shift) * -1)) scale(0.98);
}
@media (prefers-reduced-motion: reduce) {
  .theater-next-enter-active,
  .theater-next-leave-active,
  .theater-prev-enter-active,
  .theater-prev-leave-active {
    transition: opacity 0.15s linear;
  }
  .theater-next-enter-from,
  .theater-next-leave-to,
  .theater-prev-enter-from,
  .theater-prev-leave-to {
    transform: none;
  }
}
</style>
