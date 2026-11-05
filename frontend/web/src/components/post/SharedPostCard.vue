<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import LinkPreviewCard from "@/components/post/LinkPreviewCard.vue";
import VideoPlayer from "@/components/media/VideoPlayer.vue";
import MediaGrid from "@/components/post/MediaGrid.vue";
import MediaTheater from "@/components/post/MediaTheater.vue";
import RichText from "@/components/post/RichText.vue";
import { relativeTime } from "@/lib/format";
import { useMediaViewer } from "@/lib/useMediaViewer";
import { useDirectoryStore } from "@/stores/directory";
import type { SharedPost } from "@/types";

// `post` is null when this reader may not see the original, or it is gone.
// `viewKey` is the sharing post's id, so `?view=` opens this card's photos even
// when the same original is shared more than once on a page.
const props = defineProps<{ post: SharedPost | null | undefined; viewKey?: string }>();

const { t } = useI18n();
const directory = useDirectoryStore();
const mediaIds = computed(() => props.post?.media_ids ?? []);
const viewer = useMediaViewer(
  () => props.viewKey ?? props.post?.id ?? "",
  () => mediaIds.value.length,
);
const author = computed(() => (props.post ? directory.label(props.post.author_id) : ""));
</script>

<template>
  <div class="mt-3 overflow-hidden rounded-xl border border-gray-200 dark:border-gray-700" data-testid="shared-post">
    <p v-if="!post" class="p-3 text-sm text-gray-500 dark:text-gray-400">{{ t("post.sharedUnavailable") }}</p>
    <template v-else>
      <VideoPlayer v-if="(post?.type === 'video' || post?.type === 'reel') && mediaIds.length" class="!mt-0 !rounded-none" :media-id="mediaIds[0]" />
      <MediaGrid v-else-if="mediaIds.length" compact class="!mt-0" :media-ids="mediaIds" :author-name="author" @open="viewer.open" />
      <MediaTheater
        v-if="viewer.index.value !== null"
        :media-ids="mediaIds"
        :index="viewer.index.value"
        :author-name="author"
        @go="viewer.go"
        @close="viewer.close"
      >
        <!-- The original's author and text; reacting and commenting happen on the original post. -->
        <template #panel>
          <div class="space-y-3" data-testid="theater-shared-panel">
            <RouterLink :to="`/posts/${post.id}`" class="flex items-center gap-3 hover:underline">
              <UserAvatar :name="author" :media-id="directory.avatarOf(post.author_id)" :size="40" />
              <span class="min-w-0 flex-1 text-start">
                <span class="block truncate font-bold"><bdi>{{ author }}</bdi></span>
                <time class="text-xs text-gray-600 dark:text-gray-400">{{ relativeTime(post.created_at) }}</time>
              </span>
            </RouterLink>
            <p v-if="post.body" class="whitespace-pre-wrap break-words text-[15px]" dir="auto"><RichText :body="post.body" /></p>
            <RouterLink :to="`/posts/${post.id}`" class="btn-soft w-full justify-center">{{ t("profileTools.theater.openPost") }}</RouterLink>
          </div>
        </template>
      </MediaTheater>
      <div class="p-3">
        <RouterLink :to="`/posts/${post.id}`" class="flex items-center gap-2 text-xs text-gray-500 hover:underline dark:text-gray-400">
          <UserAvatar :name="author" :media-id="directory.avatarOf(post.author_id)" :size="24" />
          <span class="font-semibold text-gray-700 dark:text-gray-200" dir="auto">{{ author }}</span>
          <span aria-hidden="true">·</span>
          <time>{{ relativeTime(post.created_at) }}</time>
        </RouterLink>
        <p v-if="post.body" class="mt-2 whitespace-pre-wrap break-words text-sm" dir="auto"><RichText :body="post.body" /></p>
        <LinkPreviewCard v-if="post.link_preview" :preview="post.link_preview" />
      </div>
    </template>
  </div>
</template>
