<script setup lang="ts">
// "Add photos · n/10": the first block of the listing form. Each file goes
// through the media service's presigned upload; the ids, in order, become the
// listing's `media_ids` (the first one is the cover). Drag to reorder, or use
// the arrow buttons (keyboard); x removes a photo.
import { ChevronLeft, ChevronRight, ImagePlus, Loader2, X } from "lucide-vue-next";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { mediaErrorKey } from "@/lib/errors";
import { mediaService } from "@/services/media";
import { MAX_LISTING_PHOTOS } from "@/services/marketplace";

const props = withDefaults(defineProps<{ modelValue: string[]; disabled?: boolean }>(), { disabled: false });
const emit = defineEmits<{ "update:modelValue": [ids: string[]]; "update:busy": [busy: boolean] }>();

const { t } = useI18n();
const input = ref<HTMLInputElement | null>(null);
const uploading = ref(0);
const error = ref("");
// Preview per media id: a local blob for a fresh upload, the resolved URL otherwise.
const previews = ref<Record<string, string>>({});
const blobs: string[] = [];

// A local copy, so uploads finishing before the parent re-renders all land.
const ids = ref<string[]>([...props.modelValue]);
watch(
  () => props.modelValue,
  (v) => (ids.value = [...v]),
);
function set(next: string[]) {
  ids.value = next;
  emit("update:modelValue", next);
}
const full = computed(() => ids.value.length + uploading.value >= MAX_LISTING_PHOTOS);

watch(
  ids,
  async (list) => {
    for (const id of list) {
      if (previews.value[id]) continue;
      const url = await mediaService.resolveUrl(id);
      if (url) previews.value = { ...previews.value, [id]: url };
    }
  },
  { immediate: true },
);
watch(uploading, (n) => emit("update:busy", n > 0));
onBeforeUnmount(() => blobs.forEach((b) => URL.revokeObjectURL(b)));

function pick() {
  if (!props.disabled && !full.value) input.value?.click();
}

async function onFiles(event: Event) {
  const el = event.target as HTMLInputElement;
  const files = Array.from(el.files ?? []);
  el.value = "";
  error.value = "";
  const room = MAX_LISTING_PHOTOS - ids.value.length - uploading.value;
  if (files.length > room) error.value = t("commerce.photos.errors.tooMany", { max: MAX_LISTING_PHOTOS });
  for (const file of files.slice(0, Math.max(room, 0))) {
    if (!file.type.startsWith("image/") && !/\.(heic|heif)$/i.test(file.name)) {
      error.value = t("commerce.photos.errors.kind");
      continue;
    }
    uploading.value += 1;
    try {
      const asset = await mediaService.upload(file, "image");
      const blob = URL.createObjectURL(file);
      blobs.push(blob);
      previews.value = { ...previews.value, [asset.id]: blob };
      set([...ids.value, asset.id]);
    } catch (e) {
      error.value = t(mediaErrorKey(e) ?? "commerce.photos.errors.upload");
    } finally {
      uploading.value -= 1;
    }
  }
}

function remove(i: number) {
  set(ids.value.filter((_, j) => j !== i));
}

function move(from: number, to: number) {
  if (to < 0 || to >= ids.value.length || from === to) return;
  const next = [...ids.value];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  set(next);
}

const dragFrom = ref<number | null>(null);
function onDrop(to: number) {
  if (dragFrom.value !== null) move(dragFrom.value, to);
  dragFrom.value = null;
}
</script>

<template>
  <fieldset class="space-y-2" data-testid="listing-photos">
    <legend class="flex w-full items-center justify-between text-sm font-medium">
      <span>{{ t("commerce.photos.title") }}</span>
      <span class="text-xs font-normal text-gray-500 dark:text-gray-400" dir="ltr">
        {{ ids.length }}/{{ MAX_LISTING_PHOTOS }}
      </span>
    </legend>
    <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("commerce.photos.hint") }}</p>

    <ul class="grid grid-cols-3 gap-2 sm:grid-cols-4" :aria-label="t('commerce.photos.title')">
      <li
        v-for="(id, i) in ids"
        :key="id"
        class="group relative aspect-square overflow-hidden rounded-xl border border-gray-200 bg-gray-100 dark:border-gray-700 dark:bg-gray-800"
        :draggable="!disabled"
        data-testid="listing-photo"
        @dragstart="dragFrom = i"
        @dragover.prevent
        @drop.prevent="onDrop(i)"
      >
        <img v-if="previews[id]" :src="previews[id]" class="h-full w-full object-cover" :alt="t('commerce.photos.alt', { n: i + 1 })" />
        <span v-if="i === 0" class="absolute bottom-1 start-1 rounded-full bg-gray-900/80 px-2 py-0.5 text-[10px] font-semibold text-white">
          {{ t("commerce.photos.cover") }}
        </span>
        <button
          v-if="!disabled"
          type="button"
          class="absolute top-1 end-1 rounded-full bg-gray-900/80 p-1 text-white hover:bg-gray-900"
          :aria-label="t('commerce.photos.remove', { n: i + 1 })"
          @click="remove(i)"
        >
          <X class="h-3.5 w-3.5" aria-hidden="true" />
        </button>
        <div v-if="!disabled && ids.length > 1" class="absolute bottom-1 end-1 flex gap-1">
          <button
            v-if="i > 0"
            type="button"
            class="rounded-full bg-gray-900/80 p-1 text-white hover:bg-gray-900"
            :aria-label="t('commerce.photos.earlier', { n: i + 1 })"
            @click="move(i, i - 1)"
          >
            <ChevronLeft class="h-3.5 w-3.5 rtl:-scale-x-100" aria-hidden="true" />
          </button>
          <button
            v-if="i < ids.length - 1"
            type="button"
            class="rounded-full bg-gray-900/80 p-1 text-white hover:bg-gray-900"
            :aria-label="t('commerce.photos.later', { n: i + 1 })"
            @click="move(i, i + 1)"
          >
            <ChevronRight class="h-3.5 w-3.5 rtl:-scale-x-100" aria-hidden="true" />
          </button>
        </div>
      </li>
      <li
        v-for="n in uploading"
        :key="`up-${n}`"
        class="flex aspect-square flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-gray-300 text-xs text-gray-500 dark:border-gray-700 dark:text-gray-400"
        role="status"
      >
        <Loader2 class="h-5 w-5 animate-spin" aria-hidden="true" />
        {{ t("commerce.photos.uploading") }}
      </li>
      <li v-if="!disabled && !full">
        <button
          type="button"
          class="flex aspect-square w-full flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed border-brand-300 bg-brand-50/60 text-xs font-medium text-brand-700 transition hover:bg-brand-50 dark:border-brand-800 dark:bg-brand-950/30 dark:text-brand-200"
          data-testid="add-photos"
          @click="pick"
        >
          <ImagePlus class="h-6 w-6" aria-hidden="true" />
          {{ t("commerce.photos.add") }}
        </button>
      </li>
    </ul>
    <input
      ref="input"
      type="file"
      class="sr-only"
      accept="image/*,.heic,.heif"
      multiple
      tabindex="-1"
      aria-hidden="true"
      data-testid="listing-photo-input"
      @change="onFiles"
    />
    <p v-if="error" class="text-xs text-red-600 dark:text-red-400" role="alert">{{ error }}</p>
  </fieldset>
</template>
