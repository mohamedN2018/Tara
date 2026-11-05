<script setup lang="ts">
import { ExternalLink } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { RouteLocationRaw } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import CommentList from "@/components/post/CommentList.vue";
import PostActions from "@/components/post/PostActions.vue";
import ReactionsDialog from "@/components/post/ReactionsDialog.vue";
import RichText from "@/components/post/RichText.vue";
import { relativeTime } from "@/lib/format";
import { applyReactionChange } from "@/lib/reactionCounts";
import { type CommentPolicy, postService } from "@/services/post";
import { useToastStore } from "@/stores/toasts";
import type { Post } from "@/types";

/** What the panel changed, so the card under the theater shows the same counts. */
export interface PanelState {
  myReaction: string | null;
  reactionCount: number;
  reactionCounts: Record<string, number>;
  commentCount: number;
}

// The photo theater's side panel (plan 08): the post's author, text, reactions
// and comments, beside the photo. Reactions and comments go to the post service
// like everywhere else; the server checks who may see, react and comment.
const props = withDefaults(
  defineProps<{
    post: Post;
    authorName: string;
    authorAvatar?: string | null;
    authorTo: RouteLocationRaw;
    /** The latest text (an edit made in the card). */
    body?: string;
    policy?: CommentPolicy;
    knownNames?: Record<string, string>;
    canModerate?: boolean;
    /** Starting counts (the card's live ones); the post's own otherwise. */
    state?: PanelState | null;
  }>(),
  { authorAvatar: null, body: undefined, policy: undefined, knownNames: () => ({}), canModerate: false, state: null },
);
const emit = defineEmits<{ changed: [state: PanelState]; share: [] }>();

const { t } = useI18n();
const toasts = useToastStore();

const myReaction = ref<string | null>(props.state?.myReaction ?? props.post.my_reaction ?? null);
const reactionCount = ref(props.state?.reactionCount ?? props.post.reaction_count ?? 0);
const reactionCounts = ref<Record<string, number>>({ ...(props.state?.reactionCounts ?? props.post.reaction_counts ?? {}) });
const commentCount = ref(props.state?.commentCount ?? props.post.comment_count ?? 0);
const showReactions = ref(false);
const text = computed(() => props.body ?? props.post.body ?? "");
const policy = computed<CommentPolicy>(() => props.policy ?? props.post.comment_policy ?? "everyone");

watch([myReaction, reactionCount, reactionCounts, commentCount], () =>
  emit("changed", {
    myReaction: myReaction.value,
    reactionCount: reactionCount.value,
    reactionCounts: reactionCounts.value,
    commentCount: commentCount.value,
  }),
);

async function react(type: string) {
  const prev = myReaction.value;
  if (prev === type) return;
  const before = reactionCounts.value;
  if (prev === null) reactionCount.value += 1;
  myReaction.value = type;
  reactionCounts.value = applyReactionChange(before, prev, type);
  try {
    await postService.react(props.post.id, type);
  } catch (e) {
    myReaction.value = prev;
    reactionCounts.value = before;
    if (prev === null) reactionCount.value -= 1;
    toasts.error(e);
  }
}

async function unreact() {
  const prev = myReaction.value;
  if (prev === null) return;
  const before = reactionCounts.value;
  myReaction.value = null;
  reactionCount.value -= 1;
  reactionCounts.value = applyReactionChange(before, prev, null);
  try {
    await postService.unreact(props.post.id);
  } catch (e) {
    myReaction.value = prev;
    reactionCounts.value = before;
    reactionCount.value += 1;
    toasts.error(e);
  }
}

const comments = ref<HTMLElement | null>(null);
function focusComments() {
  const box = comments.value?.querySelector<HTMLElement>("textarea, input, [contenteditable='true']");
  box?.focus();
}
</script>

<template>
  <div class="space-y-3" data-testid="theater-post-panel">
    <header class="flex items-center gap-3">
      <RouterLink :to="authorTo" :aria-label="authorName" class="shrink-0">
        <UserAvatar :name="authorName" :media-id="authorAvatar" :size="40" />
      </RouterLink>
      <div class="min-w-0 flex-1 text-start">
        <RouterLink :to="authorTo" class="block truncate font-bold hover:underline" data-testid="theater-author">
          <bdi>{{ authorName }}</bdi>
        </RouterLink>
        <RouterLink :to="`/posts/${post.id}`" class="text-xs text-gray-600 hover:underline dark:text-gray-400">
          {{ relativeTime(post.created_at) }}
        </RouterLink>
      </div>
      <RouterLink
        :to="`/posts/${post.id}`"
        class="icon-btn h-9 w-9 shrink-0"
        :aria-label="t('profileTools.theater.openPost')"
        :title="t('profileTools.theater.openPost')"
        data-testid="theater-open-post"
      >
        <ExternalLink class="h-4 w-4 rtl:-scale-x-100" aria-hidden="true" />
      </RouterLink>
    </header>

    <p v-if="text" class="whitespace-pre-wrap break-words text-[15px] leading-relaxed" dir="auto" data-testid="theater-body">
      <RichText :body="text" />
    </p>

    <PostActions
      :my-reaction="myReaction"
      :reaction-count="reactionCount"
      :reaction-counts="reactionCounts"
      :comment-count="commentCount"
      :share-count="post.share_count ?? 0"
      @react="react"
      @unreact="unreact"
      @comment="focusComments"
      @share="emit('share')"
      @reactions="showReactions = true"
      @shares="emit('share')"
    />

    <section ref="comments" class="border-t border-gray-200 pt-3 dark:border-gray-800" :aria-label="t('profileTools.theater.comments')">
      <CommentList
        :post-id="post.id"
        :post-author-id="post.author_id"
        :policy="policy"
        :known-names="knownNames"
        :can-moderate="canModerate"
        @added="commentCount += 1"
        @total="commentCount = $event"
      />
    </section>

    <ReactionsDialog
      v-if="showReactions"
      class="!z-[80]"
      :post-id="post.id"
      :counts="reactionCounts"
      :total="reactionCount"
      @close="showReactions = false"
    />
  </div>
</template>
