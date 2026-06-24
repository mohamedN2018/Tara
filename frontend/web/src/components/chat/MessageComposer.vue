<script setup lang="ts">
import { CornerUpLeft, ImagePlus, Send, X } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import { mediaService } from "@/services/media";
import type { Message } from "@/types";

defineProps<{ replyingTo?: Message | null; replyingToName?: string }>();
const emit = defineEmits<{
  send: [payload: { body: string; mediaId: string | null }];
  typing: [];
  cancelReply: [];
}>();

const { t } = useI18n();
const body = ref("");
const mediaId = ref<string | null>(null);
const preview = ref<string | null>(null);
const uploading = ref(false);

async function onFile(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file) return;
  uploading.value = true;
  try {
    const asset = await mediaService.upload(file, "image");
    mediaId.value = asset.id;
    preview.value = URL.createObjectURL(file);
  } catch {
    // upload may fail; keep composer usable for text
  } finally {
    uploading.value = false;
  }
}

function clearAttachment() {
  mediaId.value = null;
  preview.value = null;
}

function submit() {
  const text = body.value.trim();
  if ((!text && !mediaId.value) || uploading.value) return;
  emit("send", { body: text, mediaId: mediaId.value });
  body.value = "";
  clearAttachment();
}
</script>

<template>
  <div class="border-t border-gray-200 p-3 dark:border-gray-800">
    <div
      v-if="replyingTo"
      class="mb-2 flex items-center gap-2 rounded-lg border-s-2 border-brand-500 bg-gray-50 px-3 py-1.5 text-xs dark:bg-gray-800/60"
    >
      <CornerUpLeft class="h-4 w-4 shrink-0 text-brand-500" />
      <span class="min-w-0 flex-1">
        <span class="font-semibold">{{ t("messages.replyingTo", { name: replyingToName }) }}</span>
        <span class="block truncate text-gray-500">{{ replyingTo.body || `📷 ${t("messages.photo")}` }}</span>
      </span>
      <button class="rounded-full p-0.5 text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700" :aria-label="t('feed.cancel')" @click="emit('cancelReply')">
        <X class="h-4 w-4" />
      </button>
    </div>

    <div v-if="preview" class="mb-2">
      <div class="relative inline-block">
        <img :src="preview" class="h-20 w-20 rounded-lg object-cover" alt="" />
        <button
          class="absolute -end-1.5 -top-1.5 rounded-full bg-black/60 p-0.5 text-white"
          :aria-label="t('friends.delete')"
          @click="clearAttachment"
        >
          <X class="h-3.5 w-3.5" />
        </button>
      </div>
    </div>

    <form class="flex items-center gap-2" @submit.prevent="submit">
      <label
        class="shrink-0 cursor-pointer rounded-full p-2 text-gray-500 transition hover:bg-gray-100 dark:hover:bg-gray-800"
        :class="uploading ? 'opacity-50' : ''"
        :title="t('feed.photo')"
        :aria-label="t('feed.photo')"
      >
        <ImagePlus class="h-5 w-5" />
        <input type="file" accept="image/*" class="hidden" @change="onFile" />
      </label>
      <input
        v-model="body"
        class="input"
        :placeholder="uploading ? t('profile.uploading') : t('messages.placeholder')"
        @input="$emit('typing')"
      />
      <button type="submit" class="btn-primary px-3" :disabled="uploading || (!body.trim() && !mediaId)">
        <Send class="h-4 w-4" />
      </button>
    </form>
  </div>
</template>
