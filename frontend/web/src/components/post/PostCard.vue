<script setup lang="ts">
import { Bookmark, Flag, Globe, Lock, MoreHorizontal, PenSquare, Trash2, UserCheck, Users } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { RouteLocationRaw } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import CommentInput from "@/components/post/CommentInput.vue";
import CommentList from "@/components/post/CommentList.vue";
import PostActions from "@/components/post/PostActions.vue";
import { apiError } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useMediaUrls } from "@/lib/useMediaUrl";
import { type Comment, postService } from "@/services/post";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import type { Post } from "@/types";

const props = withDefaults(
  defineProps<{
    post: Post;
    authorName?: string;
    authorHandle?: string;
    authorAvatar?: string | null;
    saved?: boolean;
    startCommentsOpen?: boolean;
  }>(),
  { saved: false, startCommentsOpen: false },
);
const emit = defineEmits<{ removed: [id: string] }>();

const { t } = useI18n();
const auth = useAuthStore();
const directory = useDirectoryStore();

const authorDisplay = computed(
  () => props.authorName || directory.nameOf(props.post.author_id) || props.post.author_id.slice(0, 12),
);
// Always navigate by account id (post.author_id) — that route loads the
// author's posts. The handle route can't resolve posts for other users.
const authorTo = computed<RouteLocationRaw>(() => ({
  name: "profile-by-id",
  params: { id: props.post.author_id },
  query: { name: props.authorName || directory.nameOf(props.post.author_id) || undefined },
}));
const isAuthor = computed(() => auth.account?.id === props.post.author_id);

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
    alert(apiError(e).message);
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
  } catch (e) {
    alert(apiError(e).message);
  } finally {
    savingEdit.value = false;
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
  } catch {
    /* ignore */
  }
}

const myReaction = ref<string | null>(null);
const isSaved = ref(props.saved);
const reactionCount = ref(props.post.reaction_count);
const commentCount = ref(props.post.comment_count);
const shareCount = ref(props.post.share_count);
const showComments = ref(false);
const comments = ref<Comment[]>([]);
const loadingComments = ref(false);
const submitting = ref(false);

const images = useMediaUrls(() => props.post.media_ids);

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
  if (prev === null) reactionCount.value += 1;
  myReaction.value = type;
  try {
    await postService.react(props.post.id, type);
  } catch {
    myReaction.value = prev;
    if (prev === null) reactionCount.value -= 1;
  }
}

async function onUnreact() {
  const prev = myReaction.value;
  if (prev === null) return;
  myReaction.value = null;
  reactionCount.value -= 1;
  try {
    await postService.unreact(props.post.id);
  } catch {
    myReaction.value = prev;
    reactionCount.value += 1;
  }
}

onMounted(() => {
  if (props.startCommentsOpen) toggleComments();
});

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

async function submitComment(body: string) {
  if (submitting.value) return;
  submitting.value = true;
  try {
    const created = await postService.addComment(props.post.id, body);
    comments.value.push(created);
    commentCount.value += 1;
  } catch (e) {
    alert(apiError(e).message);
  } finally {
    submitting.value = false;
  }
}

async function submitReply({ targetId, body }: { targetId: string; body: string }) {
  if (submitting.value) return;
  submitting.value = true;
  try {
    const created = await postService.reply(targetId, body);
    comments.value.push(created);
    commentCount.value += 1;
  } catch (e) {
    alert(apiError(e).message);
  } finally {
    submitting.value = false;
  }
}

async function share() {
  try {
    await postService.share(props.post.id);
    shareCount.value += 1;
  } catch {
    // Share endpoint may be unavailable; keep the UI responsive.
  }
}

async function toggleSave() {
  const next = !isSaved.value;
  isSaved.value = next;
  try {
    if (next) await postService.save(props.post.id);
    else await postService.unsave(props.post.id);
  } catch {
    isSaved.value = !next;
  }
}
</script>

