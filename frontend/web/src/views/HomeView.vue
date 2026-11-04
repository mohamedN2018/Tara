<script lang="ts">
// Explicit name so <KeepAlive include="HomeView"> reliably caches the feed.
export default { name: "HomeView" };
</script>

<script setup lang="ts">
import { Clock, Settings2, Undo2 } from "lucide-vue-next";
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import CompleteProfileCard from "@/components/auth/CompleteProfileCard.vue";
import AppShell from "@/components/layout/AppShell.vue";
import { railVisible, setRailAd } from "@/components/layout/rightRail";
import CreatePostCard from "@/components/post/CreatePostCard.vue";
import HideFeedbackCard from "@/components/post/HideFeedbackCard.vue";
import PostCard from "@/components/post/PostCard.vue";
import SponsoredCard from "@/components/post/SponsoredCard.vue";
import VideosRail from "@/components/post/VideosRail.vue";
import PeopleYouMayKnowStrip from "@/components/social/PeopleYouMayKnowStrip.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import StoriesRail from "@/components/stories/StoriesRail.vue";
import { realtime } from "@/lib/ws";
import { FEED_MODES, type FeedMode, type FeedReason, feedService, type HideReason, hydrateFeed } from "@/services/feed";
import { graphService } from "@/services/graph";
import { postService, REPORT_ERRORS } from "@/services/post";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";
import type { Post, SponsoredSlot } from "@/types";

const { t } = useI18n();
const toasts = useToastStore();
const directory = useDirectoryStore();
const route = useRoute();
const router = useRouter();

const posts = ref<Post[]>([]);
const sponsored = ref<SponsoredSlot[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(true);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);

// Ranking mode (2A). The switcher shows once the server says it applied the
// mode asked for; a server without modes ignores the parameter.
const MODE_KEY = "tara.feedMode";
// Latest is the order Home always had (feed's own default); For you is one tap away.
const DEFAULT_MODE: FeedMode = "recent";
function savedMode(): FeedMode {
  try {
    const v = localStorage.getItem(MODE_KEY);
    return (FEED_MODES as readonly string[]).includes(v ?? "") ? (v as FeedMode) : DEFAULT_MODE;
  } catch {
    return DEFAULT_MODE;
  }
}
// A `?mode=` link (left rail "Feeds", feed preferences) wins over the remembered one.
function queryMode(): FeedMode | null {
  const q = route.query.mode;
  return typeof q === "string" && (FEED_MODES as readonly string[]).includes(q) ? (q as FeedMode) : null;
}
const mode = ref<FeedMode>(queryMode() ?? savedMode());
// Why each post reached this feed (feed's reason): "Why am I seeing this post?".
const reasons = ref<Record<string, FeedReason>>({});
const modesSupported = ref(false);
function setMode(next: FeedMode) {
  if (next === mode.value) return;
  mode.value = next;
  try {
    localStorage.setItem(MODE_KEY, next);
  } catch {
    // Remembered for this visit only.
  }
  if (route.query.mode !== next) void router.replace({ query: { ...route.query, mode: next } });
  hidden.value = {};
  snoozedAuthors.value = new Set();
  menuSnoozed.value = {};
  // New posts found for the old mode may not belong to this one.
  pending.value = [];
  void load(true);
}
// The left rail's Feeds link while Home is already open (KeepAlive keeps this view).
watch(
  () => route.query.mode,
  () => {
    const q = queryMode();
    if (q && q !== mode.value) setMode(q);
  },
);

// A response for an older mode (or an older first page) is dropped.
let generation = 0;

async function load(initial = false) {
  if (initial) {
    generation++;
    loading.value = true;
    error.value = false;
  } else {
    if (!hasMore.value || loadingMore.value) return;
    loadingMore.value = true;
  }
  const run = generation;
  try {
    const page = await feedService.page(initial ? undefined : (cursor.value ?? undefined), mode.value);
    if (run !== generation) return;
    if (page.modeApplied) modesSupported.value = true;
    const known = new Set(initial ? [] : posts.value.map((p) => p.id));
    const fresh = page.posts.filter((p) => !known.has(p.id));
    posts.value = initial ? fresh : [...posts.value, ...fresh];
    reasons.value = initial ? { ...page.reasons } : { ...reasons.value, ...page.reasons };
    if (initial) {
      sponsored.value = page.sponsored;
      // On wide screens the first slot shows in the right column instead of the feed.
      setRailAd(page.sponsored[0]);
    }
    cursor.value = page.nextCursor;
    hasMore.value = page.hasMore;
  } catch (e) {
    if (run !== generation) return;
    if (initial) error.value = true;
    else toasts.error(e);
  } finally {
    if (run === generation) {
      loading.value = false;
      loadingMore.value = false;
    }
  }
}

