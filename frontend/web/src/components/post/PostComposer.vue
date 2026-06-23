<script setup lang="ts">
import { ImagePlus, X } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { apiError } from "@/lib/api";
import { mediaService } from "@/services/media";
import { postService } from "@/services/post";
import { useAuthStore } from "@/stores/auth";
import type { Post } from "@/types";

const emit = defineEmits<{ created: [post: Post] }>();

const { t } = useI18n();
const auth = useAuthStore();

const body = ref("");
const mediaIds = ref<string[]>([]);
const previews = ref<string[]>([]);
const submitting = ref(false);
const uploading = ref(false);
const error = ref("");

async function onFiles(e: Event) {
  const files = (e.target as HTMLInputElement).files;
  if (!files?.length) return;
  uploading.value = true;
  try {
    for (const file of Array.from(files).slice(0, 4)) {
      const asset = await mediaService.upload(file, "image");
      mediaIds.value.push(asset.id);
      previews.value.push(URL.createObjectURL(file));
    }
  } catch (err) {
    error.value = apiError(err).message;
  } finally {
    uploading.value = false;
  }
}

function removeMedia(i: number) {
  mediaIds.value.splice(i, 1);
  previews.value.splice(i, 1);
}

async function submit() {
  const text = body.value.trim();
  if ((!text && mediaIds.value.length === 0) || submitting.value) return;
  submitting.value = true;
  error.value = "";
  try {
    const post = await postService.create({ body: text, media_ids: mediaIds.value });
    emit("created", post);
    body.value = "";
    mediaIds.value = [];
    previews.value = [];
  } catch (err) {
    error.value = apiError(err).message;
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="card p-4">
    <div class="flex gap-3">
      <UserAvatar
        v-if="auth.profile"
        :name="auth.profile.display_name"
        :media-id="auth.profile.avatar_media_id"
      />
      <div class="flex-1">
        <textarea
          v-model="body"
          class="input min-h-[72px] resize-none"
          :placeholder="t('feed.composerPlaceholder')"
        />

        <div v-if="previews.length" class="mt-2 grid grid-cols-4 gap-2">
          <div v-for="(src, i) in previews" :key="i" class="relative">
            <img :src="src" class="h-20 w-full rounded-md object-cover" alt="" />
            <button
              class="absolute end-1 top-1 rounded-full bg-black/60 p-0.5 text-white"
              @click="removeMedia(i)"
            >
              <X class="h-3 w-3" />
            </button>
          </div>
        </div>

        <p v-if="error" class="mt-2 text-xs text-red-500">{{ error }}</p>

        <div class="mt-2 flex items-center justify-between">
          <label class="btn-ghost cursor-pointer px-2" :class="uploading ? 'opacity-50' : ''">
            <ImagePlus class="h-5 w-5" />
            <input type="file" accept="image/*" multiple class="hidden" @change="onFiles" />
          </label>
          <button class="btn-primary" :disabled="submitting || uploading" @click="submit">
            {{ submitting ? t("feed.posting") : t("feed.post") }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
