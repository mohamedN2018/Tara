<script setup lang="ts">
import { BarChart3, ChevronDown, Globe, ImagePlus, Lock, Plus, UserCheck, Users, X } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import MentionField from "@/components/post/MentionField.vue";
import { errorMessage } from "@/lib/errors";
import { mediaService } from "@/services/media";
import { postService } from "@/services/post";
import { useAuthStore } from "@/stores/auth";
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
const error = ref("");

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

const authorName = () => auth.profile?.display_name || auth.account?.email?.split("@")[0] || "?";

async function onFiles(e: Event) {
  const files = (e.target as HTMLInputElement).files;
  if (!files?.length) return;
  uploading.value = true;
  error.value = "";
  try {
    for (const file of Array.from(files).slice(0, 4)) {
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
  mediaIds.value.splice(i, 1);
  previews.value.splice(i, 1);
}

function reset() {
  body.value = "";
  mediaIds.value = [];
  previews.value = [];
  audience.value = "public";
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
  <div class="card p-3">
    <div class="flex items-center gap-3">
      <UserAvatar :name="authorName()" :media-id="auth.profile?.avatar_media_id" :size="40" />

      <button
        v-if="!expanded"
        class="flex-1 rounded-full bg-gray-100 px-4 py-2.5 text-start text-sm text-gray-500 transition hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700"
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
            <div class="card absolute start-0 z-50 mt-1 w-48 p-1" role="menu">
              <p class="px-2 pb-1 pt-0.5 text-xs font-semibold text-gray-400">{{ t("feed.audience") }}</p>
              <button
                v-for="a in AUDIENCES"
                :key="a.v"
                class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800"
                :class="audience === a.v ? 'text-brand-600' : ''"
                @click="audience = a.v; showAudience = false"
              >
                <component :is="a.icon" class="h-4 w-4" /> {{ t(a.label) }}
              </button>
            </div>
          </template>
        </div>
      </div>
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

      <div v-if="previews.length" class="mt-2 grid grid-cols-4 gap-2">
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
        <label class="btn-ghost cursor-pointer focus-within:ring-2 focus-within:ring-brand-300" :class="uploading ? 'opacity-50' : ''" :title="t('feed.addPhotos')">
          <ImagePlus class="h-5 w-5 text-green-600" />
          <span class="text-sm">{{ uploading ? t("states.loading") : t("feed.photo") }}</span>
          <input type="file" accept="image/*" multiple class="sr-only" :aria-label="t('feed.addPhotos')" @change="onFiles" />
        </label>
        <button type="button" class="btn-ghost" :aria-pressed="pollOpen" :class="pollOpen ? 'text-brand-600' : ''" @click="pollOpen = !pollOpen">
          <BarChart3 class="h-5 w-5" />
          <span class="text-sm">{{ t("feed.poll") }}</span>
        </button>
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
