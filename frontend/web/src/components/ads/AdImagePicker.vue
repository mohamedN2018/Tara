<script setup lang="ts">
// One image for an ad: uploaded through the media service, sent as `media_id`.
// The ads service checks it is the advertiser's own, finished image.
import { ImagePlus, Loader2, X } from "lucide-vue-next";
import { onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { mediaErrorKey } from "@/lib/errors";
import { mediaService } from "@/services/media";

const props = withDefaults(defineProps<{ modelValue?: string | null; disabled?: boolean; inputId: string }>(), {
  modelValue: null,
  disabled: false,
});
const emit = defineEmits<{ "update:modelValue": [id: string | null]; "update:busy": [busy: boolean] }>();

const { t } = useI18n();
const input = ref<HTMLInputElement | null>(null);
const preview = ref<string | null>(null);
const uploading = ref(false);
const error = ref("");
let blob: string | null = null;

watch(
  () => props.modelValue,
  async (id) => {
    if (!id) preview.value = null;
    else if (!blob) preview.value = await mediaService.resolveUrl(id);
  },
  { immediate: true },
);
watch(uploading, (b) => emit("update:busy", b));
onBeforeUnmount(() => blob && URL.revokeObjectURL(blob));

async function onFile(event: Event) {
  const el = event.target as HTMLInputElement;
  const file = el.files?.[0];
  el.value = "";
  if (!file) return;
  error.value = "";
  uploading.value = true;
  try {
    const asset = await mediaService.upload(file, "image");
    if (blob) URL.revokeObjectURL(blob);
    blob = URL.createObjectURL(file);
    preview.value = blob;
    emit("update:modelValue", asset.id);
  } catch (e) {
    error.value = t(mediaErrorKey(e) ?? "commerce.photos.errors.upload");
  } finally {
    uploading.value = false;
  }
}

function clear() {
  if (blob) URL.revokeObjectURL(blob);
  blob = null;
  emit("update:modelValue", null);
}
</script>

<template>
  <div class="space-y-1" data-testid="ad-image">
    <div v-if="modelValue && preview" class="relative overflow-hidden rounded-xl border border-gray-200 dark:border-gray-700">
      <img :src="preview" class="aspect-[1.91/1] w-full object-cover" :alt="t('commerce.ads.imageAlt')" />
      <button
        v-if="!disabled"
        type="button"
        class="absolute top-2 end-2 rounded-full bg-gray-900/80 p-1 text-white hover:bg-gray-900"
        :aria-label="t('commerce.ads.removeImage')"
        @click="clear"
      >
        <X class="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
    <label
      v-else
      :for="inputId"
      class="flex cursor-pointer items-center justify-center gap-2 rounded-xl border-2 border-dashed border-gray-300 px-3 py-4 text-sm text-gray-600 transition hover:border-brand-400 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-400 dark:border-gray-700 dark:text-gray-300"
    >
      <Loader2 v-if="uploading" class="h-4 w-4 animate-spin" aria-hidden="true" />
      <ImagePlus v-else class="h-4 w-4" aria-hidden="true" />
      {{ uploading ? t("commerce.photos.uploading") : t("commerce.ads.addImage") }}
      <input
        :id="inputId"
        ref="input"
        type="file"
        class="sr-only"
        accept="image/*,.heic,.heif"
        :disabled="disabled || uploading"
        @change="onFile"
      />
    </label>
    <p v-if="error" class="text-xs text-red-600 dark:text-red-400" role="alert">{{ error }}</p>
  </div>
</template>
