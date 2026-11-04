<script setup lang="ts">
import { Globe2, ImagePlus, X } from "lucide-vue-next";
import { computed, onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { IMAGE_ACCEPT } from "@/lib/heic";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { mediaService } from "@/services/media";
import { type Page, pageService } from "@/services/pages";
import { useToastStore } from "@/stores/toasts";
import type { Post } from "@/types";

// "Create post" as a page: text and up to 10 photos, always public and
// published now (the post service refuses drafts, tags and groups for pages,
// and asks profile whether this account may post for the page).
const props = defineProps<{ page: Page }>();
const emit = defineEmits<{ close: []; posted: [post: Post] }>();

const MAX_PHOTOS = 10;
const { t } = useI18n();
const toasts = useToastStore();
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);
const body = ref("");
const photos = ref<{ file: File; url: string }[]>([]);
const sending = ref(false);
useEscapeKey(
  computed(() => true),
  () => !sending.value && emit("close"),
);
const canSend = computed(() => !sending.value && (body.value.trim().length > 0 || photos.value.length > 0));

function add(e: Event) {
  const input = e.target as HTMLInputElement;
  const picked = [...(input.files ?? [])].slice(0, MAX_PHOTOS - photos.value.length);
  input.value = "";
  photos.value.push(...picked.map((file) => ({ file, url: URL.createObjectURL(file) })));
}
function drop(i: number) {
  URL.revokeObjectURL(photos.value[i].url);
  photos.value.splice(i, 1);
}
onBeforeUnmount(() => photos.value.forEach((p) => URL.revokeObjectURL(p.url)));

async function send() {
  if (!canSend.value) return;
  sending.value = true;
  try {
    const assets = await Promise.all(photos.value.map((p) => mediaService.upload(p.file, "image")));
    const post = await pageService.createPost(props.page.id, { body: body.value.trim(), media_ids: assets.map((a) => a.id) });
    toasts.success(t("pageHub.posts.published", { name: props.page.name }));
    emit("posted", post);
    emit("close");
  } catch (e) {
    toasts.error(e);
  } finally {
    sending.value = false;
  }
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-50 flex items-end justify-center bg-gray-950/60 backdrop-blur-sm sm:items-center sm:p-4">
      <div class="fixed inset-0" @click="!sending && emit('close')" />
      <form
        ref="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="page-composer-title"
        tabindex="-1"
        class="card relative z-10 max-h-[92vh] w-full animate-pop-in overflow-y-auto rounded-b-none rounded-t-2xl shadow-pop sm:max-w-lg sm:rounded-2xl"
        data-testid="page-composer"
        @submit.prevent="send"
      >
        <div class="relative border-b border-gray-200 p-4 text-center dark:border-gray-800">
          <h2 id="page-composer-title" class="text-lg font-bold">{{ t("pageHub.posts.composerTitle") }}</h2>
          <button type="button" class="icon-btn absolute end-3 top-3" :aria-label="t('market.close')" @click="emit('close')">
            <X class="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <div class="space-y-3 p-4">
          <div class="flex items-center gap-3">
            <UserAvatar :name="page.name" :media-id="page.avatar_media_id" :size="44" />
            <div class="min-w-0">
              <p class="truncate font-semibold" dir="auto">{{ t("pageHub.posts.postingAs", { name: page.name }) }}</p>
              <p class="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
                <Globe2 class="h-3.5 w-3.5" aria-hidden="true" /> {{ t("pageHub.posts.publicNote") }}
              </p>
            </div>
          </div>
          <label class="sr-only" for="page-composer-body">{{ t("pageHub.posts.body") }}</label>
          <textarea
            id="page-composer-body"
            v-model="body"
            class="min-h-32 w-full resize-none bg-transparent text-lg outline-none placeholder:text-gray-400"
            dir="auto"
            maxlength="5000"
            :placeholder="t('pageHub.posts.whatsNew', { name: page.name })"
            data-testid="page-composer-body"
          />
          <ul v-if="photos.length" class="grid grid-cols-3 gap-2">
            <li v-for="(p, i) in photos" :key="p.url" class="relative aspect-square overflow-hidden rounded-lg">
              <img :src="p.url" alt="" class="h-full w-full object-cover" />
              <button
                type="button"
                class="absolute end-1 top-1 rounded-full bg-gray-950/60 p-1 text-white"
                :aria-label="t('pageHub.posts.removePhoto', { n: i + 1 })"
                @click="drop(i)"
              >
                <X class="h-4 w-4" aria-hidden="true" />
              </button>
            </li>
          </ul>
          <div class="flex items-center justify-between rounded-xl border border-gray-200 p-2 dark:border-gray-800">
            <span class="px-2 text-sm font-semibold">{{ t("pageHub.posts.addPhotos") }}</span>
            <label class="icon-btn cursor-pointer text-emerald-600" :class="photos.length >= MAX_PHOTOS ? 'pointer-events-none opacity-50' : ''">
              <ImagePlus class="h-5 w-5" aria-hidden="true" />
              <span class="sr-only">{{ t("pageHub.posts.addPhotos") }}</span>
              <input type="file" multiple :accept="IMAGE_ACCEPT" class="sr-only" data-testid="page-composer-photos" @change="add" />
            </label>
          </div>
          <button type="submit" class="btn-primary w-full" :disabled="!canSend" data-testid="page-composer-submit">
            {{ sending ? t("states.loading") : t("pageHub.posts.publish") }}
          </button>
        </div>
      </form>
    </div>
  </Teleport>
</template>
