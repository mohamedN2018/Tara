<script setup lang="ts">
// "Create reel" (roadmap 5.8): pick a video, upload it through the shared video
// pipeline, wait for the transcoder, then ask the server whether it can be a
// reel (portrait around 9:16, at most 90 s, measured after transcoding). A
// clip that can't — landscape or longer — is offered as a normal video post
// instead, with the same caption and audience. A cover photo (HEIC too) is
// optional; the server binds it to the reel so it follows the reel's audience.
import { Clapperboard, Film, Globe, ImagePlus, Lock, UserCheck, Users, X } from "lucide-vue-next";
import { computed, onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";

import VideoPlayer from "@/components/media/VideoPlayer.vue";
import StoryDialog from "@/components/stories/StoryDialog.vue";
import { IMAGE_ACCEPT, isHeic } from "@/lib/heic";
import { mediaService } from "@/services/media";
import { postService } from "@/services/post";
import {
  REEL_AUDIENCES,
  REEL_ERRORS,
  REEL_MAX_CAPTION,
  REEL_MAX_SECONDS,
  type Reel,
  type ReelAudience,
  reelsService,
} from "@/services/reels";
import { MAX_VIDEO_BYTES, VIDEO_ACCEPT, videoMime, videoService } from "@/services/video";
import type { Post } from "@/types";
import { useToastStore } from "@/stores/toasts";

const emit = defineEmits<{ close: []; created: [reel: Reel]; postedVideo: [post: Post] }>();
const { t } = useI18n();
const toasts = useToastStore();

type Phase = "pick" | "uploading" | "processing" | "checking" | "ready" | "notReel" | "failed";
const phase = ref<Phase>("pick");
const mediaId = ref<string | null>(null);
const notReelCode = ref<string | null>(null);
const pickError = ref("");
const caption = ref("");
const audience = ref<ReelAudience>("public");
const cover = ref<File | null>(null);
const coverPreview = ref<string | null>(null);
const sending = ref(false);
const videoInput = ref<HTMLInputElement | null>(null);
const coverInput = ref<HTMLInputElement | null>(null);
let abort: AbortController | null = null;

const AUDIENCE_ICONS = { public: Globe, friends: Users, followers: UserCheck, only_me: Lock } as const;
const busy = computed(() => ["uploading", "processing", "checking"].includes(phase.value) || sending.value);
const statusText = computed(() =>
  phase.value === "uploading"
    ? t("reels.create.uploading")
    : phase.value === "processing"
      ? t("reels.create.processing")
      : phase.value === "checking"
        ? t("reels.create.checking")
        : "",
);
const notReelText = computed(() =>
  notReelCode.value === "reel_too_long" ? t("reels.errors.tooLong") : t("reels.errors.notVertical"),
);

function pickVideo() {
  if (!busy.value) videoInput.value?.click();
}

async function onVideo(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  pickError.value = "";
  if (!videoMime(file)) {
    pickError.value = t("video.composer.badType");
    return;
  }
  if (file.size > MAX_VIDEO_BYTES) {
    pickError.value = t("video.composer.tooBig", { size: Math.round(MAX_VIDEO_BYTES / 1024 / 1024) });
    return;
  }
  abort?.abort();
  abort = new AbortController();
  const signal = abort.signal;
  mediaId.value = null;
  notReelCode.value = null;
  phase.value = "uploading";
  try {
    const asset = await videoService.upload(file);
    mediaId.value = asset.id;
    phase.value = "processing";
    const done = await videoService.waitUntilProcessed(asset.id, { signal });
    if (done.status !== "ready") {
      phase.value = "failed";
      return;
    }
    phase.value = "checking";
    const check = await reelsService.eligibility(asset.id);
    if (signal.aborted) return;
    if (check.eligible) phase.value = "ready";
    else if (check.code === "reel_not_vertical" || check.code === "reel_too_long") {
      notReelCode.value = check.code;
      phase.value = "notReel";
    } else phase.value = "failed";
  } catch (err) {
    if ((err as DOMException)?.name === "AbortError") return;
    pickError.value = t(REEL_ERRORS.media_not_owned);
    phase.value = mediaId.value ? "failed" : "pick";
  }
}

function revokeCover() {
  if (coverPreview.value) URL.revokeObjectURL(coverPreview.value);
  coverPreview.value = null;
}
function pickCover() {
  coverInput.value?.click();
}
function onCover(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  revokeCover();
  cover.value = file;
  coverPreview.value = isHeic(file) ? null : URL.createObjectURL(file);
}
function removeCover() {
  revokeCover();
  cover.value = null;
}

async function share() {
  if (phase.value !== "ready" || !mediaId.value || sending.value) return;
  sending.value = true;
  try {
    let coverId: string | null = null;
    if (cover.value) coverId = (await mediaService.upload(cover.value, "image", "private")).id;
    const reel = await reelsService.create({
      media_id: mediaId.value,
      cover_media_id: coverId,
      caption: caption.value.trim(),
      audience: audience.value,
    });
    toasts.success(t("reels.create.shared"));
    emit("created", reel); // the parent opens it, which closes this dialog
  } catch (err) {
    toasts.error(err, REEL_ERRORS);
  } finally {
    sending.value = false;
  }
}

async function postAsVideo() {
  if (phase.value !== "notReel" || !mediaId.value || sending.value) return;
  sending.value = true;
  try {
    const post = await postService.create({
      type: "video",
      media_ids: [mediaId.value],
      body: caption.value.trim(),
      audience: audience.value,
    });
    toasts.success(t("reels.create.postedAsVideo"));
    emit("postedVideo", post); // the parent opens the post, which closes this dialog
  } catch (err) {
    toasts.error(err);
  } finally {
    sending.value = false;
  }
}

function close() {
  if (!sending.value) emit("close");
}

onBeforeUnmount(() => {
  abort?.abort();
  revokeCover();
});
</script>

<template>
  <StoryDialog :title="t('reels.create.title')" :close-label="t('reels.close')" wide @close="close">
    <input ref="videoInput" type="file" class="hidden" tabindex="-1" aria-hidden="true" :accept="VIDEO_ACCEPT" data-testid="reel-video-input" @change="onVideo" />
    <input ref="coverInput" type="file" class="hidden" tabindex="-1" aria-hidden="true" :accept="IMAGE_ACCEPT" data-testid="reel-cover-input" @change="onCover" />

    <div class="grid min-h-0 gap-4 overflow-y-auto sm:grid-cols-[220px_minmax(0,1fr)]" data-testid="reel-create" :data-phase="phase">
      <!-- The video -->
      <div>
        <button
          v-if="phase === 'pick'"
          type="button"
          class="flex aspect-[9/16] w-full flex-col items-center justify-center gap-3 rounded-2xl bg-gradient-to-br from-accent-500 via-brand-600 to-brand-900 p-4 text-center text-white shadow-glow transition hover:brightness-110 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-300"
          data-testid="reel-pick"
          @click="pickVideo"
        >
          <span class="flex h-12 w-12 items-center justify-center rounded-full bg-white/20"><Clapperboard class="h-6 w-6" aria-hidden="true" /></span>
          <span class="text-base font-bold">{{ t("reels.create.pick") }}</span>
          <span class="text-xs text-white/85">{{ t("reels.create.pickHint", { max: REEL_MAX_SECONDS }) }}</span>
        </button>
        <div v-else class="mx-auto w-48 sm:w-full">
          <div v-if="busy && !mediaId" class="flex aspect-[9/16] w-full items-center justify-center rounded-2xl bg-gray-900" />
          <VideoPlayer v-if="mediaId" :media-id="mediaId" class="!mt-0" :label="t('reels.create.title')" />
          <button type="button" class="btn-ghost mt-2 w-full text-sm" :disabled="busy" @click="pickVideo">
            <Film class="h-4 w-4" aria-hidden="true" /> {{ t("reels.create.changeVideo") }}
          </button>
        </div>
        <p v-if="statusText" class="mt-2 flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300" role="status" data-testid="reel-create-status">
          <span class="h-4 w-4 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" aria-hidden="true" />
          {{ statusText }}
        </p>
        <p v-if="phase === 'ready'" class="mt-2 text-sm text-emerald-700 dark:text-emerald-400" role="status">{{ t("reels.create.ready") }}</p>
        <p v-if="phase === 'failed'" class="mt-2 text-sm text-red-600 dark:text-red-400" role="alert">{{ t("reels.create.failed") }}</p>
        <p v-if="pickError" class="mt-2 text-sm text-red-600 dark:text-red-400" role="alert">{{ pickError }}</p>
      </div>

      <!-- Details -->
      <div class="space-y-4">
        <div v-if="phase === 'notReel'" class="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100" role="alert" data-testid="reel-not-reel">
          <p class="font-semibold">{{ t("reels.create.notReel") }}</p>
          <p class="mt-1">{{ notReelText }}</p>
        </div>

        <label class="block">
          <span class="mb-1 block text-sm font-semibold">{{ t("reels.create.caption") }}</span>
          <textarea
            v-model="caption"
            rows="3"
            dir="auto"
            class="input resize-none"
            :maxlength="REEL_MAX_CAPTION"
            :placeholder="t('reels.create.captionPlaceholder')"
            data-testid="reel-caption-input"
          />
        </label>

        <div v-if="phase !== 'notReel'">
          <p class="mb-1 text-sm font-semibold">{{ t("reels.create.cover") }}</p>
          <div class="flex items-center gap-3">
            <div class="relative flex aspect-[9/16] w-14 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-800">
              <img v-if="coverPreview" :src="coverPreview" alt="" class="h-full w-full object-cover" />
              <ImagePlus v-else class="h-5 w-5 text-gray-500" aria-hidden="true" />
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap gap-2">
                <button type="button" class="btn-outline text-sm" :disabled="sending" data-testid="reel-cover-pick" @click="pickCover">
                  {{ cover ? t("reels.create.changeCover") : t("reels.create.addCover") }}
                </button>
                <button v-if="cover" type="button" class="btn-ghost text-sm" :disabled="sending" @click="removeCover">
                  <X class="h-4 w-4" aria-hidden="true" /> {{ t("reels.create.removeCover") }}
                </button>
              </div>
              <p class="mt-1 text-xs text-gray-600 dark:text-gray-300">{{ cover && !coverPreview ? t("reels.create.coverHeic") : t("reels.create.coverHint") }}</p>
            </div>
          </div>
        </div>

        <fieldset>
          <legend class="mb-2 text-sm font-semibold">{{ t("reels.create.audience") }}</legend>
          <div class="grid grid-cols-2 gap-1.5">
            <label
              v-for="a in REEL_AUDIENCES"
              :key="a"
              class="flex cursor-pointer items-center gap-2 rounded-xl border border-gray-200 px-3 py-2 text-sm font-semibold transition has-[:checked]:border-brand-500 has-[:checked]:bg-brand-50 dark:border-gray-800 dark:has-[:checked]:bg-brand-950/50"
            >
              <input v-model="audience" type="radio" name="reel-audience" :value="a" class="h-4 w-4 accent-brand-600" :data-testid="`reel-audience-${a}`" />
              <component :is="AUDIENCE_ICONS[a]" class="h-4 w-4 text-gray-600 dark:text-gray-300" aria-hidden="true" />
              {{ t(`reels.create.audiences.${a}`) }}
            </label>
          </div>
        </fieldset>

        <div class="flex justify-end gap-2 pt-1">
          <button type="button" class="btn-ghost" :disabled="sending" @click="close">{{ t("reels.close") }}</button>
          <button v-if="phase === 'notReel'" type="button" class="btn-primary" :disabled="sending" data-testid="reel-post-as-video" @click="postAsVideo">
            {{ sending ? t("reels.create.postingAsVideo") : t("reels.create.postAsVideo") }}
          </button>
          <button v-else type="button" class="btn-primary" :disabled="phase !== 'ready' || sending" data-testid="reel-share-submit" @click="share">
            {{ sending ? t("reels.create.sharing") : t("reels.create.share") }}
          </button>
        </div>
      </div>
    </div>
  </StoryDialog>
</template>
