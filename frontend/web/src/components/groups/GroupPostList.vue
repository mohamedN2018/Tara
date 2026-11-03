<script setup lang="ts">
import { Check, X } from "lucide-vue-next";
import { onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import PostCard from "@/components/post/PostCard.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { type Group, type GroupFeedView, groupPostsService } from "@/services/groups";
import { useToastStore } from "@/stores/toasts";
import type { Post } from "@/types";

// One of the group's post lists (discussion, featured, pending). Pending posts
// get approve and decline buttons when the viewer may review them.
const props = withDefaults(defineProps<{ group: Group; view?: GroupFeedView; version?: number }>(), {
  view: "discussion",
  version: 0,
});
const emit = defineEmits<{ reviewed: [] }>();

const { t } = useI18n();
const toasts = useToastStore();
const posts = ref<Post[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);
const busy = ref<string | null>(null);
let generation = 0;

async function load() {
  const run = ++generation;
  loading.value = true;
  error.value = false;
  try {
    const page = await groupPostsService.feed(props.group.id, props.view);
    if (run !== generation) return;
    posts.value = page.data;
    cursor.value = page.page.next_cursor;
  } catch {
    if (run === generation) error.value = true;
  } finally {
    if (run === generation) loading.value = false;
  }
}

async function loadMore() {
  if (!cursor.value || loadingMore.value) return;
  loadingMore.value = true;
  try {
    const page = await groupPostsService.feed(props.group.id, props.view, cursor.value);
    posts.value = [...posts.value, ...page.data];
    cursor.value = page.page.next_cursor;
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

function drop(id: string) {
  posts.value = posts.value.filter((p) => p.id !== id);
}

async function review(post: Post, approve: boolean) {
  if (busy.value) return;
  busy.value = post.id;
  try {
    if (approve) await groupPostsService.approve(post.id);
    else await groupPostsService.decline(post.id);
    drop(post.id);
    toasts.success(t(approve ? "groups.post.approved" : "groups.post.declined"));
    emit("reviewed");
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = null;
  }
}

function onPinned(id: string, pinned: boolean) {
  if (props.view === "featured" && !pinned) drop(id);
}

/** A post the viewer just wrote: shown at the top of the discussion. */
function prepend(post: Post) {
  if (props.view !== "discussion" || post.approval_state === "pending") return;
  // A first load that failed (a just-approved member, before post's read model
  // caught up) is retried: posting already confirmed the membership.
  if (error.value) void load();
  else posts.value = [post, ...posts.value];
}
defineExpose({ prepend, reload: load });

watch(() => [props.group.id, props.view, props.version], load);
onMounted(load);
</script>

<template>
  <div class="space-y-4">
    <LoadingSkeleton v-if="loading" :rows="2" />
    <ErrorState v-else-if="error" @retry="load" />
    <EmptyState v-else-if="!posts.length">{{ t(`groups.empty.posts_${view}`) }}</EmptyState>
    <template v-else>
      <div v-for="post in posts" :key="post.id" class="space-y-2" data-testid="group-post">
        <PostCard
          :post="post"
          :group-moderator="!!group.viewer.can.moderate"
          :group-can-pin="!!group.viewer.can.pin"
          @removed="drop"
          @pinned="onPinned"
        />
        <div
          v-if="view === 'pending' && group.viewer.can.approve_posts"
          class="flex justify-end gap-2"
          role="group"
          :aria-label="t('groups.post.reviewLabel')"
        >
          <button type="button" class="btn-outline" :disabled="busy === post.id" @click="review(post, false)">
            <X class="h-4 w-4" aria-hidden="true" /> {{ t("groups.post.decline") }}
          </button>
          <button type="button" class="btn-primary" :disabled="busy === post.id" @click="review(post, true)">
            <Check class="h-4 w-4" aria-hidden="true" /> {{ t("groups.post.approve") }}
          </button>
        </div>
      </div>
      <button v-if="cursor" class="btn-ghost mx-auto block" :disabled="loadingMore" @click="loadMore">
        {{ loadingMore ? t("states.loading") : t("states.loadMore") }}
      </button>
    </template>
  </div>
</template>
