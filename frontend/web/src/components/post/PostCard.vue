<script setup lang="ts">
import {
  Bookmark,
  Flag,
  Globe,
  Lock,
  MessageSquareOff,
  MoreHorizontal,
  PenSquare,
  Trash2,
  UserCheck,
  Users,
} from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { RouteLocationRaw } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import CommentList from "@/components/post/CommentList.vue";
import LinkPreviewCard from "@/components/post/LinkPreviewCard.vue";
import MediaGrid from "@/components/post/MediaGrid.vue";
import MediaTheater from "@/components/post/MediaTheater.vue";
import PollCard from "@/components/post/PollCard.vue";
import PostActions from "@/components/post/PostActions.vue";
import ReactionsDialog from "@/components/post/ReactionsDialog.vue";
import RichText from "@/components/post/RichText.vue";
import ShareBox from "@/components/post/ShareBox.vue";
import SharedPostCard from "@/components/post/SharedPostCard.vue";
import SharesDialog from "@/components/post/SharesDialog.vue";
import { relativeTime } from "@/lib/format";
import { applyReactionChange } from "@/lib/reactionCounts";
import { hasLink } from "@/lib/richText";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useMediaViewer } from "@/lib/useMediaViewer";
import { COMMENT_POLICIES, type CommentPolicy, postService } from "@/services/post";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";
import type { Post } from "@/types";

const props = withDefaults(
  defineProps<{
    post: Post;
    authorName?: string;
    authorHandle?: string;
    authorAvatar?: string | null;
    startCommentsOpen?: boolean;
  }>(),
  { startCommentsOpen: false },
);
const emit = defineEmits<{ removed: [id: string]; shared: [post: Post] }>();

const { t } = useI18n();
const auth = useAuthStore();
const directory = useDirectoryStore();
const toasts = useToastStore();

const authorDisplay = computed(() => props.authorName || directory.label(props.post.author_id));
const avatarId = computed(() => props.authorAvatar ?? directory.avatarOf(props.post.author_id));
// Always navigate by account id (post.author_id) — that route loads the
// author's posts. The handle route can't resolve posts for other users.
const authorTo = computed<RouteLocationRaw>(() => ({
  name: "profile-by-id",
  params: { id: props.post.author_id },
}));
const isAuthor = computed(() => auth.account?.id === props.post.author_id);
// A feed snapshot holds at most an excerpt: saving it would truncate the post.
const canEdit = computed(
  () => isAuthor.value && !props.post.partial && props.post.type !== "poll",
);
const isShare = computed(() => !!props.post.shared_post_id);

// The server builds the preview after the post is saved, so a post just written
// doesn't have it yet.
const PREVIEW_REFETCH_MS = 2500;
const linkPreview = ref(props.post.link_preview ?? null);
let previewTimer: number | undefined;
function refetchPreviewSoon() {
  window.clearTimeout(previewTimer);
  previewTimer = window.setTimeout(async () => {
    try {
      linkPreview.value = (await postService.get(props.post.id)).link_preview ?? null;
    } catch {
      // Shown on the next load.
    }
  }, PREVIEW_REFETCH_MS);
}

const AUDIENCE_ICON: Record<string, typeof Globe> = {
  public: Globe,
  friends: Users,
  followers: UserCheck,
  only_me: Lock,
};
const audienceIcon = computed(() => AUDIENCE_ICON[props.post.audience] ?? Globe);
const fullTime = computed(() => {
  try {
    return new Date(props.post.created_at).toLocaleString();
  } catch {
    return "";
  }
});

const menuOpen = ref(false);
useEscapeKey(menuOpen, () => (menuOpen.value = false));
const removing = ref(false);
async function remove() {
  if (removing.value) return;
  removing.value = true;
  try {
    await postService.remove(props.post.id);
    emit("removed", props.post.id);
  } catch (e) {
    toasts.error(e);
  } finally {
    removing.value = false;
    menuOpen.value = false;
  }
}

// Edit (author only)
const localBody = ref(props.post.body);
const edited = ref(false);
const editing = ref(false);
const draft = ref("");
const savingEdit = ref(false);
function startEdit() {
  menuOpen.value = false;
  if (!canEdit.value) return;
  draft.value = localBody.value;
  editing.value = true;
}
async function saveEdit() {
  if (savingEdit.value) return;
  savingEdit.value = true;
  try {
    const updated = await postService.edit(props.post.id, draft.value.trim());
    localBody.value = updated.body;
    edited.value = true;
    editing.value = false;
    refetchPreviewSoon();
  } catch (e) {
    toasts.error(e);
  } finally {
    savingEdit.value = false;
  }
}

// Who can comment (author). The server enforces it; this only sets it.
const commentPolicy = ref<CommentPolicy>(props.post.comment_policy ?? "everyone");
const POLICY_LABEL: Record<CommentPolicy, string> = {
  everyone: "post.commentPolicyEveryone",
  friends: "post.commentPolicyFriends",
  off: "post.commentPolicyOff",
};
async function setPolicy(policy: CommentPolicy) {
  menuOpen.value = false;
  if (policy === commentPolicy.value) return;
  const prev = commentPolicy.value;
  commentPolicy.value = policy;
  try {
    await postService.setCommentPolicy(props.post.id, policy);
  } catch (e) {
    commentPolicy.value = prev;
    toasts.error(e);
  }
}

