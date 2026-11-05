<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import MediaTheater from "@/components/post/MediaTheater.vue";
import PostTheaterPanel from "@/components/post/PostTheaterPanel.vue";
import { useMediaList } from "@/lib/useMediaList";
import { useMediaViewer } from "@/lib/useMediaViewer";
import { type Page, pageService } from "@/services/pages";
import type { Post } from "@/types";

// The Posts tab's "Photos" card (plan 08): the latest photos from the page's
// own posts (post service, `?media=photo`: the audience and blocks apply), nine
// at most. A photo opens the theater with its post beside it.
const props = defineProps<{ page: Page }>();
const { t } = useI18n();
const router = useRouter();
const MAX = 9;

const posts = ref<Post[]>([]);
const loaded = ref(false);
async function load() {
  loaded.value = false;
  try {
    const found: Post[] = [];
    let cursor: string | null = null;
    // Pages of the timeline may be short (audience filtering): follow the cursor a little.
    for (let i = 0; i < 3 && found.flatMap((p) => p.media_ids ?? []).length < MAX; i += 1) {
      const res = await pageService.photoPosts(props.page.id, cursor);
      found.push(...res.data);
      cursor = res.page.next_cursor;
      if (!res.page.has_more || !cursor) break;
    }
    posts.value = found;
  } catch {
    posts.value = []; // the card stays out: no photos to show is not an error worth a banner
  } finally {
    loaded.value = true;
  }
}
onMounted(load);
watch(() => props.page.id, load);

const tiles = computed(() =>
  posts.value.flatMap((post) => (post.media_ids ?? []).map((mediaId, index) => ({ post, mediaId, index }))).slice(0, MAX),
);
const urls = useMediaList(() => tiles.value.map((x) => x.mediaId));

const openPost = ref<Post | null>(null);
const viewer = useMediaViewer(
  () => (openPost.value ? `pg-${openPost.value.id}` : ""),
  () => openPost.value?.media_ids?.length ?? 0,
);
function openAt(post: Post, index: number) {
  openPost.value = post;
  viewer.open(index);
}
</script>

<template>
  <section v-if="loaded && tiles.length" class="card p-4" aria-labelledby="page-photos-title" data-testid="page-photos">
    <h2 id="page-photos-title" class="mb-3 text-xl font-bold">{{ t("profileTools.page.photos") }}</h2>
    <ul class="grid grid-cols-3 gap-1 overflow-hidden rounded-xl">
      <li v-for="(tile, i) in tiles" :key="`${tile.post.id}-${tile.index}`">
        <button
          type="button"
          class="block aspect-square w-full overflow-hidden bg-gray-100 transition hover:opacity-90 focus:outline-none focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-brand-400 dark:bg-gray-800"
          :aria-label="t('profileTools.photos.open', { n: i + 1 })"
          data-testid="page-photos-tile"
          @click="openAt(tile.post, tile.index)"
        >
          <img v-if="urls[i]" :src="urls[i] ?? undefined" alt="" class="h-full w-full object-cover" loading="lazy" />
        </button>
      </li>
    </ul>

    <MediaTheater
      v-if="openPost && viewer.index.value !== null"
      :media-ids="openPost.media_ids ?? []"
      :index="viewer.index.value"
      :author-name="page.name"
      @go="viewer.go"
      @close="viewer.close"
    >
      <template #panel>
        <PostTheaterPanel
          :key="openPost.id"
          :post="openPost"
          :author-name="page.name"
          :author-avatar="page.avatar_media_id"
          :author-to="{ name: 'page', params: { handle: page.handle } }"
          @share="router.push(`/posts/${openPost.id}`)"
        />
      </template>
    </MediaTheater>
  </section>
</template>
