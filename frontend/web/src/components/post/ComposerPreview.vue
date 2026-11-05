<script setup lang="ts">
// The composer's live preview (wide screens): the post as it will appear in the
// feed, built only from what is in the composer right now. Nothing here is
// sent anywhere; the server still decides what is published.
import { BarChart3, Film, Globe, Image as ImageIcon, Lock, UserCheck, Users } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import RichText from "@/components/post/RichText.vue";
import { FEELING_EMOJI } from "@/services/composer";

const props = defineProps<{
  name: string;
  avatarId?: string | null;
  audience: string;
  inGroup: boolean;
  body: string;
  /** Object URLs of the picked photos (null: a HEIC with no browser preview). */
  photos: (string | null)[];
  hasVideo: boolean;
  feeling: string;
  location: string;
  taggedNames: string[];
  pollOptions: string[];
}>();

const { t } = useI18n();
const AUDIENCE_ICON: Record<string, typeof Globe> = { public: Globe, friends: Users, followers: UserCheck, only_me: Lock };
const audienceIcon = computed(() => (props.inGroup ? Users : (AUDIENCE_ICON[props.audience] ?? Globe)));
const shown = computed(() => props.photos.slice(0, 4));
const extra = computed(() => Math.max(0, props.photos.length - 4));
const empty = computed(
  () => !props.body.trim() && !props.photos.length && !props.hasVideo && !props.feeling && !props.pollOptions.length,
);
</script>

<template>
  <section class="flex min-h-0 flex-col" :aria-label="t('polish.composer.previewLabel')" data-testid="composer-preview">
    <h3 class="mb-2 text-sm font-semibold text-gray-600 dark:text-gray-300">{{ t("polish.composer.preview") }}</h3>
    <article class="card min-h-0 overflow-y-auto p-4" aria-live="polite">
      <header class="flex items-center gap-3">
        <UserAvatar :name="name" :media-id="avatarId" :size="40" />
        <div class="min-w-0">
          <p class="text-start text-[15px] font-bold">
            <bdi>{{ name }}</bdi>
            <span v-if="feeling" class="font-normal text-gray-600 dark:text-gray-300">
              — <span aria-hidden="true">{{ FEELING_EMOJI[feeling] }}</span> {{ t(`composer.feelings.${feeling}`) }}</span>
            <span v-if="taggedNames.length" class="font-normal text-gray-600 dark:text-gray-300">
              {{ " " }}{{
                taggedNames.length > 1
                  ? t("composer.meta.withOthers", { name: taggedNames[0], count: taggedNames.length - 1 }, taggedNames.length - 1)
                  : t("composer.meta.with", { name: taggedNames[0] })
              }}</span>
            <span v-if="location.trim()" class="font-normal text-gray-600 dark:text-gray-300">
              {{ " " }}{{ t("composer.meta.at", { place: location.trim() }) }}</span>
          </p>
          <p class="flex items-center gap-1 text-xs text-gray-600 dark:text-gray-400">
            {{ t("polish.composer.justNow") }} <span aria-hidden="true">·</span>
            <component :is="audienceIcon" class="h-3 w-3" aria-hidden="true" />
          </p>
        </div>
      </header>

      <p v-if="empty" class="mt-4 text-sm text-gray-600 dark:text-gray-400" data-testid="composer-preview-empty">{{ t("polish.composer.previewEmpty") }}</p>
      <p v-if="body.trim()" class="mt-3 whitespace-pre-wrap break-words text-start text-[15px]" dir="auto" data-testid="composer-preview-body"><RichText :body="body" /></p>

      <ul v-if="pollOptions.length" class="mt-3 space-y-2" :aria-label="t('feed.poll')">
        <li v-for="(o, i) in pollOptions" :key="i" class="flex items-center gap-2 rounded-xl border border-gray-200 px-3 py-2 text-sm dark:border-gray-700">
          <BarChart3 class="h-4 w-4 shrink-0 text-sky-600 dark:text-sky-400" aria-hidden="true" /><bdi>{{ o }}</bdi>
        </li>
      </ul>

      <div v-if="shown.length" class="mt-3 grid gap-1 overflow-hidden rounded-xl" :class="shown.length === 1 ? 'grid-cols-1' : 'grid-cols-2'" data-testid="composer-preview-photos">
        <div v-for="(src, i) in shown" :key="i" class="relative bg-gray-100 dark:bg-gray-800" :class="shown.length === 1 ? 'aspect-video' : 'aspect-square'">
          <img v-if="src" :src="src" class="h-full w-full object-cover" alt="" />
          <span v-else class="flex h-full w-full items-center justify-center text-gray-500 dark:text-gray-400"><ImageIcon class="h-6 w-6" aria-hidden="true" /></span>
          <span v-if="i === 3 && extra" class="absolute inset-0 flex items-center justify-center bg-black/55 text-2xl font-bold text-white">+{{ extra }}</span>
        </div>
      </div>
      <p v-else-if="hasVideo" class="mt-3 flex aspect-video items-center justify-center gap-2 rounded-xl bg-gray-900 text-sm text-white">
        <Film class="h-5 w-5" aria-hidden="true" /> {{ t("polish.composer.videoPreview") }}
      </p>
    </article>
  </section>
</template>
