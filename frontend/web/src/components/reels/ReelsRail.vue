<script setup lang="ts">
import { ChevronLeft, ChevronRight, Clapperboard, Play } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { mediaService } from "@/services/media";
import { type Reel, reelsService } from "@/services/reels";
import { videoService } from "@/services/video";
import { useDirectoryStore } from "@/stores/directory";
import { usePageDirectoryStore } from "@/stores/pageDirectory";

import { compactCount } from "./pager";

// The home feed's "Reels" rail (roadmap 5.8): real reels from the viewer's
// For you feed, apart from the Videos rail (landscape / long video posts). It
// renders nothing at all until there is at least one reel.
const RAIL_MAX = 12;

const { t, locale } = useI18n();
const directory = useDirectoryStore();
const pageDirectory = usePageDirectoryStore();

const reels = ref<Reel[]>([]);
const thumbs = ref<Record<string, string | null>>({});
const track = ref<HTMLElement | null>(null);

async function loadThumb(reel: Reel) {
  try {
    const url = reel.reel.cover_media_id
      ? await mediaService.resolveUrl(reel.reel.cover_media_id)
      : (await videoService.playback(reel.reel.media_id)).poster_url;
    thumbs.value = { ...thumbs.value, [reel.id]: url };
  } catch {
    // The tile keeps its brand background.
  }
}

onMounted(async () => {
  try {
    const page = await reelsService.feed("for_you");
    reels.value = page.data.slice(0, RAIL_MAX);
    reels.value.forEach((r) => void loadThumb(r));
  } catch {
    reels.value = [];
  }
});

const name = (r: Reel) => (r.author_type === "page" ? pageDirectory.label(r.author_id) : directory.label(r.author_id));
const avatar = (r: Reel) => (r.author_type === "page" ? pageDirectory.avatarOf(r.author_id) : directory.avatarOf(r.author_id));

/** Scroll by one tile towards the reading end (+1) or start (-1); mirrors in RTL. */
function scrollByTile(step: 1 | -1) {
  const el = track.value;
  if (!el) return;
  const rtl = getComputedStyle(el).direction === "rtl";
  el.scrollBy({ left: (rtl ? -1 : 1) * step * 240, behavior: "smooth" });
}
</script>

<template>
  <section v-if="reels.length" class="card p-3 sm:p-4" aria-labelledby="reels-rail-title" data-testid="reels-rail">
    <header class="mb-3 flex items-center gap-2">
      <Clapperboard class="h-5 w-5 text-accent-600 dark:text-accent-300" aria-hidden="true" />
      <h2 id="reels-rail-title" class="flex-1 text-[15px] font-bold">{{ t("reels.rail.title") }}</h2>
      <RouterLink to="/reels" class="text-sm font-semibold text-brand-600 hover:underline dark:text-brand-300" data-testid="reels-see-all">
        {{ t("reels.rail.seeAll") }}
      </RouterLink>
    </header>
    <div class="relative">
      <ul ref="track" class="flex snap-x gap-2 overflow-x-auto scroll-smooth pb-1 [scrollbar-width:none]">
        <li v-for="r in reels" :key="r.id" class="w-32 shrink-0 snap-start sm:w-40">
          <RouterLink
            :to="{ name: 'reel', params: { id: r.id } }"
            class="group relative block aspect-[9/16] overflow-hidden rounded-xl bg-gradient-to-br from-accent-600 via-brand-600 to-brand-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            :aria-label="t('reels.rail.open', { name: name(r) })"
            data-testid="reels-rail-item"
            :data-reel-id="r.id"
          >
            <img v-if="thumbs[r.id]" :src="thumbs[r.id] ?? undefined" alt="" class="absolute inset-0 h-full w-full object-cover transition group-hover:scale-105" />
            <span class="absolute inset-0 bg-gradient-to-t from-black/75 via-transparent to-black/20" />
            <span class="absolute start-2 top-2 flex items-center gap-1 rounded-full bg-black/45 px-1.5 py-0.5 text-[11px] font-semibold text-white">
              <Play class="h-3 w-3" aria-hidden="true" />{{ compactCount(r.reel.view_count, locale) }}
            </span>
            <span class="absolute inset-x-2 bottom-2 flex items-center gap-1.5 text-xs font-semibold text-white">
              <UserAvatar :name="name(r)" :media-id="avatar(r)" :size="24" ring />
              <span class="truncate" dir="auto">{{ name(r) }}</span>
            </span>
          </RouterLink>
        </li>
      </ul>
      <button
        v-if="reels.length > 3"
        type="button"
        class="absolute start-1 top-1/2 hidden h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-white text-gray-800 shadow-lg transition hover:bg-gray-100 sm:inline-flex dark:bg-gray-800 dark:text-gray-100"
        :aria-label="t('reels.rail.prev')"
        @click="scrollByTile(-1)"
      >
        <ChevronLeft class="h-5 w-5 rtl:-scale-x-100" aria-hidden="true" />
      </button>
      <button
        v-if="reels.length > 3"
        type="button"
        class="absolute end-1 top-1/2 hidden h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-white text-gray-800 shadow-lg transition hover:bg-gray-100 sm:inline-flex dark:bg-gray-800 dark:text-gray-100"
        :aria-label="t('reels.rail.next')"
        @click="scrollByTile(1)"
      >
        <ChevronRight class="h-5 w-5 rtl:-scale-x-100" aria-hidden="true" />
      </button>
    </div>
  </section>
</template>
