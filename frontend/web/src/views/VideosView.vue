<script setup lang="ts">
import { Video } from "lucide-vue-next";
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import FeedCardSkeleton from "@/components/feed/FeedCardSkeleton.vue";
import FeedRetryCard from "@/components/feed/FeedRetryCard.vue";
import AppShell from "@/components/layout/AppShell.vue";
import PostCard from "@/components/post/PostCard.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import { delivery, loadDelivery } from "@/lib/delivery";
import { postService } from "@/services/post";
import type { Post } from "@/types";

// Video posts the viewer may see, newest first (GET /posts/?type=video). A page
// can come back short after visibility filtering, so paging continues.
// Delivery (08 §7.2-7.7, the `video` block): the first request asks for
// `first_page_size`, the next ones `page_size`; the next page is asked for when
// the sentinel comes within `prefetch_root_margin_vp` viewports; a failed page
// is retried `next_page_retries` times with backoff, then an inline retry card.
const { t } = useI18n();
const cfg = () => delivery("video");

const posts = ref<Post[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);
const nextFailed = ref(false);
let generation = 0;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

async function load(initial = false) {
  if (initial) {
    generation++;
    loading.value = true;
    error.value = false;
    nextFailed.value = false;
  } else {
    if (loadingMore.value || !hasMore.value || nextFailed.value) return;
    loadingMore.value = true;
  }
  const run = generation;
  try {
    const retries = initial ? 0 : cfg().next_page_retries;
    const limit = initial ? cfg().first_page_size : cfg().page_size;
    let page: Awaited<ReturnType<typeof postService.videos>> | null = null;
    for (let attempt = 0; ; attempt++) {
      try {
        page = await postService.videos(initial ? null : cursor.value, undefined, limit);
        break;
      } catch (e) {
        if (run !== generation || attempt >= retries) throw e;
        await sleep(cfg().next_page_backoff_ms * 2 ** attempt);
      }
    }
    if (run !== generation || !page) return;
    const known = new Set(initial ? [] : posts.value.map((p) => p.id));
    const fresh = page.data.filter((p) => !known.has(p.id));
    posts.value = initial ? fresh : [...posts.value, ...fresh];
    cursor.value = page.page.next_cursor;
    hasMore.value = !!page.page.has_more && !!page.page.next_cursor;
  } catch {
    if (run !== generation) return;
    if (initial) error.value = true;
    else nextFailed.value = true;
  } finally {
    if (run === generation) {
      loading.value = false;
      loadingMore.value = false;
      void nextTick(reobserve);
    }
  }
}

function retryNext() {
  nextFailed.value = false;
  void load(false);
}

function onRemoved(id: string) {
  posts.value = posts.value.filter((p) => p.id !== id);
}

const sentinel = ref<HTMLElement | null>(null);
let observer: IntersectionObserver | null = null;
function reobserve() {
  if (!observer || !sentinel.value) return;
  observer.unobserve?.(sentinel.value);
  observer.observe(sentinel.value);
}
watch(sentinel, (el) => {
  observer?.disconnect();
  if (el) observer?.observe(el);
});

onMounted(() => {
  void loadDelivery();
  if (typeof IntersectionObserver !== "undefined") {
    observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) void load(false);
      },
      { rootMargin: `${Math.round(cfg().prefetch_root_margin_vp * (window.innerHeight || 800))}px 0px` },
    );
  }
  void load(true);
});
onUnmounted(() => observer?.disconnect());
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

      <div v-if="loading" class="space-y-4" role="status" :aria-label="t('delivery.loading')">
        <FeedCardSkeleton v-for="n in 2" :key="n" />
      </div>
      <ErrorState v-else-if="error" @retry="load(true)" />
      <template v-else>
        <EmptyState v-if="!posts.length && !hasMore">{{ t("postsFeed.videos.empty") }}</EmptyState>
        <PostCard v-for="p in posts" :key="p.id" :post="p" @removed="onRemoved" />
        <FeedRetryCard v-if="nextFailed" :busy="loadingMore" @retry="retryNext" />
        <div v-else-if="hasMore" ref="sentinel" class="py-2 text-center" data-testid="videos-sentinel">
          <div v-if="loadingMore" class="space-y-4 text-start" role="status" :aria-label="t('delivery.loadingMore')">
            <FeedCardSkeleton v-for="n in 2" :key="n" />
          </div>
          <button v-else class="btn-ghost mx-auto" @click="load(false)">
            {{ t("postsFeed.videos.loadMore") }}
          </button>
        </div>
      </template>
    </div>
  </AppShell>
</template>
