<script setup lang="ts">
// A profile's or Page's "Reels" tab (roadmap 5.8): their reels the viewer may
// see (the server applies the audience and blocks), newest first. A tile opens
// the pager at that reel, with the rest of this author's reels around it.
// On your own profile a second list, "Saved reels" (plan 08), shows the reels
// you saved, each loaded through /reels/<id>/ so a hidden one is left out.
import { Clapperboard, Play, Plus } from "lucide-vue-next";
import { onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { mediaService } from "@/services/media";
import { postService } from "@/services/post";
import { type Reel, reelsService } from "@/services/reels";
import { videoService } from "@/services/video";

import { compactCount } from "./pager";

const props = withDefaults(defineProps<{ authorId: string; canCreate?: boolean; showSaved?: boolean }>(), {
  canCreate: false,
  showSaved: false,
});
type ReelList = "author" | "saved";
const list = ref<ReelList>("author");
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

// The server checks each reel after paging, so a page can be short: follow the
// cursor a few times to fill the grid.
async function fetchAuthor(from: string | null) {
  let next = from;
  let more = false;
  const found: Reel[] = [];
  for (let i = 0; i < 4; i += 1) {
    const page = await reelsService.byAuthor(props.authorId, next);
    found.push(...page.data);
    next = page.page.next_cursor;
    more = page.page.has_more;
    if (found.length >= 6 || !more) break;
  }
  return { found, next, more };
}
async function fetchSaved(from: string | null) {
  let next = from;
  let more = false;
  const found: Reel[] = [];
  for (let i = 0; i < 4; i += 1) {
    const page = await postService.savedReelIds(next);
    const got = await Promise.allSettled(page.ids.map((id) => reelsService.get(id)));
    found.push(...got.flatMap((r) => (r.status === "fulfilled" ? [r.value] : [])));
    next = page.nextCursor;
    more = page.hasMore && !!next;
    if (found.length >= 6 || !more) break;
  }
  return { found, next, more };
}

// A newer load (another list, another author) wins over one still running.
let token = 0;
async function load(reset = false) {
  if (loading.value && !reset) return;
  const mine = ++token;
  loading.value = true;
  failed.value = false;
  try {
    const from = reset ? null : cursor.value;
    const { found, next, more } = list.value === "saved" ? await fetchSaved(from) : await fetchAuthor(from);
    if (mine !== token) return;
    reels.value = reset ? found : [...reels.value, ...found];
    cursor.value = next;
    hasMore.value = more;
    found.forEach((r) => void loadThumb(r));
  } catch {
    if (mine === token) failed.value = true;
  } finally {
    if (mine === token) loading.value = false;
  }
}

onMounted(() => void load(true));
watch(
  () => props.authorId,
  () => {
    list.value = "author";
    void load(true);
  },
);
function pickList(next: ReelList) {
  if (list.value === next) return;
  list.value = next;
  reels.value = [];
  cursor.value = null;
  hasMore.value = false;
  void load(true);
}
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
    <div v-if="showSaved" class="mb-3 flex gap-1 border-b border-gray-200 dark:border-gray-800" role="tablist" :aria-label="t('profileTools.reels.label')">
      <button
        v-for="l in (['author', 'saved'] as const)"
        :key="l"
        type="button"
        role="tab"
        :aria-selected="list === l"
        class="relative px-3 py-3 text-sm font-semibold transition"
        :class="list === l ? 'text-brand-600 dark:text-brand-300' : 'rounded-lg text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'"
        :data-testid="`reel-list-${l}`"
        @click="pickList(l)"
      >
        {{ l === "author" ? t("profileTools.reels.yours") : t("profileTools.reels.saved") }}
        <span v-if="list === l" class="absolute inset-x-2 bottom-0 h-[3px] rounded-full bg-brand-600 dark:bg-brand-300" aria-hidden="true" />
      </button>
    </div>
    <LoadingSkeleton v-if="loading && !reels.length" :rows="2" />
    <ErrorState v-else-if="failed && !reels.length" @retry="load(true)" />
    <EmptyState v-else-if="!reels.length">{{ list === "saved" ? t("profileTools.reels.emptySaved") : t("reels.empty.author") }}</EmptyState>
    <ul v-else class="grid grid-cols-3 gap-1 sm:grid-cols-4 sm:gap-2">
      <li v-for="r in reels" :key="r.id">
        <RouterLink
          :to="list === 'saved' ? { name: 'reel', params: { id: r.id } } : { name: 'reel', params: { id: r.id }, query: { author: authorId } }"
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
