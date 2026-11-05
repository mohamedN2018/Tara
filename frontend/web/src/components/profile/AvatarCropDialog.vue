<script setup lang="ts">
import { X, ZoomIn, ZoomOut } from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { clampCropOffset, cropScale, cropSourceRect, type Point } from "@/lib/photoFrame";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";

// Crop and zoom a new profile picture before it is uploaded (plan 08). Runs in
// the browser on a canvas: the square shown in the circle is drawn at 720 px and
// uploaded as a new image. A photo the browser can't draw (HEIC, or a picked
// photo whose storage refuses cross-origin reads) is used as it is instead.
const props = withDefaults(defineProps<{ file?: File | null; src?: string | null; busy?: boolean }>(), {
  file: null,
  src: null,
  busy: false,
});
const emit = defineEmits<{ close: []; cropped: [file: File]; "as-is": [] }>();
const { t } = useI18n();

const VIEW = 288;
const OUTPUT = 720;

const objectUrl = ref<string | null>(null);
const natural = ref({ width: 0, height: 0 });
const ready = ref(false);
const unusable = ref(false);
const zoom = ref(1);
const offset = ref<Point>({ x: 0, y: 0 });
const img = ref<HTMLImageElement | null>(null);

async function prepare() {
  try {
    if (props.file) {
      objectUrl.value = URL.createObjectURL(props.file);
    } else if (props.src) {
      // Read the picked photo as a blob so the canvas may export it.
      const res = await fetch(props.src, { mode: "cors", credentials: "omit" });
      if (!res.ok) throw new Error(String(res.status));
      objectUrl.value = URL.createObjectURL(await res.blob());
    } else {
      unusable.value = true;
    }
  } catch {
    unusable.value = true;
  }
}
function onLoad() {
  const el = img.value;
  if (!el?.naturalWidth) {
    unusable.value = true;
    return;
  }
  natural.value = { width: el.naturalWidth, height: el.naturalHeight };
  ready.value = true;
}
onMounted(() => void prepare());
onBeforeUnmount(() => {
  if (objectUrl.value) URL.revokeObjectURL(objectUrl.value);
});

const scale = computed(() => cropScale(zoom.value, natural.value, VIEW));
const photoStyle = computed(() => {
  const w = natural.value.width * scale.value;
  const h = natural.value.height * scale.value;
  return {
    width: `${w}px`,
    height: `${h}px`,
    left: `${VIEW / 2 + offset.value.x - w / 2}px`,
    top: `${VIEW / 2 + offset.value.y - h / 2}px`,
  };
});
function setZoom(z: number) {
  zoom.value = Math.min(3, Math.max(1, z));
  offset.value = clampCropOffset(offset.value, zoom.value, natural.value, VIEW);
}
function nudge(dx: number, dy: number) {
  offset.value = clampCropOffset({ x: offset.value.x + dx, y: offset.value.y + dy }, zoom.value, natural.value, VIEW);
}

