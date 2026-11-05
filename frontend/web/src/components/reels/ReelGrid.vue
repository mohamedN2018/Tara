<script setup lang="ts">
// A profile's or Page's "Reels" tab (roadmap 5.8): their reels the viewer may
// see (the server applies the audience and blocks), newest first. A tile opens
// the pager at that reel, with the rest of this author's reels around it.
import { Clapperboard, Play, Plus } from "lucide-vue-next";
import { onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { mediaService } from "@/services/media";
import { type Reel, reelsService } from "@/services/reels";
import { videoService } from "@/services/video";

import { compactCount } from "./pager";

const props = withDefaults(defineProps<{ authorId: string; canCreate?: boolean }>(), { canCreate: false });
const { t, locale } = useI18n();

const reels = ref<Reel[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(false);
const failed = ref(false);
const thumbs = ref<Record<string, string | null>>({});

async function loadThumb(reel: Reel) {
  try {
    const url = reel.reel.cover_media_id
      ? await mediaService.resolveUrl(reel.reel.cover_media_id)
      : (await videoService.playback(reel.reel.media_id)).poster_url;
    thumbs.value = { ...thumbs.value, [reel.id]: url };
  } catch {
    // Keeps the brand background.
  }
}

async function load(reset = false) {
  if (loading.value) return;
  loading.value = true;
  failed.value = false;
  try {
    // The server checks each reel after paging, so a page can be short: follow
    // the cursor a few times to fill the grid.
    let next = reset ? null : cursor.value;
    const found: Reel[] = [];
    for (let i = 0; i < 4; i += 1) {
      const page = await reelsService.byAuthor(props.authorId, next);
      found.push(...page.data);
      next = page.page.next_cursor;
      hasMore.value = page.page.has_more;
      if (found.length >= 6 || !page.page.has_more) break;
    }
    reels.value = reset ? found : [...reels.value, ...found];
    cursor.value = next;
    found.forEach((r) => void loadThumb(r));
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

onMounted(() => void load(true));
watch(
  () => props.authorId,
  () => void load(true),
);
</script>

<template>
  <section class="card p-4" aria-labelledby="reel-grid-title" data-testid="reel-grid">
    <header class="mb-3 flex items-center gap-2">
      <Clapperboard class="h-5 w-5 text-accent-600 dark:text-accent-300" aria-hidden="true" />
      <h2 id="reel-grid-title" class="flex-1 text-xl font-bold">{{ t("reels.title") }}</h2>
      <RouterLink v-if="canCreate" :to="{ path: '/reels', query: { create: '1' } }" class="btn-ghost text-sm" data-testid="reel-grid-create">
        <Plus class="h-4 w-4" aria-hidden="true" /> {{ t("reels.create.title") }}
      </RouterLink>
    </header>
    <LoadingSkeleton v-if="loading && !reels.length" :rows="2" />
    <ErrorState v-else-if="failed && !reels.length" @retry="load(true)" />
    <EmptyState v-else-if="!reels.length">{{ t("reels.empty.author") }}</EmptyState>
    <ul v-else class="grid grid-cols-3 gap-1 sm:grid-cols-4 sm:gap-2">
      <li v-for="r in reels" :key="r.id">
        <RouterLink
          :to="{ name: 'reel', params: { id: r.id }, query: { author: authorId } }"
          class="group relative block aspect-[9/16] overflow-hidden rounded-lg bg-gradient-to-br from-accent-600 via-brand-600 to-brand-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          :aria-label="r.body ? `${t('reels.player')}: ${r.body.slice(0, 80)}` : t('reels.player')"
          data-testid="reel-grid-item"
          :data-reel-id="r.id"
        >
          <img v-if="thumbs[r.id]" :src="thumbs[r.id] ?? undefined" alt="" class="absolute inset-0 h-full w-full object-cover transition group-hover:scale-105" />
          <span class="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent" />
          <span class="absolute bottom-1.5 start-1.5 flex items-center gap-1 text-xs font-semibold text-white">
            <Play class="h-3.5 w-3.5" aria-hidden="true" />{{ compactCount(r.reel.view_count, locale) }}
          </span>
        </RouterLink>
      </li>
    </ul>
    <div v-if="hasMore && reels.length" class="mt-3 flex justify-center">
      <button type="button" class="btn-ghost" :disabled="loading" @click="load()">
        {{ loading ? t("states.loading") : t("feed.loadMore") }}
      </button>
    </div>
  </section>
</template>
