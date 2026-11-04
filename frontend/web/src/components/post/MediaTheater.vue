<script setup lang="ts">
import { ChevronLeft, ChevronRight, Download, X } from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { downloadMedia } from "@/lib/downloadMedia";
import { type Direction, keyToDelta, pageDirection, stepIndex, swipeToDelta } from "@/lib/mediaViewer";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { useMediaList } from "@/lib/useMediaList";
import { useToastStore } from "@/stores/toasts";

// Full-screen photo viewer (QTech's "theater", rewritten): the parent keeps the
// open index in the URL; this component only shows it and asks to move.
const props = defineProps<{ mediaIds: string[]; index: number; authorName: string }>();
const emit = defineEmits<{ go: [index: number]; close: [] }>();
const { t } = useI18n();

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
});
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKey);
  document.body.style.overflow = overflow;
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
      class="fixed inset-0 z-[70] flex flex-col bg-gray-950/95 text-white focus:outline-none"
      data-testid="media-theater"
    >
      <div class="flex items-center justify-between gap-3 p-3 sm:p-4">
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
        <button
          type="button"
          class="ms-auto inline-flex h-11 items-center gap-2 rounded-full bg-white/15 px-4 text-sm font-semibold transition hover:bg-white/25 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 disabled:opacity-60"
          :disabled="downloading"
          data-testid="theater-download"
          @click="download"
        >
          <Download class="h-5 w-5" aria-hidden="true" /> {{ t("postsFeed.media.download") }}
        </button>
      </div>

      <div
        class="relative min-h-0 flex-1 select-none overflow-hidden"
        :style="{ '--theater-shift': shift }"
        @click.self="emit('close')"
        @touchstart.passive="onTouchStart"
        @touchend.passive="onTouchEnd"
      >
        <Transition :name="moved > 0 ? 'theater-next' : 'theater-prev'">
          <img
            v-if="urls[index]"
            :key="index"
            :src="urls[index] ?? undefined"
            :alt="alt(index)"
            class="pointer-events-none absolute inset-0 m-auto max-h-full max-w-full object-contain"
            draggable="false"
          />
          <span v-else :key="`wait-${index}`" class="absolute inset-0 m-auto h-10 w-10 animate-spin rounded-full border-4 border-white/20 border-t-white" role="status" :aria-label="t('states.loading')" />
        </Transition>

        <!-- Previous sits at the reading start, next at the end; icons mirror in RTL. -->
        <button
          v-if="many"
          type="button"
          class="absolute start-2 top-1/2 inline-flex h-12 w-12 -translate-y-1/2 items-center justify-center rounded-full bg-white/15 transition hover:bg-white/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 active:scale-90 sm:start-4"
          :aria-label="t('post.viewer.prev')"
          @click="move(-1)"
        >
          <ChevronLeft class="h-7 w-7 rtl:-scale-x-100" />
        </button>
        <button
          v-if="many"
          type="button"
          class="absolute end-2 top-1/2 inline-flex h-12 w-12 -translate-y-1/2 items-center justify-center rounded-full bg-white/15 transition hover:bg-white/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 active:scale-90 sm:end-4"
          :aria-label="t('post.viewer.next')"
          @click="move(1)"
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
  </Teleport>
</template>

<style scoped>
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
