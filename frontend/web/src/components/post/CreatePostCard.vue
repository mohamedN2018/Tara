<script setup lang="ts">
import { BarChart3, ChevronDown, Globe, ImagePlus, Lock, Plus, UserCheck, Users, X } from "lucide-vue-next";
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import MentionField from "@/components/post/MentionField.vue";
import { errorMessage } from "@/lib/errors";
import { IMAGE_ACCEPT, isHeic, toUploadable } from "@/lib/heic";
import { mediaService } from "@/services/media";
import { COMMENT_POLICIES, type CommentPolicy, postService } from "@/services/post";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";
import type { Post } from "@/types";

const emit = defineEmits<{ created: [post: Post] }>();

const { t } = useI18n();
const auth = useAuthStore();

const expanded = ref(false);
const body = ref("");
const mediaIds = ref<string[]>([]);
const previews = ref<string[]>([]);
const submitting = ref(false);
const uploading = ref(false);
const converting = ref(false);
const error = ref("");
// The post service accepts at most 10 media per post (MAX_MEDIA_PER_POST).
const MAX_PHOTOS = 10;
const commentPolicy = ref<CommentPolicy>("everyone");
const POLICY_LABEL: Record<CommentPolicy, string> = {
  everyone: "post.commentPolicyEveryone",
  friends: "post.commentPolicyFriends",
  off: "post.commentPolicyOff",
};

const AUDIENCES = [
  { v: "public", icon: Globe, label: "feed.audiencePublic" },
  { v: "friends", icon: Users, label: "feed.audienceFriends" },
  { v: "followers", icon: UserCheck, label: "feed.audienceFollowers" },
  { v: "only_me", icon: Lock, label: "feed.audienceOnlyMe" },
];
const audience = ref("public");
const showAudience = ref(false);
const currentAudience = computed(() => AUDIENCES.find((a) => a.v === audience.value) ?? AUDIENCES[0]);

// Poll: the post body is the question.
const POLL_MAX_OPTIONS = 6;
const pollOpen = ref(false);
const pollOptions = ref(["", ""]);
const pollHours = ref<number | null>(null);
const POLL_DURATIONS = [
  { hours: null, label: "feed.pollNoEnd" },
  { hours: 24, label: "feed.pollDay" },
  { hours: 72, label: "feed.pollThreeDays" },
  { hours: 168, label: "feed.pollWeek" },
];
const filledOptions = computed(() => pollOptions.value.map((o) => o.trim()).filter(Boolean));
const pollReady = computed(() => filledOptions.value.length >= 2 && !!body.value.trim());

// "Create post" shortcuts (sidebar, mobile bar) open this composer.
const ui = useUiStore();
const root = ref<HTMLElement | null>(null);
watch(
  () => ui.composeRequested,
  async (requested) => {
    if (!requested) return;
    ui.composeRequested = false;
    expanded.value = true;
    await nextTick();
    root.value?.scrollIntoView({ behavior: "smooth", block: "center" });
    root.value?.querySelector<HTMLElement>("textarea, input:not([type=file])")?.focus();
  },
  { immediate: true },
);

const authorName = () => auth.profile?.display_name || auth.account?.email?.split("@")[0] || "?";

async function onFiles(e: Event) {
  const input = e.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  input.value = ""; // picking the same file again still fires `change`
  if (!files.length) return;
  const room = MAX_PHOTOS - mediaIds.value.length;
  uploading.value = true;
  error.value = room < files.length ? t("feed.tooManyPhotos", { max: MAX_PHOTOS }) : "";
  try {
    for (const picked of files.slice(0, Math.max(0, room))) {
      let file = picked;
      if (isHeic(picked)) {
        // iPhone photos: converted to JPEG in a lazily loaded chunk.
        converting.value = true;
        try {
          file = await toUploadable(picked);
        } catch {
          error.value = t("feed.heicFailed");
          continue;
        } finally {
          converting.value = false;
        }
      }
      const asset = await mediaService.upload(file, "image");
      mediaIds.value.push(asset.id);
      previews.value.push(URL.createObjectURL(file));
    }
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    uploading.value = false;
  }
}

