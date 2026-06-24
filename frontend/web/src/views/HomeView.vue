<script lang="ts">
// Explicit name so <KeepAlive include="HomeView"> reliably caches the feed.
export default { name: "HomeView" };
</script>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import AppShell from "@/components/layout/AppShell.vue";
import CreatePostCard from "@/components/post/CreatePostCard.vue";
import PostCard from "@/components/post/PostCard.vue";
import SponsoredCard from "@/components/post/SponsoredCard.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { realtime } from "@/lib/ws";
import { feedService } from "@/services/feed";
import { postService } from "@/services/post";
import type { Post, SponsoredSlot } from "@/types";

const { t } = useI18n();

const posts = ref<Post[]>([]);
const sponsored = ref<SponsoredSlot[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(true);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);

/** The feed delivers a snapshot of each post; render it directly. */
function snapshotToPost(snapshot: Record<string, unknown>, fallbackId: string): Post {
  return {
    id: (snapshot.id as string) ?? fallbackId,
    author_id: (snapshot.author_id as string) ?? "",
    author_type: (snapshot.author_type as string) ?? "user",
    type: (snapshot.type as string) ?? "text",
    // The feed snapshot exposes `excerpt` (truncated body); fall back gracefully.
    body: (snapshot.body as string) ?? (snapshot.excerpt as string) ?? "",
    audience: (snapshot.audience as string) ?? "public",
    media_ids: (snapshot.media_ids as string[]) ?? [],
    reaction_count: (snapshot.reaction_count as number) ?? 0,
    comment_count: (snapshot.comment_count as number) ?? 0,
    share_count: (snapshot.share_count as number) ?? 0,
    created_at: (snapshot.created_at as string) ?? new Date().toISOString(),
  };
}

async function load(initial = false) {
  if (initial) {
    loading.value = true;
    error.value = false;
  } else {
    if (!hasMore.value || loadingMore.value) return;
    loadingMore.value = true;
  }
  try {
    const resp = await feedService.home(initial ? undefined : (cursor.value ?? undefined));
    const mapped = resp.data.map((item) => snapshotToPost(item.snapshot, item.post_id));
    posts.value = initial ? mapped : [...posts.value, ...mapped];
    if (initial) sponsored.value = resp.sponsored ?? [];
    cursor.value = resp.page.next_cursor;
    hasMore.value = resp.page.has_more;
  } catch {
    if (initial) error.value = true;
  } finally {
    loading.value = false;
    loadingMore.value = false;
  }
}

function onCreated(post: Post) {
  posts.value.unshift(post);
}

function onRemoved(id: string) {
  posts.value = posts.value.filter((p) => p.id !== id);
  pending.value = pending.value.filter((p) => p.id !== id);
}

// Real-time: new feed items arrive as `feed.item.added`; stash them and reveal
// via a pill (keeps scroll position instead of jumping).
const pending = ref<Post[]>([]);
let unsubFeed: (() => void) | null = null;

async function onFeedItem(postId: unknown) {
  const id = typeof postId === "string" ? postId : null;
  if (!id) return;
  if (posts.value.some((p) => p.id === id) || pending.value.some((p) => p.id === id)) return;
  try {
    pending.value.unshift(await postService.get(id));
  } catch {
    // Post may be unavailable; ignore.
  }
}

function revealPending() {
  posts.value = [...pending.value, ...posts.value];
  pending.value = [];
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// Infinite scroll: load the next page when the sentinel nears the viewport.
// The manual "load more" button remains as a keyboard/fallback affordance.
const sentinel = ref<HTMLElement | null>(null);
let observer: IntersectionObserver | null = null;

onMounted(() => {
  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0]?.isIntersecting) load(false);
    },
    { rootMargin: "600px" },
  );
  load(true);
  unsubFeed = realtime.on("feed.item.added", (frame) => onFeedItem(frame.post_id));
});

watch(sentinel, (el) => {
  observer?.disconnect();
  if (el) observer?.observe(el);
});

onUnmounted(() => {
  observer?.disconnect();
  unsubFeed?.();
});
</script>

<template>
  <AppShell>
    <div class="mx-auto w-full max-w-[600px] space-y-4">
      <CreatePostCard @created="onCreated" />

      <div v-if="pending.length" class="sticky top-16 z-10 flex justify-center">
        <button
          class="rounded-full bg-brand-600 px-4 py-1.5 text-sm font-medium text-white shadow-lg transition hover:bg-brand-700"
          @click="revealPending"
        >
          ↑ {{ pending.length === 1 ? t("toasts.newPost") : t("toasts.newPosts", { count: pending.length }) }}
        </button>
      </div>

      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="error" @retry="load(true)" />
      <EmptyState v-else-if="posts.length === 0">{{ t("feed.empty") }}</EmptyState>

      <template v-else>
        <template v-for="(post, i) in posts" :key="post.id">
          <PostCard :post="post" @removed="onRemoved" />
          <SponsoredCard
            v-if="i % 5 === 4 && sponsored[Math.floor(i / 5)]"
            :ad="sponsored[Math.floor(i / 5)]"
          />
        </template>

        <div v-if="hasMore" ref="sentinel" class="py-4 text-center">
          <span v-if="loadingMore" class="text-sm text-gray-500">{{ t("states.loading") }}</span>
          <button v-else class="btn-ghost mx-auto block" @click="load(false)">
            {{ t("feed.loadMore") }}
          </button>
        </div>
      </template>
    </div>
  </AppShell>
</template>
