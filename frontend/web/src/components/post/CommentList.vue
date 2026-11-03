<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import CommentInput from "@/components/post/CommentInput.vue";
import CommentItem from "@/components/post/CommentItem.vue";
import {
  addReply,
  type CommentLocator,
  emptyThread,
  locateComment,
  mergeById,
  removeComment,
  replaceComment,
  replyTargetAuthor,
  type Thread,
  threadRootId,
} from "@/lib/commentThreads";
import { type Comment, type CommentPolicy, postService, REPORT_ERRORS } from "@/services/post";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

// A post's comments: roots paged from the post, each thread's replies paged
// from its root (so a reply never lands on a page without its root). Replies to
// replies are filed under the root by the server and labelled "@name" here.
const props = withDefaults(
  defineProps<{
    postId: string;
    postAuthorId: string;
    policy?: CommentPolicy;
    knownNames?: Record<string, string>;
    /** A comment to scroll to and highlight (a notification's `?comment=`). */
    focusId?: string | null;
    /** Its thread root, when the link knows it (`?thread=`). */
    focusRootId?: string | null;
  }>(),
  { policy: "everyone", knownNames: () => ({}), focusId: null, focusRootId: null },
);
const emit = defineEmits<{ added: []; total: [count: number] }>();

const { t } = useI18n();
const auth = useAuthStore();
const directory = useDirectoryStore();
const toasts = useToastStore();

const roots = ref<Comment[]>([]);
const threads = ref<Record<string, Thread>>({});
const cursor = ref<string | null>(null);
const loading = ref(true);
const loadingMore = ref(false);
const submitting = ref(false);
const busyId = ref<string | null>(null);

const me = computed(() => auth.account?.id ?? "");
const isPostAuthor = computed(() => me.value === props.postAuthorId);
const commentsOff = computed(() => props.policy === "off");

function nameFor(id: string): string {
  return props.knownNames[id] || directory.label(id);
}
function threadOf(rootId: string): Thread {
  return threads.value[rootId] ?? emptyThread();
}
function setThread(rootId: string, patch: Partial<Thread>) {
  threads.value = { ...threads.value, [rootId]: { ...threadOf(rootId), ...patch } };
}

async function load() {
  loading.value = true;
  try {
    const page = await postService.comments(props.postId);
    roots.value = page.data;
    cursor.value = page.page.next_cursor;
  } catch (e) {
    toasts.error(e);
  } finally {
    loading.value = false;
  }
}

/** False when nothing was loaded (already loading, at the end, or failed). */
async function loadMore(): Promise<boolean> {
  if (!cursor.value || loadingMore.value) return false;
  loadingMore.value = true;
  try {
    const page = await postService.comments(props.postId, cursor.value);
    // A comment written here while paging can come back from the server too.
    roots.value = mergeById(roots.value, page.data);
    cursor.value = page.page.next_cursor;
    return true;
  } catch (e) {
    toasts.error(e);
    return false;
  } finally {
    loadingMore.value = false;
  }
}

/** Open a thread, loading its next page of replies. False when that failed. */
async function loadReplies(rootId: string): Promise<boolean> {
  const thread = threadOf(rootId);
  if (thread.loaded && !thread.cursor) {
    setThread(rootId, { open: true });
    return true;
  }
  busyId.value = rootId;
  try {
    const page = await postService.replies(rootId, thread.cursor);
    setThread(rootId, {
      open: true,
      loaded: true,
      cursor: page.page.next_cursor,
      replies: mergeById(threadOf(rootId).replies, page.data),
    });
    return true;
  } catch (e) {
    toasts.error(e);
    return false;
  } finally {
    busyId.value = null;
  }
}

// Deep link to one comment: find it (paging roots, then its thread's replies),
// scroll it into view and highlight it briefly.
const highlightId = ref<string | null>(null);
let highlightTimer: number | undefined;
const HIGHLIGHT_MS = 2500;

const locator: CommentLocator = {
  hasRoot: (id: string) => roots.value.some((r) => r.id === id),
  moreRoots: () => (cursor.value ? loadMore() : Promise.resolve(false)),
  roots: () => roots.value,
  thread: (rootId: string) => threadOf(rootId),
  loadReplies,
  setOpen: (rootId: string, open: boolean) => setThread(rootId, { open }),
};

