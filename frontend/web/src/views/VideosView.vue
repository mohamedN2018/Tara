<script setup lang="ts">
import { Video } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import AppShell from "@/components/layout/AppShell.vue";
import PostCard from "@/components/post/PostCard.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { postService } from "@/services/post";
import { useToastStore } from "@/stores/toasts";
import type { Post } from "@/types";

// Video posts the viewer may see, newest first (GET /posts/?type=video). A page
// can come back short after visibility filtering, so "Load more" keeps paging.
const { t } = useI18n();
const toasts = useToastStore();

const posts = ref<Post[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);

async function load(initial = false) {
  if (initial) {
    loading.value = true;
    error.value = false;
  } else {
    if (loadingMore.value || !hasMore.value) return;
    loadingMore.value = true;
  }
  try {
    const page = await postService.videos(initial ? null : cursor.value);
    const known = new Set(initial ? [] : posts.value.map((p) => p.id));
    const fresh = page.data.filter((p) => !known.has(p.id));
    posts.value = initial ? fresh : [...posts.value, ...fresh];
    cursor.value = page.page.next_cursor;
    hasMore.value = !!page.page.has_more && !!page.page.next_cursor;
  } catch (e) {
    if (initial) error.value = true;
    else toasts.error(e);
  } finally {
    loading.value = false;
    loadingMore.value = false;
  }
}

function onRemoved(id: string) {
  posts.value = posts.value.filter((p) => p.id !== id);
}

onMounted(() => load(true));
</script>

<template>
  <AppShell>
    <div class="mx-auto w-full max-w-[680px] space-y-4">
      <header class="card flex items-center gap-3 p-4">
        <span class="inline-flex h-10 w-10 items-center justify-center rounded-full bg-brand-50 text-brand-600 dark:bg-brand-950/60 dark:text-brand-300">
          <Video class="h-5 w-5" aria-hidden="true" />
        </span>
        <div>
          <h1 class="text-xl font-bold">{{ t("postsFeed.videos.title") }}</h1>
          <p class="text-sm text-gray-500 dark:text-gray-400">{{ t("postsFeed.videos.hint") }}</p>
        </div>
      </header>

      <LoadingSkeleton v-if="loading" :rows="2" />
      <ErrorState v-else-if="error" @retry="load(true)" />
      <template v-else>
        <EmptyState v-if="!posts.length && !hasMore">{{ t("postsFeed.videos.empty") }}</EmptyState>
        <PostCard v-for="p in posts" :key="p.id" :post="p" @removed="onRemoved" />
        <div v-if="hasMore" class="py-2 text-center">
          <button class="btn-ghost mx-auto" :disabled="loadingMore" @click="load(false)">
            {{ loadingMore ? t("states.loading") : t("postsFeed.videos.loadMore") }}
          </button>
        </div>
      </template>
    </div>
  </AppShell>
</template>