// Report (non-author)
const showReport = ref(false);
const reportReason = ref("");
const reported = ref(false);
async function submitReport() {
  if (!reportReason.value.trim()) return;
  try {
    await postService.report(props.post.id, reportReason.value.trim());
    reported.value = true;
    showReport.value = false;
    reportReason.value = "";
  } catch (e) {
    toasts.error(e);
  }
}

const myReaction = ref<string | null>(props.post.my_reaction ?? null);
const isSaved = ref(props.post.is_saved ?? false);
const reactionCount = ref(props.post.reaction_count);
const reactionCounts = ref<Record<string, number>>({ ...(props.post.reaction_counts ?? {}) });
const commentCount = ref(props.post.comment_count);
const shareCount = ref(props.post.share_count);
const showComments = ref(false);
const commentsMounted = ref(false);
const showReactions = ref(false);
const showShares = ref(false);

// Photos: grid in the card, full-screen viewer kept in `?view=<post>:<index>`.
const mediaIds = computed(() => props.post.media_ids ?? []);
const viewer = useMediaViewer(
  () => props.post.id,
  () => mediaIds.value.length,
);

// Names we genuinely know — used to label comments (others fall back to a short
// id). Never invents a name.
const knownNames = computed(() => {
  const map: Record<string, string> = {};
  if (props.authorName) map[props.post.author_id] = props.authorName;
  if (auth.account?.id) map[auth.account.id] = t("post.you");
  return map;
});