async function reveal(id: string) {
  await nextTick();
  const el = listEl.value?.querySelector<HTMLElement>(`[data-comment-id="${CSS.escape(id)}"]`);
  if (!el) return;
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" });
  el.focus({ preventScroll: true });
  highlightId.value = id;
  window.clearTimeout(highlightTimer);
  highlightTimer = window.setTimeout(() => (highlightId.value = null), HIGHLIGHT_MS);
}

let focusRun = 0;
async function focusComment() {
  const id = props.focusId;
  if (!id) return;
  const run = ++focusRun;
  const found = await locateComment(locator, id, props.focusRootId);
  if (run !== focusRun) return; // a newer link took over
  if (found) await reveal(id);
  else toasts.push({ text: t("post.commentUnavailable"), icon: "error" });
}
onBeforeUnmount(() => window.clearTimeout(highlightTimer));

// Reply composer: one open box at a time, under the thread being answered.
const replyTarget = ref<Comment | null>(null);
const replyRootId = computed(() => (replyTarget.value ? threadRootId(replyTarget.value) : null));
function openReply(c: Comment) {
  replyTarget.value = c;
  const rootId = threadRootId(c);
  if (!threadOf(rootId).open) loadReplies(rootId);
}

async function submitRoot(body: string) {
  if (submitting.value) return;
  submitting.value = true;
  try {
    const created = await postService.addComment(props.postId, body);
    roots.value = mergeById(roots.value, [created]);
    emit("added");
  } catch (e) {
    toasts.error(e);
  } finally {
    submitting.value = false;
  }
}

async function submitReply(body: string) {
  const target = replyTarget.value;
  if (!target || submitting.value) return;
  submitting.value = true;
  try {
    const created = await postService.reply(target.id, body);
    ({ roots: roots.value, threads: threads.value } = addReply(roots.value, threads.value, created));
    replyTarget.value = null;
    emit("added");
  } catch (e) {
    toasts.error(e);
  } finally {
    submitting.value = false;
  }
}

async function edit(c: Comment, body: string) {
  busyId.value = c.id;
  try {
    const updated = await postService.editComment(c.id, body);
    ({ roots: roots.value, threads: threads.value } = replaceComment(roots.value, threads.value, {
      ...c,
      ...updated,
    }));
  } catch (e) {
    toasts.error(e);
  } finally {
    busyId.value = null;
  }
}

async function remove(c: Comment) {
  busyId.value = c.id;
  try {
    const { comment_count } = await postService.deleteComment(c.id);
    ({ roots: roots.value, threads: threads.value } = removeComment(roots.value, threads.value, c));
    if (replyTarget.value && threadRootId(replyTarget.value) === threadRootId(c)) replyTarget.value = null;
    emit("total", comment_count);
  } catch (e) {
    toasts.error(e);
  } finally {
    busyId.value = null;
  }
}

async function react(c: Comment, type: string | null) {
  const before = c;
  const had = !!c.my_reaction;
  const optimistic: Comment = {
    ...c,
    my_reaction: type,
    reaction_count: Math.max(0, (c.reaction_count ?? 0) + (type && !had ? 1 : !type && had ? -1 : 0)),
  };
  ({ roots: roots.value, threads: threads.value } = replaceComment(roots.value, threads.value, optimistic));
  try {
    if (type) {
      const count = await postService.reactComment(c.id, type);
      ({ roots: roots.value, threads: threads.value } = replaceComment(roots.value, threads.value, {
        ...optimistic,
        reaction_count: count,
      }));
    } else {
      await postService.unreactComment(c.id);
    }
  } catch (e) {
    ({ roots: roots.value, threads: threads.value } = replaceComment(roots.value, threads.value, before));
    toasts.error(e);
  }
}

// Marked reported only once the server took it (a throttled report was not sent).
const reportedIds = ref(new Set<string>());
async function report(c: Comment, reason: string) {
  try {
    await postService.reportComment(c.id, reason);
    reportedIds.value = new Set(reportedIds.value).add(c.id);
  } catch (e) {
    toasts.error(e, REPORT_ERRORS);
  }
}

function replyToName(c: Comment): string | null {
  const author = replyTargetAuthor(c);
  return author ? nameFor(author) : null;
}

const listEl = ref<HTMLElement | null>(null);

