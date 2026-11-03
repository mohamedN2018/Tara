<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import CommentInput from "@/components/post/CommentInput.vue";
import RichText from "@/components/post/RichText.vue";
import { relativeTime } from "@/lib/format";
import type { Comment } from "@/services/post";
import { useDirectoryStore } from "@/stores/directory";

const props = withDefaults(
  defineProps<{
    comments: Comment[];
    loading?: boolean;
    submitting?: boolean;
    knownNames?: Record<string, string>;
  }>(),
  { loading: false, submitting: false, knownNames: () => ({}) },
);
const emit = defineEmits<{ reply: [payload: { targetId: string; body: string }] }>();
const { t } = useI18n();
const directory = useDirectoryStore();

function nameFor(id: string): string {
  return props.knownNames[id] || directory.label(id);
}

interface ReplyView extends Comment {
  toName: string; // who this reply is directed at, when not the thread root
}
interface Thread {
  root: Comment;
  replies: ReplyView[];
}

// The API returns every comment flat (each with parent_id). Fold them into
// two visual levels: a root comment + all of its descendant replies.
const threads = computed<Thread[]>(() => {
  const byId = new Map(props.comments.map((c) => [c.id, c]));
  const rootOf = (c: Comment): Comment => {
    let cur = c;
    let guard = 0;
    while (cur.parent_id && byId.has(cur.parent_id) && guard++ < 50) {
      cur = byId.get(cur.parent_id) as Comment;
    }
    return cur;
  };

  const order: Comment[] = [];
  const repliesByRoot = new Map<string, ReplyView[]>();
  for (const c of props.comments) {
    const isRoot = !c.parent_id || !byId.has(c.parent_id);
    if (isRoot) {
      order.push(c);
      if (!repliesByRoot.has(c.id)) repliesByRoot.set(c.id, []);
    }
  }
  for (const c of props.comments) {
    const isRoot = !c.parent_id || !byId.has(c.parent_id);
    if (isRoot) continue;
    const root = rootOf(c);
    const directParent = c.parent_id ? byId.get(c.parent_id) : undefined;
    const toName = directParent && directParent.id !== root.id ? nameFor(directParent.author_id) : "";
    const list = repliesByRoot.get(root.id) ?? [];
    list.push({ ...c, toName });
    repliesByRoot.set(root.id, list);
  }

  const byTime = (a: Comment, b: Comment) => (a.created_at < b.created_at ? -1 : 1);
  return order
    .sort(byTime)
    .map((root) => ({ root, replies: (repliesByRoot.get(root.id) ?? []).sort(byTime) }));
});

// Reply composer state (one open box at a time).
const replyTargetId = ref<string | null>(null);
const replyTargetName = ref("");
const replyRootId = ref<string | null>(null);
const expanded = ref<Set<string>>(new Set());

function rootIdOf(commentId: string): string {
  const byId = new Map(props.comments.map((c) => [c.id, c]));
  let cur = byId.get(commentId);
  let guard = 0;
  while (cur?.parent_id && byId.has(cur.parent_id) && guard++ < 50) {
    cur = byId.get(cur.parent_id);
  }
  return cur?.id ?? commentId;
}

function openReply(c: Comment) {
  replyTargetId.value = c.id;
  replyTargetName.value = nameFor(c.author_id);
  replyRootId.value = rootIdOf(c.id);
  expanded.value.add(replyRootId.value);
}
function cancelReply() {
  replyTargetId.value = null;
  replyRootId.value = null;
}
function submitReply(body: string) {
  if (!replyTargetId.value) return;
  emit("reply", { targetId: replyTargetId.value, body });
  cancelReply();
}
function toggle(rootId: string) {
  if (expanded.value.has(rootId)) expanded.value.delete(rootId);
  else expanded.value.add(rootId);
}
</script>

<template>
  <div class="space-y-3">
    <p v-if="loading" class="px-1 text-xs text-gray-500">{{ t("states.loading") }}</p>
    <p v-else-if="!threads.length" class="px-1 text-xs text-gray-400">{{ t("post.noComments") }}</p>

    <div v-for="th in threads" :key="th.root.id" class="space-y-2">
      <!-- Root comment -->
      <div class="flex items-start gap-2">
        <UserAvatar :name="nameFor(th.root.author_id)" :media-id="directory.avatarOf(th.root.author_id)" :size="32" />
        <div class="min-w-0 flex-1">
          <div class="inline-block rounded-2xl bg-gray-100 px-3 py-1.5 dark:bg-gray-800">
            <span class="block text-xs font-semibold" dir="auto">{{ nameFor(th.root.author_id) }}</span>
            <span class="whitespace-pre-wrap break-words text-sm" dir="auto"><RichText :body="th.root.body" /></span>
          </div>
          <div class="mt-0.5 flex items-center gap-3 ps-2 text-[11px] text-gray-400">
            <time>{{ relativeTime(th.root.created_at) }}</time>
            <button class="font-semibold text-gray-500 hover:underline" @click="openReply(th.root)">
              {{ t("post.reply") }}
            </button>
          </div>

          <!-- Replies toggle -->
          <button
            v-if="th.replies.length && !expanded.has(th.root.id)"
            class="mt-1 ps-2 text-xs font-semibold text-brand-600 hover:underline"
            @click="toggle(th.root.id)"
          >
            {{ t("post.viewReplies", th.replies.length) }}
          </button>

          <!-- Replies -->
          <div v-if="expanded.has(th.root.id)" class="mt-2 space-y-2 border-s border-gray-200 ps-3 dark:border-gray-700">
            <div v-for="r in th.replies" :key="r.id" class="flex items-start gap-2">
              <UserAvatar :name="nameFor(r.author_id)" :media-id="directory.avatarOf(r.author_id)" :size="26" />
              <div class="min-w-0">
                <div class="inline-block rounded-2xl bg-gray-100 px-3 py-1.5 dark:bg-gray-800">
                  <span class="block text-xs font-semibold" dir="auto">{{ nameFor(r.author_id) }}</span>
                  <span class="whitespace-pre-wrap break-words text-sm" dir="auto">
                    <span v-if="r.toName" class="font-medium text-brand-600">@{{ r.toName }} </span><RichText :body="r.body" />
                  </span>
                </div>
                <div class="mt-0.5 flex items-center gap-3 ps-2 text-[11px] text-gray-400">
                  <time>{{ relativeTime(r.created_at) }}</time>
                  <button class="font-semibold text-gray-500 hover:underline" @click="openReply(r)">
                    {{ t("post.reply") }}
                  </button>
                </div>
              </div>
            </div>

            <button
              class="text-xs font-semibold text-gray-400 hover:underline"
              @click="toggle(th.root.id)"
            >
              {{ t("post.hideReplies") }}
            </button>
          </div>

          <!-- Reply composer for this thread -->
          <div v-if="replyRootId === th.root.id" class="mt-2">
            <div class="mb-1 flex items-center gap-2 ps-2 text-[11px] text-gray-500">
              <span>{{ t("post.replyingTo", { name: replyTargetName }) }}</span>
              <button class="font-semibold text-red-500 hover:underline" :aria-label="t('post.cancelReply')" @click="cancelReply">×</button>
            </div>
            <CommentInput
              :submitting="submitting"
              :autofocus="true"
              :placeholder="t('post.replyPlaceholder')"
              @submit="submitReply"
            />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