// Hide a post (2A): the card is swapped in place for HideFeedbackCard, so the
// list keeps its order and Undo puts the post back where it was.
interface HideState {
  reason: HideReason | null;
  snoozed: boolean;
  busy: boolean;
  reported?: boolean;
  unfollowed?: boolean;
}
const hidden = ref<Record<string, HideState>>({});
// Authors snoozed here: their other cards leave the list until Undo.
const snoozedAuthors = ref(new Set<string>());

function patchHide(id: string, patch: Partial<HideState>) {
  const current = hidden.value[id];
  if (current) hidden.value = { ...hidden.value, [id]: { ...current, ...patch } };
}
function dropHide(id: string) {
  const next = { ...hidden.value };
  delete next[id];
  hidden.value = next;
}
function setSnoozed(authorId: string, on: boolean) {
  const next = new Set(snoozedAuthors.value);
  if (on) next.add(authorId);
  else next.delete(authorId);
  snoozedAuthors.value = next;
}

// The X means "not interested" until the viewer picks another reason.
const DEFAULT_REASON: HideReason = "not_interested";

async function onHide(post: Post) {
  if (hidden.value[post.id]) return;
  hidden.value = { ...hidden.value, [post.id]: { reason: null, snoozed: false, busy: true } };
  try {
    await feedService.hide(post.id, DEFAULT_REASON);
    patchHide(post.id, { busy: false });
  } catch (e) {
    dropHide(post.id);
    toasts.error(e);
  }
}

async function onReason(post: Post, reason: HideReason) {
  patchHide(post.id, { busy: true });
  try {
    await feedService.hide(post.id, reason);
    patchHide(post.id, { reason, busy: false });
  } catch (e) {
    patchHide(post.id, { busy: false });
    toasts.error(e);
  }
}

async function onUndo(post: Post) {
  const state = hidden.value[post.id];
  if (!state || state.busy) return;
  patchHide(post.id, { busy: true });
  try {
    await feedService.unhide(post.id);
  } catch (e) {
    patchHide(post.id, { busy: false });
    toasts.error(e);
    return;
  }
  // Undoing the hide undoes this card's snooze too: the post is wanted back.
  // If the server keeps the snooze, the card stays so Unsnooze can be retried.
  if (state.snoozed) {
    try {
      await feedService.unsnooze(post.author_id);
    } catch (e) {
      patchHide(post.id, { busy: false });
      toasts.error(e);
      return;
    }
    setSnoozed(post.author_id, false);
  }
  dropHide(post.id);
  await nextTick();
  [...document.querySelectorAll<HTMLElement>("[data-feed-item]")]
    .find((n) => n.dataset.feedItem === post.id)
    ?.querySelector<HTMLElement>('[data-testid="hide-post"]')
    ?.focus();
}

async function onSnooze(post: Post) {
  patchHide(post.id, { busy: true });
  try {
    await feedService.snooze(post.author_id);
    setSnoozed(post.author_id, true);
    patchHide(post.id, { snoozed: true, busy: false });
  } catch (e) {
    patchHide(post.id, { busy: false });
    toasts.error(e);
  }
}

async function onUnsnooze(post: Post) {
  patchHide(post.id, { busy: true });
  try {
    await feedService.unsnooze(post.author_id);
    setSnoozed(post.author_id, false);
    patchHide(post.id, { snoozed: false, busy: false });
  } catch (e) {
    patchHide(post.id, { busy: false });
    toasts.error(e);
  }
}

// Hide card: report the post (moderation), or unfollow a followed author.
async function onHideReport(post: Post, reason: string) {
  patchHide(post.id, { busy: true });
  try {
    await postService.report(post.id, reason);
    patchHide(post.id, { busy: false, reported: true });
  } catch (e) {
    patchHide(post.id, { busy: false });
    toasts.error(e, REPORT_ERRORS);
  }
}
async function onHideUnfollow(post: Post) {
  patchHide(post.id, { busy: true });
  try {
    if ((post.author_type ?? "user") === "page") await graphService.unfollowPage(post.author_id);
    else await graphService.unfollow(post.author_id);
    patchHide(post.id, { busy: false, unfollowed: true });
    dropAuthor(post.author_id, post.id);
  } catch (e) {
    patchHide(post.id, { busy: false });
    toasts.error(e);
  }
}

