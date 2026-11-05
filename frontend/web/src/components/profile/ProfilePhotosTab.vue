<script setup lang="ts">
import { Images } from "lucide-vue-next";
import { computed, ref, toRefs, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import MediaTheater from "@/components/post/MediaTheater.vue";
import PostTheaterPanel from "@/components/post/PostTheaterPanel.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { useMediaList } from "@/lib/useMediaList";
import { useMediaViewer } from "@/lib/useMediaViewer";
import type { ProfileState } from "@/lib/useProfile";
import { postService, type TimelineFilters } from "@/services/post";
import { useDirectoryStore } from "@/stores/directory";
import type { Post } from "@/types";

// The profile's Photos tab (plan 08): "Photos of you" (other people's posts that
// tag the person), "Your photos" (their own posts with photos) and "Albums".
// Tara has no albums of its own, so an album here is honestly what it is: one
// post with more than one photo. Everything comes from the post service, which
// applies the audience and blocks. A photo opens the theater with its post.
type PhotoList = "of" | "by" | "albums";
const LISTS: PhotoList[] = ["of", "by", "albums"];

const props = defineProps<{ state: ProfileState }>();
const { userId, displayName, isSelf, tab: profileTab, profile } = toRefs(props.state);
const { t, locale } = useI18n();
const router = useRouter();
const directory = useDirectoryStore();

const list = ref<PhotoList>("by");
interface ListState {
  posts: Post[];
  cursor: string | null;
  hasMore: boolean;
  loading: boolean;
  failed: boolean;
  loaded: boolean;
}
const empty = (): ListState => ({ posts: [], cursor: null, hasMore: false, loading: false, failed: false, loaded: false });
const lists = ref<Record<PhotoList, ListState>>({ of: empty(), by: empty(), albums: empty() });
const filtersFor = (l: PhotoList): TimelineFilters =>
  l === "of" ? { postedBy: "others", media: "photo" } : { media: l === "albums" ? "album" : "photo" };

let generation = 0;
async function load(l: PhotoList, reset = false) {
  const id = userId.value;
  const st = lists.value[l];
  if (!id || st.loading) return;
  const mine = generation;
  st.loading = true;
  st.failed = false;
  try {
    const page = await postService.timelinePage(id, reset ? undefined : (st.cursor ?? undefined), filtersFor(l));
    if (mine !== generation) return;
    st.posts = reset ? page.data : [...st.posts, ...page.data];
    st.cursor = page.page.next_cursor;
    st.hasMore = page.page.has_more && !!page.page.next_cursor;
    st.loaded = true;
  } catch {
    if (mine === generation) st.failed = true;
  } finally {
    if (mine === generation) st.loading = false;
  }
}

// Load a list the first time it is shown; start again for another profile.
watch(
  [profileTab, list, userId],
  ([tb, l]) => {
    if (tb === "photos" && !lists.value[l].loaded) void load(l, true);
  },
  { immediate: true },
);
watch(userId, () => {
  generation += 1;
  lists.value = { of: empty(), by: empty(), albums: empty() };
  if (profileTab.value === "photos") void load(list.value, true);
});

const current = computed(() => lists.value[list.value]);
// One tile per photo (Photos of / by), one card per post (Albums).
const tiles = computed(() =>
  current.value.posts.flatMap((post) => (post.media_ids ?? []).map((mediaId, index) => ({ post, mediaId, index }))),
);
const tileUrls = useMediaList(() => (list.value === "albums" ? [] : tiles.value.map((x) => x.mediaId)));
const albumUrls = useMediaList(() => (list.value === "albums" ? current.value.posts.map((p) => p.media_ids?.[0] ?? "").filter(Boolean) : []));

const label = (l: PhotoList) => {
  if (l === "albums") return t("profileTools.photos.albums");
  if (l === "of") return isSelf.value ? t("profileTools.photos.ofYou") : t("profileTools.photos.ofName", { name: displayName.value });
  return isSelf.value ? t("profileTools.photos.byYou") : t("profileTools.photos.byName", { name: displayName.value });
};
const emptyText = computed(() => {
  if (list.value === "of") return t("profileTools.photos.emptyOf", { name: displayName.value });
  return list.value === "albums" ? t("profileTools.photos.emptyAlbums") : t("profileTools.photos.emptyBy");
});
function albumTitle(p: Post): string {
  const text = (p.body || "").trim();
  if (text) return text.length > 60 ? `${text.slice(0, 60)}…` : text;
  let date = "";
  try {
    date = new Date(p.created_at).toLocaleDateString(locale.value, { year: "numeric", month: "long", day: "numeric" });
  } catch {
    date = p.created_at.slice(0, 10);
  }
  return t("profileTools.photos.albumFrom", { date });
}

// ---- the theater: the open post's photos, kept in `?view=ph-<post>:<index>` ----
const openPost = ref<Post | null>(null);
const viewer = useMediaViewer(
  () => (openPost.value ? `ph-${openPost.value.id}` : ""),
  () => openPost.value?.media_ids?.length ?? 0,
);
function openAt(post: Post, index: number) {
  openPost.value = post;
  viewer.open(index);
}
const ownPost = (p: Post) => p.author_id === userId.value;
const authorName = (p: Post) => (ownPost(p) ? displayName.value : directory.label(p.author_id));
const authorAvatar = (p: Post) => (ownPost(p) ? (profile.value?.avatar_media_id ?? null) : directory.avatarOf(p.author_id));
const authorTo = (p: Post) => ({ name: p.author_type === "page" ? "page-by-id" : "profile-by-id", params: { id: p.author_id } });
function shareOpen() {
  const p = openPost.value;
  if (p) void router.push(`/posts/${p.id}`);
}

function onListKey(e: KeyboardEvent) {
  const i = LISTS.indexOf(list.value);
  const rtl = document.documentElement.dir === "rtl";
  const next = e.key === "ArrowRight" ? (rtl ? -1 : 1) : e.key === "ArrowLeft" ? (rtl ? 1 : -1) : 0;
  if (!next) return;
  e.preventDefault();
  list.value = LISTS[(i + next + LISTS.length) % LISTS.length];
  (document.getElementById(`photos-list-${list.value}`) as HTMLElement | null)?.focus();
}
</script>

<template>
  <div class="card p-4" data-testid="profile-photos">
    <h2 class="mb-3 text-xl font-bold">{{ t("profile.photos") }}</h2>
    <div class="mb-4 flex gap-1 overflow-x-auto border-b border-gray-200 dark:border-gray-800" role="tablist" :aria-label="t('profileTools.photos.label')" @keydown="onListKey">
      <button
        v-for="l in LISTS"
        :id="`photos-list-${l}`"
        :key="l"
        type="button"
        role="tab"
        :aria-selected="list === l"
        :tabindex="list === l ? 0 : -1"
        aria-controls="photos-panel"
        class="relative shrink-0 whitespace-nowrap px-3 py-3 text-sm font-semibold transition"
        :class="list === l ? 'text-brand-600 dark:text-brand-300' : 'rounded-lg text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'"
        :data-testid="`photos-list-${l}`"
        @click="list = l"
      >
        <bdi>{{ label(l) }}</bdi>
        <span v-if="list === l" class="absolute inset-x-2 bottom-0 h-[3px] rounded-full bg-brand-600 dark:bg-brand-300" aria-hidden="true" />
      </button>
    </div>

    <div id="photos-panel" role="tabpanel" :aria-labelledby="`photos-list-${list}`">
      <p v-if="list === 'albums'" class="mb-3 text-sm text-gray-600 dark:text-gray-400">{{ t("profileTools.photos.albumsHint") }}</p>
      <LoadingSkeleton v-if="current.loading && !current.posts.length" :rows="2" />
      <ErrorState v-else-if="current.failed && !current.posts.length" @retry="load(list, true)" />
      <EmptyState v-else-if="current.loaded && !current.posts.length">{{ emptyText }}</EmptyState>

      <ul v-else-if="list === 'albums'" class="grid grid-cols-2 gap-3 sm:grid-cols-3" data-testid="photos-albums">
        <li v-for="(p, i) in current.posts" :key="p.id">
          <button
            type="button"
            class="group block w-full text-start focus:outline-none"
            data-testid="photos-album"
            @click="openAt(p, 0)"
          >
            <span class="relative block aspect-square overflow-hidden rounded-xl bg-gray-100 ring-brand-400 group-focus-visible:ring-4 dark:bg-gray-800">
              <img v-if="albumUrls[i]" :src="albumUrls[i] ?? undefined" alt="" class="h-full w-full object-cover transition group-hover:scale-105" loading="lazy" />
              <span class="absolute end-2 top-2 rounded-full bg-gray-950/60 p-1 text-white" aria-hidden="true"><Images class="h-4 w-4" /></span>
            </span>
            <span class="mt-1.5 block truncate text-sm font-semibold" dir="auto">{{ albumTitle(p) }}</span>
            <span class="block text-xs text-gray-600 dark:text-gray-400">{{ t("profileTools.photos.albumCount", p.media_ids?.length ?? 0, { named: { n: p.media_ids?.length ?? 0 } }) }}</span>
          </button>
        </li>
      </ul>

      <ul v-else class="grid grid-cols-3 gap-1.5 sm:grid-cols-4" :data-testid="`photos-grid-${list}`">
        <li v-for="(tile, i) in tiles" :key="`${tile.post.id}-${tile.index}`">
          <button
            type="button"
            class="block aspect-square w-full overflow-hidden rounded-lg bg-gray-100 transition hover:opacity-90 focus:outline-none focus-visible:ring-4 focus-visible:ring-brand-400 dark:bg-gray-800"
            :aria-label="t('profileTools.photos.open', { n: i + 1 })"
            data-testid="photos-tile"
            @click="openAt(tile.post, tile.index)"
          >
            <img v-if="tileUrls[i]" :src="tileUrls[i] ?? undefined" class="h-full w-full object-cover" loading="lazy" :alt="t('profile.photoAlt', { n: i + 1, name: authorName(tile.post) })" />
          </button>
        </li>
      </ul>

      <div v-if="current.hasMore && current.posts.length" class="mt-3 flex justify-center">
        <button type="button" class="btn-ghost" :disabled="current.loading" @click="load(list)">
          {{ current.loading ? t("states.loading") : t("feed.loadMore") }}
        </button>
      </div>
    </div>

    <MediaTheater
      v-if="openPost && viewer.index.value !== null"
      :media-ids="openPost.media_ids ?? []"
      :index="viewer.index.value"
      :author-name="authorName(openPost)"
      @go="viewer.go"
      @close="viewer.close"
    >
      <template #panel>
        <PostTheaterPanel
          :key="openPost.id"
          :post="openPost"
          :author-name="authorName(openPost)"
          :author-avatar="authorAvatar(openPost)"
          :author-to="authorTo(openPost)"
          @share="shareOpen"
        />
      </template>
    </MediaTheater>
  </div>
</template>