let drag: { x: number; y: number; from: Point } | null = null;
function onPointerDown(e: PointerEvent) {
  if (!ready.value) return;
  drag = { x: e.clientX, y: e.clientY, from: { ...offset.value } };
  (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
}
function onPointerMove(e: PointerEvent) {
  if (!drag) return;
  offset.value = clampCropOffset(
    { x: drag.from.x + e.clientX - drag.x, y: drag.from.y + e.clientY - drag.y },
    zoom.value,
    natural.value,
    VIEW,
  );
}
function onPointerUp() {
  drag = null;
}
function onKey(e: KeyboardEvent) {
  const step = e.shiftKey ? 32 : 8;
  const moves: Record<string, [number, number]> = {
    ArrowLeft: [-step, 0],
    ArrowRight: [step, 0],
    ArrowUp: [0, -step],
    ArrowDown: [0, step],
  };
  const m = moves[e.key];
  if (m) {
    e.preventDefault();
    nudge(m[0], m[1]);
  } else if (e.key === "+" || e.key === "=") {
    e.preventDefault();
    setZoom(zoom.value + 0.25);
  } else if (e.key === "-") {
    e.preventDefault();
    setZoom(zoom.value - 0.25);
  }
}

const saving = ref(false);
async function save() {
  if (props.busy || saving.value) return;
  if (!ready.value || !img.value) {
    emit("as-is");
    return;
  }
  saving.value = true;
  try {
    const { sx, sy, size } = cropSourceRect(offset.value, zoom.value, natural.value, VIEW);
    const canvas = document.createElement("canvas");
    canvas.width = OUTPUT;
    canvas.height = OUTPUT;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("no canvas");
    ctx.drawImage(img.value, sx, sy, size, size, 0, 0, OUTPUT, OUTPUT);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
    if (!blob) throw new Error("no blob");
    emit("cropped", new File([blob], "avatar.jpg", { type: "image/jpeg" }));
  } catch {
    // A tainted canvas or an old browser: upload the photo as it is.
    emit("as-is");
  } finally {
    saving.value = false;
  }
}

const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);
useEscapeKey(ref(true), () => emit("close"));
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[75] flex items-end justify-center bg-gray-950/60 backdrop-blur-sm sm:items-center sm:p-4">
      <div class="fixed inset-0" @click="emit('close')" />
      <div
        ref="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="avatar-crop-title"
        tabindex="-1"
        class="card relative z-10 w-full rounded-b-none p-4 shadow-pop sm:max-w-md sm:rounded-2xl sm:p-5"
        data-testid="avatar-crop"
      >
        <div class="mb-3 flex items-center justify-between gap-2">
          <h2 id="avatar-crop-title" class="text-lg font-bold">{{ t("profileTools.avatar.cropTitle") }}</h2>
          <button type="button" class="icon-btn h-9 w-9" :aria-label="t('profileTools.avatar.cancel')" @click="emit('close')">
            <X class="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <div class="flex flex-col items-center gap-3">
          <!-- Geometry is physical (left/top), so it is the same in RTL and LTR. -->
          <div
            dir="ltr"
            class="relative touch-none select-none overflow-hidden rounded-xl bg-gray-900 focus:outline-none focus-visible:ring-4 focus-visible:ring-brand-400"
            :class="ready ? 'cursor-grab active:cursor-grabbing' : ''"
            :style="{ width: `${VIEW}px`, height: `${VIEW}px` }"
            tabindex="0"
            role="img"
            :aria-label="t('profileTools.avatar.preview')"
            data-testid="avatar-crop-frame"
            @pointerdown="onPointerDown"
            @pointermove="onPointerMove"
            @pointerup="onPointerUp"
            @pointercancel="onPointerUp"
            @keydown="onKey"
          >
            <img
              v-if="objectUrl"
              ref="img"
              :src="objectUrl"
              alt=""
              class="pointer-events-none absolute max-w-none"
              :class="ready ? '' : 'invisible'"
              :style="ready ? photoStyle : undefined"
              draggable="false"
              @load="onLoad"
              @error="unusable = true"
            />
            <!-- The circle that becomes the profile picture. -->
            <span class="pointer-events-none absolute inset-0 rounded-full shadow-[0_0_0_999px_rgba(3,7,18,0.55)] ring-2 ring-white/80" aria-hidden="true" />
            <span v-if="!ready && !unusable" class="absolute inset-0 m-auto h-8 w-8 animate-spin rounded-full border-4 border-white/20 border-t-white" role="status" :aria-label="t('states.loading')" />
          </div>
          <p v-if="unusable" class="text-center text-sm text-amber-700 dark:text-amber-300" role="status" data-testid="avatar-crop-as-is">{{ t("profileTools.avatar.asIs") }}</p>
          <p v-else class="text-center text-sm text-gray-600 dark:text-gray-400">{{ t("profileTools.avatar.dragHint") }}</p>

          <label class="flex w-full items-center gap-3" :class="ready ? '' : 'opacity-50'">
            <ZoomOut class="h-5 w-5 shrink-0 text-gray-600 dark:text-gray-300" aria-hidden="true" />
            <span class="sr-only">{{ t("profileTools.avatar.zoom") }}</span>
            <input
              type="range"
              min="1"
              max="3"
              step="0.01"
              class="w-full accent-brand-600"
              :value="zoom"
              :disabled="!ready"
              data-testid="avatar-crop-zoom"
              @input="setZoom(Number(($event.target as HTMLInputElement).value))"
            />
            <ZoomIn class="h-5 w-5 shrink-0 text-gray-600 dark:text-gray-300" aria-hidden="true" />
          </label>
        </div>

        <div class="mt-4 flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="emit('close')">{{ t("profileTools.avatar.cancel") }}</button>
          <button type="button" class="btn-primary" :disabled="busy || saving || (!ready && !unusable)" data-testid="avatar-crop-save" @click="save">
            {{ busy || saving ? t("profile.uploading") : t("profileTools.avatar.save") }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
