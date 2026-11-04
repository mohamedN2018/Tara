<script setup lang="ts">
import { ChevronLeft, ChevronRight, Play, Video } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { postService } from "@/services/post";
import { videoService } from "@/services/video";
import { useDirectoryStore } from "@/stores/directory";
import type { Post } from "@/types";

// The home feed's "Videos" rail: real video posts the viewer may see, newest
// first. It renders nothing at all until there is at least one.
const RAIL_MAX = 10;

const { t } = useI18n();
const directory = useDirectoryStore();

const videos = ref<Post[]>([]);
const posters = ref<Record<string, string | null>>({});
const track = ref<HTMLElement | null>(null);

async function loadPoster(post: Post) {
  const id = post.media_ids?.[0];
  if (!id) return;
  try {
    const p = await videoService.playback(id);
    posters.value = { ...posters.value, [post.id]: p.poster_url };
  } catch {
    // The tile keeps its plain background.
  }
}

onMounted(async () => {
  try {
    const page = await postService.videos();
    videos.value = page.data.filter((p) => p.media_ids?.length).slice(0, RAIL_MAX);
    videos.value.forEach((p) => void loadPoster(p));
  } catch {
    videos.value = [];
  }
});

/** Scroll by one tile towards the reading end (+1) or start (-1); mirrors in RTL. */
function scrollByTile(step: 1 | -1) {
  const el = track.value;
  if (!el) return;
  const rtl = getComputedStyle(el).direction === "rtl";
  el.scrollBy({ left: (rtl ? -1 : 1) * step * 240, behavior: "smooth" });
}
</script>

<template>
  <section v-if="videos.length" class="card p-3 sm:p-4" aria-labelledby="videos-rail-title" data-testid="videos-rail">
    <header class="mb-3 flex items-center gap-2">
      <Video class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" />
      <h2 id="videos-rail-title" class="flex-1 text-[15px] font-bold">{{ t("postsFeed.videos.rail") }}</h2>
      <RouterLink to="/videos" class="text-sm font-semibold text-brand-600 hover:underline dark:text-brand-300" data-testid="videos-see-all">
        {{ t("postsFeed.videos.seeAll") }}
      </RouterLink>
    </header>
    <div class="relative">
      <ul ref="track" class="flex snap-x gap-2 overflow-x-auto scroll-smooth pb-1 [scrollbar-width:none]">
        <li v-for="v in videos" :key="v.id" class="w-36 shrink-0 snap-start sm:w-44">
          <RouterLink
            :to="{ name: 'post', params: { id: v.id } }"
            class="group relative block aspect-[9/16] overflow-hidden rounded-xl bg-gradient-to-br from-brand-700 via-brand-500 to-accent-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            :aria-label="t('postsFeed.videos.open', { name: directory.label(v.author_id) })"
          >
            <img v-if="posters[v.id]" :src="posters[v.id] ?? undefined" alt="" class="absolute inset-0 h-full w-full object-cover transition group-hover:scale-105" />
            <span class="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent" />
            <span class="absolute inset-0 flex items-center justify-center">
              <Play class="h-10 w-10 rounded-full bg-black/40 p-2 text-white" aria-hidden="true" />
            </span>
            <span class="absolute inset-x-2 bottom-2 flex items-center gap-1.5 text-xs font-semibold text-white">
              <UserAvatar :name="directory.label(v.author_id)" :media-id="directory.avatarOf(v.author_id)" :size="24" ring />
              <span class="truncate" dir="auto">{{ directory.label(v.author_id) }}</span>
            </span>
          </RouterLink>
        </li>
      </ul>
      <button
        v-if="videos.length > 3"
        type="button"
        class="absolute start-1 top-1/2 hidden h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-white text-gray-800 shadow-lg transition hover:bg-gray-100 sm:inline-flex dark:bg-gray-800 dark:text-gray-100"
        :aria-label="t('postsFeed.videos.prev')"
        @click="scrollByTile(-1)"
      >
        <ChevronLeft class="h-5 w-5 rtl:-scale-x-100" aria-hidden="true" />
      </button>
      <button
        v-if="videos.length > 3"
        type="button"
        class="absolute end-1 top-1/2 hidden h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-white text-gray-800 shadow-lg transition hover:bg-gray-100 sm:inline-flex dark:bg-gray-800 dark:text-gray-100"
        :aria-label="t('postsFeed.videos.next')"
        @click="scrollByTile(1)"
      >
        <ChevronRight class="h-5 w-5 rtl:-scale-x-100" aria-hidden="true" />
      </button>
    </div>
  </section>
</template>
