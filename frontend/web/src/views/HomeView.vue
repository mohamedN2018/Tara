<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import AppShell from "@/components/layout/AppShell.vue";
import PostCard from "@/components/post/PostCard.vue";
import PostComposer from "@/components/post/PostComposer.vue";
import SponsoredCard from "@/components/post/SponsoredCard.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { feedService } from "@/services/feed";
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
    body: (snapshot.body as string) ?? "",
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

onMounted(() => load(true));
</script>

<template>
  <AppShell>
    <div class="space-y-4">
      <PostComposer @created="onCreated" />

      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="error" @retry="load(true)" />
      <EmptyState v-else-if="posts.length === 0">{{ t("feed.empty") }}</EmptyState>

      <template v-else>
        <template v-for="(post, i) in posts" :key="post.id">
          <PostCard :post="post" />
          <SponsoredCard
            v-if="i % 5 === 4 && sponsored[Math.floor(i / 5)]"
            :ad="sponsored[Math.floor(i / 5)]"
          />
        </template>

        <button
          v-if="hasMore"
          class="btn-ghost mx-auto block"
          :disabled="loadingMore"
          @click="load(false)"
        >
          {{ loadingMore ? t("states.loading") : t("feed.loadMore") }}
        </button>
      </template>
    </div>
  </AppShell>
</template>
