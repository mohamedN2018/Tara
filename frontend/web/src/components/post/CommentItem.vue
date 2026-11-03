<script setup lang="ts">
import { Flag, MoreHorizontal, PenSquare, Trash2 } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import RichText from "@/components/post/RichText.vue";
import { relativeTime } from "@/lib/format";
import { reactionByKey } from "@/lib/reactions";
import { useEscapeKey } from "@/lib/useEscapeKey";
import type { Comment } from "@/services/post";
import { useDirectoryStore } from "@/stores/directory";

// One comment bubble with its actions. The parent list does the API calls.
const props = withDefaults(
  defineProps<{
    comment: Comment;
    name: string;
    /** "@name" shown before a reply that answers another reply. */
    replyToName?: string | null;
    canEdit?: boolean;
    canDelete?: boolean;
    canReply?: boolean;
    busy?: boolean;
    small?: boolean;
    /** The comment a link pointed at, briefly marked after scrolling to it. */
    highlighted?: boolean;
    /** The server accepted this viewer's report. */
    reported?: boolean;
  }>(),
  {
    replyToName: null,
    canEdit: false,
    canDelete: false,
    canReply: true,
    busy: false,
    small: false,
    highlighted: false,
    reported: false,
  },
);
const emit = defineEmits<{
  reply: [];
  edit: [body: string];
  remove: [];
  react: [type: string | null];
  report: [reason: string];
}>();

const { t } = useI18n();
const directory = useDirectoryStore();

const reaction = computed(() => reactionByKey(props.comment.my_reaction));
const menuOpen = ref(false);
useEscapeKey(menuOpen, () => (menuOpen.value = false));

const editing = ref(false);
const draft = ref("");
function startEdit() {
  menuOpen.value = false;
  draft.value = props.comment.body;
  editing.value = true;
}
function saveEdit() {
  const body = draft.value.trim();
  if (!body) return;
  emit("edit", body);
  editing.value = false;
}

const reporting = ref(false);
const reason = ref("");
function sendReport() {
  const value = reason.value.trim();
  if (!value) return;
  emit("report", value);
  reporting.value = false;
  reason.value = "";
}

function toggleLike() {
  emit("react", props.comment.my_reaction ? null : "like");
}
</script>

<template>
  <div
    class="-m-1 flex items-start gap-2 rounded-2xl p-1 outline-none motion-safe:transition-colors motion-safe:duration-700"
    :class="highlighted ? 'bg-brand-50 ring-2 ring-brand-400 dark:bg-brand-950/40' : ''"
    :data-comment-id="comment.id"
    :data-highlighted="highlighted || undefined"
    tabindex="-1"
  >
    <RouterLink :to="{ name: 'profile-by-id', params: { id: comment.author_id } }" :aria-label="name" class="shrink-0">
      <UserAvatar :name="name" :media-id="directory.avatarOf(comment.author_id)" :size="small ? 26 : 32" />
    </RouterLink>
    <div class="min-w-0 flex-1">
      <div v-if="editing" class="space-y-2">
        <textarea v-model="draft" class="input min-h-16 text-sm" rows="2" dir="auto" :aria-label="t('post.commentEditLabel')" @keydown.esc.stop="editing = false" />
        <div class="flex justify-end gap-2">
          <button class="btn-ghost px-3 py-1.5" @click="editing = false">{{ t("feed.cancel") }}</button>
          <button class="btn-primary px-3 py-1.5" :disabled="busy || !draft.trim()" @click="saveEdit">{{ t("post.saveComment") }}</button>
        </div>
      </div>
      <div v-else class="flex items-start gap-1">
        <div class="relative inline-block min-w-0 rounded-2xl bg-gray-100 px-3 py-1.5 dark:bg-gray-800">
          <RouterLink :to="{ name: 'profile-by-id', params: { id: comment.author_id } }" class="block text-xs font-semibold hover:underline" dir="auto">{{ name }}</RouterLink>
          <span class="whitespace-pre-wrap break-words text-sm" dir="auto">
            <span v-if="replyToName" class="font-medium text-brand-600 dark:text-brand-300">@{{ replyToName }} </span><RichText :body="comment.body" />
          </span>
          <span
            v-if="comment.reaction_count"
            class="absolute -bottom-2 end-1 inline-flex items-center gap-0.5 rounded-full bg-white px-1.5 text-[11px] shadow-card ring-1 ring-gray-200 dark:bg-gray-900 dark:ring-gray-700"
            :aria-label="t('post.reactionsCount', comment.reaction_count)"
          ><span aria-hidden="true">{{ reaction?.emoji ?? "👍" }}</span><span class="tabular-nums">{{ comment.reaction_count }}</span></span>
        </div>

        <div class="relative shrink-0 self-center">
          <button
            class="rounded-full p-1 text-gray-400 transition hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-200"
            :aria-label="t('post.commentMenu')"
            :aria-expanded="menuOpen"
            @click="menuOpen = !menuOpen"
          >
            <MoreHorizontal class="h-4 w-4" />
          </button>
          <template v-if="menuOpen">
            <div class="fixed inset-0 z-40" @click="menuOpen = false" />
            <div class="popover absolute end-0 z-50 mt-1 w-40 p-1.5" role="menu">
              <button v-if="canEdit" role="menuitem" class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800" @click="startEdit">
                <PenSquare class="h-4 w-4" /> {{ t("post.editComment") }}
              </button>
              <button v-if="canDelete" role="menuitem" class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm text-red-600 transition hover:bg-red-50 dark:hover:bg-red-950/40" :disabled="busy" @click="menuOpen = false; emit('remove')">
                <Trash2 class="h-4 w-4" /> {{ t("post.deleteComment") }}
              </button>
              <button v-if="!canEdit" role="menuitem" class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800" @click="menuOpen = false; reporting = true">
                <Flag class="h-4 w-4" /> {{ t("post.reportComment") }}
              </button>
            </div>
          </template>
        </div>
      </div>

      <div v-if="!editing" class="mt-1 flex items-center gap-3 ps-2 text-[11px] text-gray-500 dark:text-gray-400">
        <time :datetime="comment.created_at">{{ relativeTime(comment.created_at) }}</time>
        <button
          class="font-semibold hover:underline"
          :class="reaction ? reaction.color : ''"
          :aria-pressed="!!reaction"
          @click="toggleLike"
        >
          {{ reaction ? t(reaction.labelKey) : t("post.like") }}
        </button>
        <button v-if="canReply" class="font-semibold hover:underline" @click="emit('reply')">{{ t("post.reply") }}</button>
        <span v-if="comment.edited_at">{{ t("post.edited") }}</span>
      </div>

      <div v-if="reporting" class="mt-2 rounded-xl border border-gray-200 p-2 dark:border-gray-800">
        <label :for="`report-${comment.id}`" class="mb-1 block text-xs font-medium">{{ t("post.reportCommentReason") }}</label>
        <textarea :id="`report-${comment.id}`" v-model="reason" class="input min-h-12 text-sm" rows="2" dir="auto" maxlength="200" />
        <div class="mt-2 flex justify-end gap-2">
          <button class="btn-ghost px-3 py-1.5" @click="reporting = false">{{ t("feed.cancel") }}</button>
          <button class="btn-primary px-3 py-1.5" :disabled="!reason.trim()" @click="sendReport">{{ t("post.report") }}</button>
        </div>
      </div>
      <p v-if="reported" class="mt-1 ps-2 text-[11px] font-medium text-green-600">{{ t("post.reportSent") }}</p>
    </div>
  </div>
</template>