function removeMedia(i: number) {
  URL.revokeObjectURL(previews.value[i]);
  mediaIds.value.splice(i, 1);
  previews.value.splice(i, 1);
}

function reset() {
  body.value = "";
  previews.value.forEach((url) => URL.revokeObjectURL(url));
  mediaIds.value = [];
  previews.value = [];
  audience.value = "public";
  commentPolicy.value = "everyone";
  expanded.value = false;
  pollOpen.value = false;
  pollOptions.value = ["", ""];
  pollHours.value = null;
}

async function submit() {
  const text = body.value.trim();
  if ((!text && mediaIds.value.length === 0) || submitting.value) return;
  if (pollOpen.value && !pollReady.value) {
    error.value = t("feed.pollIncomplete");
    return;
  }
  submitting.value = true;
  error.value = "";
  try {
    const post = await postService.create({
      body: text,
      media_ids: mediaIds.value,
      audience: audience.value,
      comment_policy: commentPolicy.value,
      ...(pollOpen.value
        ? { poll: { options: filledOptions.value, duration_hours: pollHours.value } }
        : {}),
    });
    emit("created", post);
    reset();
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div ref="root" class="card p-4">
    <div class="flex items-center gap-3">
      <UserAvatar :name="authorName()" :media-id="auth.profile?.avatar_media_id" :size="40" />

      <button
        v-if="!expanded"
        class="h-11 flex-1 rounded-full border border-transparent bg-gray-100 px-5 text-start text-sm text-gray-500 transition hover:border-brand-200 hover:bg-white dark:bg-gray-800/70 dark:text-gray-400 dark:hover:border-brand-900 dark:hover:bg-gray-800"
        @click="expanded = true"
      >
        {{ t("feed.composerPlaceholder") }}
      </button>

      <div v-else class="min-w-0">
        <p class="truncate text-sm font-semibold">{{ authorName() }}</p>
        <div class="relative">
          <button
            class="mt-0.5 inline-flex items-center gap-1 rounded-md bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600 transition hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300"
            @click="showAudience = !showAudience"
          >
            <component :is="currentAudience.icon" class="h-3 w-3" />
            {{ t(currentAudience.label) }}
            <ChevronDown class="h-3 w-3" />
          </button>
          <template v-if="showAudience">
            <div class="fixed inset-0 z-40" @click="showAudience = false" />
            <div class="popover absolute start-0 z-50 mt-1 w-48 p-1" role="menu">
              <p class="px-2 pb-1 pt-0.5 text-xs font-semibold text-gray-500 dark:text-gray-400">{{ t("feed.audience") }}</p>
              <button
                v-for="a in AUDIENCES"
                :key="a.v"
                class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800"
                :class="audience === a.v ? 'text-brand-600 dark:text-brand-300' : ''"
                @click="audience = a.v; showAudience = false"
              >
                <component :is="a.icon" class="h-4 w-4" /> {{ t(a.label) }}
              </button>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- Quick actions (collapsed): each opens the composer in that mode. -->
    <div v-if="!expanded" class="mt-3 grid grid-cols-2 gap-1 border-t border-gray-100 pt-2 dark:border-gray-800">
      <label class="btn-ghost cursor-pointer focus-within:ring-2 focus-within:ring-brand-400" :class="uploading ? 'opacity-50' : ''">
        <ImagePlus class="h-5 w-5 text-emerald-500" />
        <span>{{ converting ? t("feed.heicConverting") : uploading ? t("states.loading") : t("feed.photo") }}</span>
        <input type="file" :accept="IMAGE_ACCEPT" multiple class="sr-only" :aria-label="t('feed.addPhotos')" @change="onFiles($event); expanded = true" />
      </label>
      <button type="button" class="btn-ghost" @click="expanded = true; pollOpen = true">
        <BarChart3 class="h-5 w-5 text-accent-500" />
        <span>{{ t("feed.poll") }}</span>
      </button>
    </div>

    <div v-if="expanded" class="mt-3">
      <MentionField
        v-model="body"
        multiline
        field-class="input min-h-[88px] resize-none border-0 bg-gray-50 text-base focus:ring-0 dark:bg-gray-800/60"
        :placeholder="pollOpen ? t('feed.pollQuestion') : t('feed.composerPlaceholder')"
      />

      <div v-if="pollOpen" class="mt-2 space-y-2" data-testid="poll-editor">
        <input
          v-for="(_, i) in pollOptions"
          :key="i"
          v-model="pollOptions[i]"
          class="input"
          dir="auto"
          maxlength="120"
          :placeholder="t('feed.pollOption', { n: i + 1 })"
          :aria-label="t('feed.pollOption', { n: i + 1 })"
        />
        <div class="flex items-center justify-between gap-2">
          <button
            v-if="pollOptions.length < POLL_MAX_OPTIONS"
            type="button"
            class="btn-ghost text-sm"
            @click="pollOptions.push('')"
          >
            <Plus class="h-4 w-4" /> {{ t("feed.pollAddOption") }}
          </button>
          <select v-model="pollHours" class="input ms-auto w-auto" :aria-label="t('feed.pollDuration')">
            <option v-for="d in POLL_DURATIONS" :key="d.label" :value="d.hours">{{ t(d.label) }}</option>
          </select>
        </div>
      </div>

      <div v-if="previews.length" class="mt-2 grid grid-cols-4 gap-2 sm:grid-cols-5">
        <div v-for="(src, i) in previews" :key="i" class="relative">
          <img :src="src" class="h-20 w-full rounded-lg object-cover" :alt="t('post.imageAlt', { n: i + 1, name: authorName() })" />
          <button
            class="absolute end-1 top-1 rounded-full bg-black/60 p-0.5 text-white"
            :aria-label="t('friends.delete')"
            @click="removeMedia(i)"
          >
            <X class="h-3 w-3" />
          </button>
        </div>
      </div>

      <p v-if="error" class="mt-2 text-xs text-red-500">{{ error }}</p>

      <div class="mt-3 flex flex-wrap items-center gap-1 border-t border-gray-100 pt-3 dark:border-gray-800">
        <label class="btn-ghost cursor-pointer focus-within:ring-2 focus-within:ring-brand-400" :class="uploading ? 'opacity-50' : ''" :title="t('feed.addPhotos')">
          <ImagePlus class="h-5 w-5 text-green-600" />
          <span class="text-sm">{{ converting ? t("feed.heicConverting") : uploading ? t("states.loading") : t("feed.photo") }}</span>
          <input type="file" :accept="IMAGE_ACCEPT" multiple class="sr-only" :aria-label="t('feed.addPhotos')" @change="onFiles" />
        </label>
        <button type="button" class="btn-ghost" :aria-pressed="pollOpen" :class="pollOpen ? 'text-brand-600 dark:text-brand-300' : ''" @click="pollOpen = !pollOpen">
          <BarChart3 class="h-5 w-5" />
          <span class="text-sm">{{ t("feed.poll") }}</span>
        </button>
        <select v-model="commentPolicy" class="input h-9 w-auto py-1 text-xs" :aria-label="t('post.commentPolicy')" data-testid="comment-policy">
          <option v-for="p in COMMENT_POLICIES" :key="p" :value="p">{{ t(POLICY_LABEL[p]) }}</option>
        </select>
        <div class="ms-auto flex gap-2">
          <button class="btn-ghost" @click="reset">{{ t("feed.cancel") }}</button>
          <button class="btn-primary" :disabled="submitting || uploading" @click="submit">
            {{ submitting ? t("feed.posting") : t("feed.post") }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
