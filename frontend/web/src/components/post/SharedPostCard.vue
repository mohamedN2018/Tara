<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import LinkPreviewCard from "@/components/post/LinkPreviewCard.vue";
import RichText from "@/components/post/RichText.vue";
import { relativeTime } from "@/lib/format";
import { useMediaUrls } from "@/lib/useMediaUrl";
import { useDirectoryStore } from "@/stores/directory";
import type { SharedPost } from "@/types";

// `post` is null when this reader may not see the original, or it is gone.
const props = defineProps<{ post: SharedPost | null | undefined }>();

const { t } = useI18n();
const directory = useDirectoryStore();
const images = useMediaUrls(() => props.post?.media_ids ?? []);
const author = computed(() => (props.post ? directory.label(props.post.author_id) : ""));
</script>

<template>
  <div class="mt-3 overflow-hidden rounded-xl border border-gray-200 dark:border-gray-700" data-testid="shared-post">
    <p v-if="!post" class="p-3 text-sm text-gray-500">{{ t("post.sharedUnavailable") }}</p>
    <template v-else>
      <img v-if="images.length" :src="images[0]" class="max-h-72 w-full object-cover" loading="lazy" :alt="t('post.imageAlt', { n: 1, name: author })" />
      <div class="p-3">
        <RouterLink :to="`/posts/${post.id}`" class="flex items-center gap-2 text-xs text-gray-500 hover:underline">
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