<template>
  <article class="card p-4">
    <header class="flex items-center gap-3">
      <RouterLink :to="authorTo">
        <UserAvatar :name="authorDisplay" :media-id="authorAvatar" :size="40" />
      </RouterLink>
      <div class="min-w-0">
        <RouterLink :to="authorTo" class="block truncate text-sm font-semibold hover:underline">
          {{ authorDisplay }}
        </RouterLink>
        <div class="flex items-center gap-1 text-xs text-gray-500">
          <RouterLink :to="`/posts/${post.id}`" class="hover:underline" :title="fullTime">
            {{ relativeTime(post.created_at) }}
          </RouterLink>
          <span aria-hidden="true">·</span>
          <component :is="audienceIcon" class="h-3 w-3" :title="t(`feed.audience${post.audience === 'only_me' ? 'OnlyMe' : post.audience.charAt(0).toUpperCase() + post.audience.slice(1)}`)" />
        </div>
      </div>

      <div class="ms-auto flex items-center gap-1">
        <button
          class="rounded-full p-2 text-gray-400 transition hover:bg-gray-100 hover:text-brand-600 dark:hover:bg-gray-800"
          :class="isSaved ? 'text-brand-600' : ''"
          :aria-pressed="isSaved"
          :aria-label="t('post.save')"
          :title="t('post.save')"
          @click="toggleSave"
        >
          <Bookmark class="h-5 w-5" :fill="isSaved ? 'currentColor' : 'none'" />
        </button>

        <div class="relative">
          <button
            class="rounded-full p-2 text-gray-400 transition hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800"
            :aria-label="t('profile.more')"
            @click="menuOpen = !menuOpen"
          >
            <MoreHorizontal class="h-5 w-5" />
          </button>
          <template v-if="menuOpen">
            <div class="fixed inset-0 z-40" @click="menuOpen = false" />
            <div class="card absolute end-0 z-50 mt-1 w-44 p-1.5" role="menu">
              <button
                v-if="isAuthor"
                class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800"
                @click="startEdit"
              >
                <PenSquare class="h-4 w-4" /> {{ t("post.edit") }}
              </button>
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
      <textarea v-model="draft" class="input min-h-24 text-[15px]" rows="3" />
      <div class="mt-2 flex justify-end gap-2">
        <button class="btn-ghost" @click="editing = false">{{ t("feed.cancel") }}</button>
        <button class="btn-primary" :disabled="savingEdit" @click="saveEdit">{{ t("post.save") }}</button>
      </div>
    </div>
    <p v-else-if="localBody" class="mt-3 whitespace-pre-wrap text-[15px] leading-relaxed">
      {{ localBody }}
      <span v-if="edited" class="text-xs text-gray-400">· {{ t("messages.edited") }}</span>
    </p>

    <!-- Report box -->
    <div v-if="showReport" class="mt-3 rounded-xl border border-gray-200 p-3 dark:border-gray-800">
      <p class="mb-2 text-sm font-medium">{{ t("post.reportReason") }}</p>
      <textarea v-model="reportReason" class="input min-h-16" rows="2" />
      <div class="mt-2 flex justify-end gap-2">
        <button class="btn-ghost" @click="showReport = false">{{ t("feed.cancel") }}</button>
        <button class="btn-primary" :disabled="!reportReason.trim()" @click="submitReport">{{ t("post.report") }}</button>
      </div>
    </div>
    <p v-if="reported" class="mt-2 text-xs font-medium text-green-600">{{ t("post.reportSent") }}</p>

    <div
      v-if="images.length"
      class="mt-3 grid gap-1.5 overflow-hidden rounded-xl"
      :class="images.length === 1 ? 'grid-cols-1' : 'grid-cols-2'"
    >
      <img
        v-for="(src, i) in images"
        :key="i"
        :src="src"
        class="max-h-96 w-full object-cover"
        loading="lazy"
        decoding="async"
        alt=""
      />
    </div>

    <div class="mt-3">
      <PostActions
        :my-reaction="myReaction"
        :reaction-count="reactionCount"
        :comment-count="commentCount"
        :share-count="shareCount"
        @react="onReact"
        @unreact="onUnreact"
        @comment="toggleComments"
        @share="share"
      />
    </div>

    <section v-if="showComments" class="mt-3 space-y-3 border-t border-gray-100 pt-3 dark:border-gray-800">
      <CommentInput :submitting="submitting" @submit="submitComment" />
      <CommentList
        :comments="comments"
        :loading="loadingComments"
        :submitting="submitting"
        :known-names="knownNames"
        @reply="submitReply"
      />
    </section>
  </article>
</template>