// Muted or unfollowed from the post menu: the author's other items leave the
// list now (the feed itself stops sending them).
function dropAuthor(authorId: string, keepId?: string) {
  posts.value = posts.value.filter((p) => p.author_id !== authorId || p.id === keepId);
  pending.value = pending.value.filter((p) => p.author_id !== authorId);
}
function onAuthorGone(post: Post) {
  dropAuthor(post.author_id);
}

// Snooze from the post menu: the card turns into a "snoozed" notice with Undo.
const menuSnoozed = ref<Record<string, boolean>>({});
const snoozeBusy = ref<string | null>(null);
async function onMenuSnooze(post: Post) {
  if (snoozeBusy.value) return;
  snoozeBusy.value = post.id;
  try {
    await feedService.snooze(post.author_id);
    setSnoozed(post.author_id, true);
    menuSnoozed.value = { ...menuSnoozed.value, [post.id]: true };
  } catch (e) {
    toasts.error(e);
  } finally {
    snoozeBusy.value = null;
  }
}
async function undoMenuSnooze(post: Post) {
  if (snoozeBusy.value) return;
  snoozeBusy.value = post.id;
  try {
    await feedService.unsnooze(post.author_id);
    setSnoozed(post.author_id, false);
    const next = { ...menuSnoozed.value };
    delete next[post.id];
    menuSnoozed.value = next;
  } catch (e) {
    toasts.error(e);
  } finally {
    snoozeBusy.value = null;
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
let unsubs: Array<() => void> = [];

const known = (id: string) => posts.value.some((p) => p.id === id) || pending.value.some((p) => p.id === id);

// The push goes to every recipient, whatever their mode, snoozes or mutes: the
// server's own top page for the current mode decides what the pill may offer.
// `only`: keep just these pushed ids; null keeps every new item (catch-up).
async function addFromTop(only: Set<string> | null) {
  const run = generation;
  try {
    const { data } = await feedService.home(undefined, mode.value);
    if (run !== generation) return;
    const items = data.filter(
      (item) => (!only || only.has(item.post_id)) && !known(item.post_id) && !snoozedAuthors.value.has(item.author_id),
    );
    if (!items.length) return;
    const live = await hydrateFeed(items);
    if (run !== generation) return;
    const fresh = live.filter((p) => !known(p.id) && !snoozedAuthors.value.has(p.author_id));
    pending.value = [...fresh, ...pending.value];
  } catch {
    // Still reachable through a page reload.
  }
}

// Pushes that arrive while a check runs are checked together right after it.
let queued: Set<string> | null = null;
let draining = false;

async function onFeedItem(postId: unknown) {
  const id = typeof postId === "string" ? postId : null;
  if (!id || known(id)) return;
  (queued ??= new Set()).add(id);
  if (draining) return;
  draining = true;
  try {
    while (queued) {
      const ids = queued;
      queued = null;
      await addFromTop(ids);
    }
  } finally {
    draining = false;
  }
}

// Feed pushes sent while the socket was down are gone: compare with the top of the feed.
async function catchUp() {
  await addFromTop(null);
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
  unsubs = [
    realtime.on("feed.item.added", (frame) => onFeedItem(frame.post_id)),
    realtime.on("_reconnected", catchUp),
  ];
});

watch(sentinel, (el) => {
  observer?.disconnect();
  if (el) observer?.observe(el);
});

onUnmounted(() => {
  observer?.disconnect();
  unsubs.forEach((u) => u());
});
</script>

<template>
  <AppShell>
    <div class="mx-auto w-full max-w-[600px] space-y-4">
      <CompleteProfileCard />
      <CreatePostCard @created="onCreated" />
      <StoriesRail />

      <div
        v-if="modesSupported"
        class="card flex items-center gap-1 overflow-x-auto p-1.5"
        role="group"
        :aria-label="t('homeFeed.modes.label')"
        data-testid="feed-modes"
      >
        <button
          v-for="m in FEED_MODES"
          :key="m"
          type="button"
          class="shrink-0 flex-1 rounded-lg px-3 py-2 text-sm font-semibold transition"
          :class="
            mode === m
              ? 'bg-brand-50 text-brand-700 dark:bg-brand-950/60 dark:text-brand-200'
              : 'text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'
          "
          :aria-pressed="mode === m"
          @click="setMode(m)"
        >
          {{ t(`homeFeed.modes.${m}`) }}
        </button>
        <RouterLink
          to="/feeds/manage"
          class="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-gray-600 transition hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
          :aria-label="t('postsFeed.feeds.manage')"
          :title="t('postsFeed.feeds.manage')"
          data-testid="feed-manage"
        >
          <Settings2 class="h-5 w-5" aria-hidden="true" />
        </RouterLink>
      </div>

      <div v-if="pending.length" class="sticky top-16 z-10 flex justify-center">
        <button
          class="rounded-full bg-brand-600 px-4 py-1.5 text-sm font-medium text-white shadow-lg transition hover:bg-brand-700"
          @click="revealPending"
        >
          ↑ {{ t("toasts.newPosts", pending.length) }}
        </button>
      </div>

      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="error" @retry="load(true)" />
      <EmptyState v-else-if="posts.length === 0 && mode === 'favorites' && modesSupported" class="card">
        {{ t("postsFeed.feeds.favoritesEmpty") }}
        <RouterLink to="/settings/content#favorites" class="mt-2 block font-semibold text-brand-600 hover:underline dark:text-brand-300">
          {{ t("postsFeed.feeds.favoritesLink") }}
        </RouterLink>
      </EmptyState>
      <EmptyState v-else-if="posts.length === 0" class="card">{{ t("feed.empty") }}</EmptyState>

      <template v-else>
        <template v-for="(post, i) in posts" :key="post.id">
          <div
            v-show="hidden[post.id] || menuSnoozed[post.id] || !snoozedAuthors.has(post.author_id)"
            :data-feed-item="post.id"
          >
            <div
              v-if="menuSnoozed[post.id] && !hidden[post.id]"
              class="card flex items-center gap-3 p-4"
              role="status"
              data-testid="snoozed-notice"
            >
              <Clock class="h-5 w-5 shrink-0" aria-hidden="true" />
              <span class="min-w-0 flex-1 text-sm" dir="auto">{{ t("postsFeed.menu.snoozed", { name: directory.label(post.author_id) }) }}</span>
              <button type="button" class="btn-ghost shrink-0" :disabled="snoozeBusy === post.id" @click="undoMenuSnooze(post)">
                <Undo2 class="h-4 w-4 rtl:-scale-x-100" aria-hidden="true" /> {{ t("postsFeed.menu.undo") }}
              </button>
            </div>
            <HideFeedbackCard
              v-if="hidden[post.id]"
              :post-id="post.id"
              :author-name="directory.label(post.author_id)"
              :reason="hidden[post.id].reason"
              :snoozed="hidden[post.id].snoozed"
              :busy="hidden[post.id].busy"
              :can-unfollow="reasons[post.id] === 'follow'"
              :reported="!!hidden[post.id].reported"
              :unfollowed="!!hidden[post.id].unfollowed"
              @undo="onUndo(post)"
              @reason="onReason(post, $event)"
              @snooze="onSnooze(post)"
              @unsnooze="onUnsnooze(post)"
              @report="onHideReport(post, $event)"
              @unfollow="onHideUnfollow(post)"
            />
            <!-- Kept mounted while hidden so Undo brings it back as it was. -->
            <PostCard
              v-show="!hidden[post.id] && !menuSnoozed[post.id]"
              :post="post"
              hideable
              snoozable
              :feed-reason="reasons[post.id] ?? null"
              :feed-mode="modesSupported ? mode : null"
              @removed="onRemoved"
              @shared="onCreated"
              @hide="onHide"
              @snooze="onMenuSnooze"
              @author-gone="onAuthorGone"
            />
          </div>
          <!-- Real video posts only; renders nothing when there are none. -->
          <VideosRail v-if="i === 1" />
          <!-- Narrow screens have no right column: its "People you may know" comes into the feed as a strip. -->
          <PeopleYouMayKnowStrip v-if="!railVisible && i === Math.min(2, posts.length - 1)" />
          <SponsoredCard
            v-if="i % 5 === 4 && sponsored[Math.floor(i / 5)] && !(i === 4 && railVisible)"
            :ad="sponsored[Math.floor(i / 5)]"
          />
        </template>

        <div v-if="hasMore" ref="sentinel" class="py-4 text-center">
          <span v-if="loadingMore" class="text-sm text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</span>
          <button v-else class="btn-ghost mx-auto block" @click="load(false)">
            {{ t("feed.loadMore") }}
          </button>
        </div>
      </template>
    </div>
  </AppShell>
</template>
