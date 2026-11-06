<script setup lang="ts">
// A feed card before its post is hydrated (08 §7.4, §7.7; WP 4c.1-B3, 4c.4-B3).
//
// - No `snapshot`: a card-shaped skeleton (avatar, two text lines, a media
//   block sized like a real card's, the action row), for the first load and
//   the next page.
// - A `snapshot` the server marked public, with an excerpt or media: the first
//   paint shows what `/feed/` sent and nothing else (author, time, excerpt,
//   photos). Counts and actions stay skeletons until `/posts/batch/` answers:
//   the snapshot carries no counts and none are invented.
// - Any other snapshot (friends, group, private…) carries ids only: it stays a
//   skeleton with no text until hydration, which replaces or removes it.
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import MediaGrid from "@/components/post/MediaGrid.vue";
import { relativeTime } from "@/lib/format";
import { useDirectoryStore } from "@/stores/directory";
import { usePageDirectoryStore } from "@/stores/pageDirectory";
import type { Post } from "@/types";

const props = withDefaults(defineProps<{ snapshot?: Post | null; media?: boolean; eager?: boolean }>(), {
  snapshot: null,
  media: true,
  eager: false,
});
const { t } = useI18n();
const directory = useDirectoryStore();
const pages = usePageDirectoryStore();

/** Only a public snapshot with real content is drawn; anything else stays a skeleton. */
const content = computed(() => {
  const s = props.snapshot;
  if (!s || s.audience !== "public") return null;
  const images = s.type === "video" || s.type === "reel" ? [] : (s.media_ids ?? []);
  if (!s.body && !images.length) return null;
  return { post: s, images };
});
const byPage = computed(() => content.value?.post.author_type === "page");
const name = computed(() => {
  const p = content.value?.post;
  if (!p) return "";
  return byPage.value ? pages.label(p.author_id) : directory.label(p.author_id);
});
const avatar = computed(() => {
  const p = content.value?.post;
  if (!p) return null;
  return byPage.value ? pages.avatarOf(p.author_id) : directory.avatarOf(p.author_id);
});
</script>

<template>
  <div
    v-if="content"
    class="card p-4 sm:p-5"
    :data-post-id="content.post.id"
    data-snapshot="content"
    data-testid="feed-snapshot-card"
    :aria-busy="true"
  >
    <div class="flex items-center gap-3">
      <UserAvatar :name="name" :media-id="avatar" :size="44" />
      <div class="min-w-0 flex-1">
        <p class="truncate text-[15px] font-bold text-gray-900 dark:text-white" dir="auto">{{ name }}</p>
        <p class="text-xs text-gray-500 dark:text-gray-400">{{ relativeTime(content.post.created_at) }}</p>
      </div>
    </div>
    <p v-if="content.post.body" class="mt-3 whitespace-pre-wrap break-words text-[15px] leading-relaxed" dir="auto">{{ content.post.body }}</p>
    <div v-if="content.images.length" class="-mx-4 sm:-mx-5">
      <MediaGrid :media-ids="content.images" :author-name="name" compact :eager="eager" />
    </div>
    <div class="mt-4 flex gap-3 border-t border-gray-100 pt-3 dark:border-gray-800" aria-hidden="true">
      <div class="skeleton h-8 flex-1 rounded-lg" />
      <div class="skeleton h-8 flex-1 rounded-lg" />
      <div class="skeleton h-8 flex-1 rounded-lg" />
    </div>
    <span class="sr-only">{{ t("delivery.snapshot.label") }}</span>
  </div>
  <div v-else class="card p-4 sm:p-5" data-testid="feed-card-skeleton" aria-hidden="true">
    <div class="flex items-center gap-3">
      <div class="skeleton h-11 w-11 rounded-full" />
      <div class="flex-1 space-y-2">
        <div class="skeleton h-3 w-1/3" />
        <div class="skeleton h-3 w-1/4" />
      </div>
    </div>
    <div class="mt-4 space-y-2">
      <div class="skeleton h-3 w-full" />
      <div class="skeleton h-3 w-5/6" />
    </div>
    <div v-if="media" class="skeleton -mx-4 mt-3 aspect-[4/3] max-h-[32rem] rounded-none sm:-mx-5" />
    <div class="mt-4 flex gap-3">
      <div class="skeleton h-8 flex-1 rounded-lg" />
      <div class="skeleton h-8 flex-1 rounded-lg" />
      <div class="skeleton h-8 flex-1 rounded-lg" />
    </div>
  </div>
</template>
