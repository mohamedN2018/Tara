<script setup lang="ts">
import { Heart, MessageSquare, Send as Share2 } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { apiError } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import { useMediaUrls } from "@/lib/useMediaUrl";
import { type Comment, postService } from "@/services/post";
import type { Post } from "@/types";

const props = defineProps<{
  post: Post;
  authorName?: string;
  authorHandle?: string;
  authorAvatar?: string | null;
}>();

const { t } = useI18n();

const liked = ref(false);
const reactionCount = ref(props.post.reaction_count);
const commentCount = ref(props.post.comment_count);
const showComments = ref(false);
const comments = ref<Comment[]>([]);
const commentBody = ref("");
const loadingComments = ref(false);
const submitting = ref(false);

const images = useMediaUrls(() => props.post.media_ids);

async function toggleLike() {
  const next = !liked.value;
  liked.value = next;
  reactionCount.value += next ? 1 : -1;
  try {
    if (next) await postService.react(props.post.id);
    else await postService.unreact(props.post.id);
  } catch {
    // Revert on failure.
    liked.value = !next;
    reactionCount.value += next ? -1 : 1;
  }
}

async function toggleComments() {
  showComments.value = !showComments.value;
  if (showComments.value && comments.value.length === 0) {
    loadingComments.value = true;
    try {
      const page = await postService.comments(props.post.id);
      comments.value = page.data;
    } catch {
      comments.value = [];
    } finally {
      loadingComments.value = false;
    }
  }
}

async function submitComment() {
  const body = commentBody.value.trim();
  if (!body || submitting.value) return;
  submitting.value = true;
  try {
    const created = await postService.addComment(props.post.id, body);
    comments.value.push(created);
    commentCount.value += 1;
    commentBody.value = "";
  } catch (e) {
    alert(apiError(e).message);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <article class="card p-4">
    <header class="flex items-center gap-3">
      <RouterLink :to="authorHandle ? `/u/${authorHandle}` : ''">
        <UserAvatar :name="authorName || post.author_id" :media-id="authorAvatar" />
      </RouterLink>
      <div class="min-w-0">
        <RouterLink
          :to="authorHandle ? `/u/${authorHandle}` : ''"
          class="block truncate text-sm font-semibold hover:underline"
        >
          {{ authorName || post.author_id }}
        </RouterLink>
        <time class="text-xs text-gray-500">{{ relativeTime(post.created_at) }}</time>
      </div>
    </header>

    <p v-if="post.body" class="mt-3 whitespace-pre-wrap text-sm leading-relaxed">{{ post.body }}</p>

    <div
      v-if="images.length"
      class="mt-3 grid gap-1.5 overflow-hidden rounded-lg"
      :class="images.length === 1 ? 'grid-cols-1' : 'grid-cols-2'"
    >
      <img
        v-for="(src, i) in images"
        :key="i"
        :src="src!"
        class="h-48 w-full object-cover"
        loading="lazy"
        alt=""
      />
    </div>

    <div class="mt-3 flex items-center gap-1 border-t border-gray-100 pt-2 text-sm dark:border-gray-800">
      <button
        class="btn-ghost flex-1"
        :class="liked ? 'text-red-500' : ''"
        @click="toggleLike"
      >
        <Heart class="h-4 w-4" :fill="liked ? 'currentColor' : 'none'" />
        {{ reactionCount }}
      </button>
      <button class="btn-ghost flex-1" @click="toggleComments">
        <MessageSquare class="h-4 w-4" />
        {{ commentCount }}
      </button>
      <button class="btn-ghost flex-1">
        <Share2 class="h-4 w-4" />
        {{ post.share_count }}
      </button>
    </div>

    <section v-if="showComments" class="mt-2 space-y-3 border-t border-gray-100 pt-3 dark:border-gray-800">
      <div class="flex gap-2">
        <input
          v-model="commentBody"
          class="input"
          :placeholder="t('post.addComment')"
          @keyup.enter="submitComment"
        />
        <button class="btn-primary" :disabled="submitting" @click="submitComment">
          {{ t("post.comment") }}
        </button>
      </div>
      <p v-if="loadingComments" class="text-xs text-gray-500">{{ t("states.loading") }}</p>
      <div v-for="c in comments" :key="c.id" class="rounded-lg bg-gray-50 p-2 text-sm dark:bg-gray-800/50">
        <span class="font-medium">{{ c.author_id.slice(0, 8) }}</span>
        <p class="text-gray-700 dark:text-gray-300">{{ c.body }}</p>
      </div>
    </section>
  </article>
</template>