onMounted(async () => {
  await load();
  await focusComment();
});
watch(
  () => [props.focusId, props.focusRootId],
  () => {
    if (!loading.value) void focusComment();
  },
);
</script>

<template>
  <div ref="listEl" class="space-y-3">
    <p v-if="commentsOff" class="rounded-xl bg-gray-50 px-3 py-2 text-xs text-gray-500 dark:bg-gray-800/60 dark:text-gray-400" data-testid="comments-off">
      {{ t("post.commentsOff") }}
    </p>
    <template v-else>
      <p v-if="policy === 'friends' && !isPostAuthor" class="px-1 text-xs text-gray-500 dark:text-gray-400">
        {{ t("post.commentsFriendsOnly") }}
      </p>
      <CommentInput :submitting="submitting" @submit="submitRoot" />
    </template>

    <p v-if="loading" class="px-1 text-xs text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</p>
    <p v-else-if="!roots.length && !commentsOff" class="px-1 text-xs text-gray-500 dark:text-gray-400">{{ t("post.noComments") }}</p>

    <div v-for="root in roots" :key="root.id" class="space-y-2">
      <CommentItem
        :comment="root"
        :name="nameFor(root.author_id)"
        :can-edit="root.author_id === me"
        :can-delete="root.author_id === me || isPostAuthor"
        :can-reply="!commentsOff"
        :busy="busyId === root.id"
        :highlighted="highlightId === root.id"
        :reported="reportedIds.has(root.id)"
        @reply="openReply(root)"
        @edit="edit(root, $event)"
        @remove="remove(root)"
        @react="react(root, $event)"
        @report="report(root, $event)"
      />

      <div class="ms-10 space-y-2">
        <button
          v-if="(root.reply_count ?? 0) > 0 && !threadOf(root.id).open"
          class="text-xs font-semibold text-brand-600 hover:underline dark:text-brand-300"
          :disabled="busyId === root.id"
          @click="loadReplies(root.id)"
        >
          {{ t("post.viewReplies", root.reply_count ?? 0) }}
        </button>

        <div v-if="threadOf(root.id).open" class="space-y-2 border-s border-gray-200 ps-3 dark:border-gray-700">
          <CommentItem
            v-for="r in threadOf(root.id).replies"
            :key="r.id"
            small
            :comment="r"
            :name="nameFor(r.author_id)"
            :reply-to-name="replyToName(r)"
            :can-edit="r.author_id === me"
            :can-delete="r.author_id === me || isPostAuthor"
            :can-reply="!commentsOff"
            :busy="busyId === r.id"
            :highlighted="highlightId === r.id"
            :reported="reportedIds.has(r.id)"
            @reply="openReply(r)"
            @edit="edit(r, $event)"
            @remove="remove(r)"
            @react="react(r, $event)"
            @report="report(r, $event)"
          />
          <div class="flex gap-3">
            <button
              v-if="threadOf(root.id).cursor"
              class="text-xs font-semibold text-brand-600 hover:underline dark:text-brand-300"
              :disabled="busyId === root.id"
              @click="loadReplies(root.id)"
            >
              {{ busyId === root.id ? t("states.loading") : t("post.moreReplies") }}
            </button>
            <button class="text-xs font-semibold text-gray-500 hover:underline dark:text-gray-400" @click="setThread(root.id, { open: false })">
              {{ t("post.hideReplies") }}
            </button>
          </div>
        </div>

        <div v-if="replyRootId === root.id && replyTarget">
          <div class="mb-1 flex items-center gap-2 ps-2 text-[11px] text-gray-500 dark:text-gray-400">
            <span>{{ t("post.replyingTo", { name: nameFor(replyTarget.author_id) }) }}</span>
            <button class="font-semibold text-red-500 hover:underline" :aria-label="t('post.cancelReply')" @click="replyTarget = null">×</button>
          </div>
          <CommentInput :submitting="submitting" :autofocus="true" :placeholder="t('post.replyPlaceholder')" @submit="submitReply" />
        </div>
      </div>
    </div>

    <button
      v-if="cursor"
      class="text-xs font-semibold text-brand-600 hover:underline dark:text-brand-300"
      :disabled="loadingMore"
      @click="loadMore"
    >
      {{ loadingMore ? t("states.loading") : t("post.moreComments") }}
    </button>
  </div>
</template>