async function onReact(type: string) {
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

async function onUnreact() {
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

const JUST_POSTED_MS = 15_000;
onMounted(() => {
  if (props.startCommentsOpen) toggleComments();
  const fresh = Date.now() - new Date(props.post.created_at).getTime() < JUST_POSTED_MS;
  if (fresh && !linkPreview.value && isAuthor.value && hasLink(localBody.value)) refetchPreviewSoon();
});
onBeforeUnmount(() => window.clearTimeout(previewTimer));

function toggleComments() {
  showComments.value = !showComments.value;
  if (showComments.value) commentsMounted.value = true;
}

const sharing = ref(false);
function onShared(post: Post) {
  sharing.value = false;
  shareCount.value += 1;
  emit("shared", post);
}

async function toggleSave() {
  const next = !isSaved.value;
  isSaved.value = next;
  try {
    if (next) await postService.save(props.post.id);
    else await postService.unsave(props.post.id);
  } catch (e) {
    isSaved.value = !next;
    toasts.error(e);
  }
}
</script>

<template>
  <article class="card p-4 sm:p-5">
    <header class="flex items-center gap-3">
      <RouterLink :to="authorTo" :aria-label="authorDisplay">
        <UserAvatar :name="authorDisplay" :media-id="avatarId" :size="44" />
      </RouterLink>
      <div class="min-w-0">
        <RouterLink :to="authorTo" class="block truncate text-[15px] font-bold text-gray-900 hover:text-brand-600 dark:text-white dark:hover:text-brand-300" dir="auto">
          {{ authorDisplay }}
        </RouterLink>
        <div class="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
          <RouterLink :to="`/posts/${post.id}`" class="hover:underline" :title="fullTime">
            {{ relativeTime(post.created_at) }}
          </RouterLink>
          <span aria-hidden="true">·</span>
          <component :is="audienceIcon" class="h-3 w-3" :title="t(`feed.audience${post.audience === 'only_me' ? 'OnlyMe' : post.audience.charAt(0).toUpperCase() + post.audience.slice(1)}`)" />
          <MessageSquareOff v-if="commentPolicy === 'off'" class="h-3 w-3" :aria-label="t('post.commentsOff')" />
        </div>
      </div>

      <div class="ms-auto flex items-center gap-1">
        <button
          class="rounded-full p-2 text-gray-500 transition hover:bg-gray-100 hover:text-brand-600 dark:hover:bg-gray-800 dark:text-gray-400"
          :class="isSaved ? 'text-brand-600 dark:text-brand-300' : ''"
          :aria-pressed="isSaved"
          :aria-label="t('post.save')"
          :title="t('post.save')"
          @click="toggleSave"
        >
          <Bookmark class="h-5 w-5" :fill="isSaved ? 'currentColor' : 'none'" />
        </button>

        <div class="relative">
          <button
            class="rounded-full p-2 text-gray-500 transition hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:text-gray-400"
            :aria-label="t('profile.more')"
            @click="menuOpen = !menuOpen"
          >
            <MoreHorizontal class="h-5 w-5" />
          </button>
          <template v-if="menuOpen">
            <div class="fixed inset-0 z-40" @click="menuOpen = false" />
            <div class="popover absolute end-0 z-50 mt-1 w-44 p-1.5" role="menu">
              <button
                v-if="canEdit"
                class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800"
                @click="startEdit"
              >
                <PenSquare class="h-4 w-4" /> {{ t("post.edit") }}
              </button>
              <div v-if="isAuthor" role="group" :aria-label="t('post.commentPolicy')" class="my-1 border-y border-gray-100 py-1 dark:border-gray-800">
                <p class="px-3 pb-0.5 pt-1 text-[11px] font-semibold text-gray-500 dark:text-gray-400">{{ t("post.commentPolicy") }}</p>
                <button
                  v-for="p in COMMENT_POLICIES"
                  :key="p"
                  role="menuitemradio"
                  :aria-checked="commentPolicy === p"
                  class="flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-start text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800"
                  :class="commentPolicy === p ? 'font-semibold text-brand-600 dark:text-brand-300' : ''"
                  @click="setPolicy(p)"
                >
                  {{ t(POLICY_LABEL[p]) }}
                </button>
              </div>
              <button
                v-if="isAuthor"
                class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm text-red-600 transition hover:bg-red-50 disabled:opacity-60 dark:hover:bg-red-950/40"
                :disabled="removing"
                @click="remove"
              >
                <Trash2 class="h-4 w-4" /> {{ t("friends.delete") }}
              </button>
              <button
                v-else
                class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800"
                @click="menuOpen = false; showReport = true"
              >
                <Flag class="h-4 w-4" /> {{ t("post.report") }}
              </button>
            </div>
          </template>
        </div>
      </div>
    </header>

    <!-- Edit mode -->
    <div v-if="editing" class="mt-3">
      <textarea v-model="draft" class="input min-h-24 text-[15px]" rows="3" dir="auto" :aria-label="t('post.editBody')" />
      <div class="mt-2 flex justify-end gap-2">
        <button class="btn-ghost" @click="editing = false">{{ t("feed.cancel") }}</button>
        <button class="btn-primary" :disabled="savingEdit" @click="saveEdit">{{ t("post.save") }}</button>
      </div>
    </div>
    <p v-else-if="localBody" class="mt-3 whitespace-pre-wrap break-words text-[15px] leading-relaxed" dir="auto">
      <RichText :body="localBody" />
      <span v-if="edited" class="text-xs text-gray-500 dark:text-gray-400">· {{ t("messages.edited") }}</span>
    </p>

    <LinkPreviewCard v-if="linkPreview && !editing" :preview="linkPreview" />
    <PollCard v-if="post.poll" :post-id="post.id" :poll="post.poll" />
    <SharedPostCard v-if="isShare" :post="post.shared_post" :view-key="post.id" />

    <!-- Report box -->
    <div v-if="showReport" class="mt-3 rounded-xl border border-gray-200 p-3 dark:border-gray-800">
      <p class="mb-2 text-sm font-medium">{{ t("post.reportReason") }}</p>
      <textarea v-model="reportReason" class="input min-h-16" rows="2" dir="auto" :aria-label="t('post.reportReason')" />
      <div class="mt-2 flex justify-end gap-2">
        <button class="btn-ghost" @click="showReport = false">{{ t("feed.cancel") }}</button>
        <button class="btn-primary" :disabled="!reportReason.trim()" @click="submitReport">{{ t("post.report") }}</button>
      </div>
    </div>
    <p v-if="reported" class="mt-2 text-xs font-medium text-green-600">{{ t("post.reportSent") }}</p>

    <MediaGrid v-if="mediaIds.length" :media-ids="mediaIds" :author-name="authorDisplay" @open="viewer.open" />
    <MediaTheater
      v-if="viewer.index.value !== null"
      :media-ids="mediaIds"
      :index="viewer.index.value"
      :author-name="authorDisplay"
      @go="viewer.go"
      @close="viewer.close"
    />

    <div class="mt-3">
      <PostActions
        :my-reaction="myReaction"
        :reaction-count="reactionCount"
        :reaction-counts="reactionCounts"
        :comment-count="commentCount"
        :share-count="shareCount"
        @react="onReact"
        @unreact="onUnreact"
        @comment="toggleComments"
        @share="sharing = !sharing"
        @reactions="showReactions = true"
        @shares="showShares = true"
      />
    </div>
    <ShareBox v-if="sharing" :post="post" @cancel="sharing = false" @shared="onShared" />

    <section
      v-if="commentsMounted"
      v-show="showComments"
      class="mt-3 border-t border-gray-100 pt-3 dark:border-gray-800"
    >
      <CommentList
        :post-id="post.id"
        :post-author-id="post.author_id"
        :policy="commentPolicy"
        :known-names="knownNames"
        @added="commentCount += 1"
        @total="commentCount = $event"
      />
    </section>

    <ReactionsDialog
      v-if="showReactions"
      :post-id="post.id"
      :counts="reactionCounts"
      :total="reactionCount"
      @close="showReactions = false"
    />
    <SharesDialog v-if="showShares" :post-id="post.id" @close="showShares = false" />
  </article>
</template>
