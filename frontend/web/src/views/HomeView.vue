<script lang="ts">
// Explicit name so <KeepAlive include="HomeView"> reliably caches the feed.
export default { name: "HomeView" };
</script>

<script setup lang="ts">
import { Clock, Settings2, Undo2 } from "lucide-vue-next";
import { nextTick, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import CompleteProfileCard from "@/components/auth/CompleteProfileCard.vue";
import FeedCardSkeleton from "@/components/feed/FeedCardSkeleton.vue";
import FeedEndCard from "@/components/feed/FeedEndCard.vue";
import FeedRetryCard from "@/components/feed/FeedRetryCard.vue";
import AppShell from "@/components/layout/AppShell.vue";
import { railVisible, setRailAd } from "@/components/layout/rightRail";
import CreatePostCard from "@/components/post/CreatePostCard.vue";
import HideFeedbackCard from "@/components/post/HideFeedbackCard.vue";
import PostCard from "@/components/post/PostCard.vue";
import SponsoredCard from "@/components/post/SponsoredCard.vue";
import VideosRail from "@/components/post/VideosRail.vue";
import ReelsRail from "@/components/reels/ReelsRail.vue";
import PeopleYouMayKnowStrip from "@/components/social/PeopleYouMayKnowStrip.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import StoriesRail from "@/components/stories/StoriesRail.vue";
import { delivery, holdRails, loadDelivery, positionRules, releaseRails } from "@/lib/delivery";
import {
  type FeedPosition,
  isChronological,
  isReload,
  readPosition,
  savePosition,
  scrollToCard,
  topCard,
} from "@/lib/feedPosition";
import { itemKey, noteServed } from "@/lib/signals";
import { realtime } from "@/lib/ws";
import {
  DEFAULT_AD_SLOTS,
  type FeedEntry,
  FEED_MODES,
  type FeedMode,
  type FeedReason,
  feedService,
  type HideReason,
  hydrateFeed,
  isFeedMode,
} from "@/services/feed";
import { graphService } from "@/services/graph";
import { mediaService } from "@/services/media";
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
// Where ads go (WP 4.9): the server's `meta.ad_slots`, today `[4]`. Slot k shows
// sponsored[k]; the first one moves to the right column when it is visible.
const adSlots = ref<number[]>([...DEFAULT_AD_SLOTS]);
function adAt(i: number): SponsoredSlot | null {
  const k = adSlots.value.indexOf(i);
  if (k < 0 || !sponsored.value[k]) return null;
  return k === 0 && railVisible.value ? null : sponsored.value[k];
}
// Server time of the first page: the "new posts" peek asks for rows after it.
const asOf = ref<string | undefined>(undefined);
const cursor = ref<string | null>(null);
const hasMore = ref(true);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);
// The next page failed after its automatic retries: the inline retry card shows.
const nextFailed = ref(false);

// Delivery (08 §7.2-7.10): every value is the server's `delivery` block for Home.
const cfg = () => delivery("home");
// Rails (stories, events, pages, suggestions, birthdays, trending, groups) wait for
// the first card, or `defer_rails_max_ms` at the latest (08 §7.4 step 2).
if (cfg().defer_rails_until_first_post) holdRails(cfg().defer_rails_max_ms);
// The other surfaces' blocks, in the background: never before the first feed call.
let deliveryAsked = false;

// Snapshot-first (08 §7.4): ids of cards drawn from their `/feed/` snapshot and not yet
// hydrated, with whether the snapshot carried content (else the card is a skeleton).
const snapshots = ref<Record<string, boolean>>({});

// Ranking mode (2A). The switcher shows once the server says it applied the
// mode asked for; a server without modes ignores the parameter.
// Precedence (WP 4.6): a `?mode=` link, then the mode the server remembers for
// this account (`/feed/preferences/`), then this browser's copy, then the default.
const MODE_KEY = "tara.feedMode";
// Latest is the order Home always had (feed's own default, owner decision 5).
const DEFAULT_MODE: FeedMode = "recent";
function storedMode(): FeedMode | undefined {
  try {
    const v = localStorage.getItem(MODE_KEY);
    return isFeedMode(v) ? v : undefined;
  } catch {
    return undefined;
  }
}
function storeMode(m: FeedMode) {
  try {
    localStorage.setItem(MODE_KEY, m);
  } catch {
    // Remembered on the server, or for this visit only.
  }
}
// A `?mode=` link (left rail "Feeds", feed preferences) wins over the remembered one.
function queryMode(): FeedMode | null {
  const q = route.query.mode;
  return isFeedMode(q) ? q : null;
}
const mode = ref<FeedMode>(queryMode() ?? storedMode() ?? DEFAULT_MODE);
// Until the first page answers, the server picks the mode (its remembered one).
let modeResolved = queryMode() !== null;
// Why each post reached this feed (feed's reason): "Why am I seeing this post?".
const reasons = ref<Record<string, FeedReason>>({});
const modesSupported = ref(false);
// `remember`: a pick in the switcher is the viewer's default, kept for the account
// so a new browser opens on it (WP 4.6); following a `?mode=` link is not.
function setMode(next: FeedMode, remember = false) {
  if (next === mode.value) return;
  mode.value = next;
  modeResolved = true;
  storeMode(next);
  if (remember) void feedService.setDefaultMode(next).catch(() => undefined);
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

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Live posts replace their snapshot cards in place (same key); a post the batch omits is gone. */
function applyHydration(run: number, ids: string[], live: Post[]) {
  if (run !== generation) return;
  const byId = new Map(live.map((p) => [p.id, p]));
  const asked = new Set(ids);
  posts.value = posts.value.flatMap((p) => (asked.has(p.id) ? (byId.has(p.id) ? [byId.get(p.id) as Post] : []) : [p]));
  const next = { ...snapshots.value };
  ids.forEach((id) => delete next[id]);
  snapshots.value = next;
  releaseRails();
  // Every post of the page was gone: ask for the next one.
  if (!posts.value.length && hasMore.value) void load(false);
}

/** The batch could not be reached: snapshots that show content stay; id-only ones cannot be shown. */
function hydrationFailed(run: number, ids: string[]) {
  if (run !== generation) return;
  const asked = new Set(ids);
  const keep = snapshots.value;
  posts.value = posts.value.filter((p) => !asked.has(p.id) || keep[p.id]);
  releaseRails();
}

/** A card with something to read is on screen (a snapshot with content, or a live post). */
const firstContent = () => posts.value.some((p) => snapshots.value[p.id] !== false);

/** One request per (surface, cursor); a second trigger while one is pending is ignored. */
let inFlight: string | null = null;

async function load(initial = false, entry: FeedEntry = "open"): Promise<void> {
  if (initial) {
    generation++;
    loading.value = true;
    error.value = false;
    nextFailed.value = false;
    inFlight = null;
    parked.value = {};
  } else {
    if (!hasMore.value || loadingMore.value || nextFailed.value) return;
    loadingMore.value = true;
  }
  const run = generation;
  const flightKey = `${mode.value}|${initial ? "" : (cursor.value ?? "")}`;
  inFlight = flightKey;
  try {
    const asked = modeResolved ? mode.value : undefined;
    const retries = initial ? 0 : cfg().next_page_retries;
    let page: Awaited<ReturnType<typeof feedService.page>> | null = null;
    for (let attempt = 0; ; attempt++) {
      try {
        page = await feedService.page(initial ? undefined : (cursor.value ?? undefined), asked, asked ? undefined : storedMode(), {
          entry: initial ? entry : undefined,
          snapshots: true,
        });
        break;
      } catch (e) {
        if (run !== generation) return;
        if (attempt >= retries) throw e;
        // Backoff next_page_backoff_ms × 2^n (1 s, 2 s, 4 s); the sentinel is watched again after.
        unobserveSentinel();
        await sleep(cfg().next_page_backoff_ms * 2 ** attempt);
        if (run !== generation) return;
        reobserveSentinel();
      }
    }
    if (run !== generation || !page) return;
    if (!deliveryAsked) {
      deliveryAsked = true;
      void loadDelivery();
    }
    if (page.modeApplied) modesSupported.value = true;
    if (!modeResolved && page.mode) {
      // The server's remembered mode (or this browser's copy) is the one served.
      mode.value = page.mode;
      storeMode(page.mode);
    }
    modeResolved = true;
    const known = new Set(initial ? [] : posts.value.map((p) => p.id));
    const fresh = page.posts.filter((p) => !known.has(p.id));
    const offset = initial ? 0 : posts.value.length;
    posts.value = initial ? fresh : [...posts.value, ...fresh];
    // Signals (WP 2.8): each served item's token and feed position, for its impression.
    fresh.forEach((p, i) => noteServed(itemKey("post", p.id), { st: page.serveTokens?.[p.id], pos: offset + i, surface: "home" }));
    reasons.value = initial ? { ...page.reasons } : { ...reasons.value, ...page.reasons };
    if (initial) {
      sponsored.value = page.sponsored;
      adSlots.value = page.adSlots ?? [...DEFAULT_AD_SLOTS];
      asOf.value = page.asOf;
      // On wide screens the first slot shows in the right column instead of the feed.
      setRailAd(page.sponsored[0]);
    }
    cursor.value = page.nextCursor;
    hasMore.value = page.hasMore;
    if (page.hydrated) {
      const ids = fresh.map((p) => p.id);
      const content = page.snapshotContent ?? {};
      const marks = Object.fromEntries(ids.map((id) => [id, !!content[id]]));
      snapshots.value = initial ? marks : { ...snapshots.value, ...marks };
      page.hydrated.then(
        (live) => applyHydration(run, ids, live),
        () => hydrationFailed(run, ids),
      );
      if (!initial) warmMedia(fresh);
    } else if (initial) snapshots.value = {};
    if (!fresh.length && page.hasMore) {
      // A page with nothing new (all filtered, or already shown): keep going.
      void nextTick(() => load(false));
    }
  } catch {
    if (run !== generation) return;
    if (initial) error.value = true;
    else nextFailed.value = true; // the inline retry card, never an English toast
  } finally {
    if (run === generation) {
      loading.value = false;
      loadingMore.value = false;
      if (inFlight === flightKey) inFlight = null;
      void nextTick(() => {
        if (run !== generation) return;
        if (firstContent() || error.value || !hasMore.value) releaseRails();
        reobserveSentinel();
        retargetPrefetchMark();
      });
    }
  }
}

/** The retry card: one more try, with the automatic retries again behind it. */
function retryNext() {
  nextFailed.value = false;
  void load(false);
}

// Warm the next `media_warm_items` items (08 §7.5): one batched resolve, and their
// thumbnails at low priority. No video segments, no posters.
function warmMedia(fresh: Post[]) {
  const items = fresh.slice(0, cfg().media_warm_items);
  const ids = items.flatMap((p) => (p.type === "video" || p.type === "reel" ? [] : (p.media_ids ?? [])));
  if (!ids.length) return;
  void mediaService.warm(ids).then(() => {
    if (typeof Image === "undefined") return;
    for (const id of ids) {
      const url = mediaService.cachedThumb(id);
      if (!url) continue;
      const img = new Image();
      (img as HTMLImageElement & { fetchPriority?: string }).fetchPriority = "low";
      img.decoding = "async";
      img.src = url;
    }
  });
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
// server's peek for the current mode decides what the pill may offer. A peek
// never replaces the ranking session nor asks for ads (D4, WP 4.7).
// `only`: keep just these pushed ids; null keeps every new item (catch-up).
async function addFromTop(only: Set<string> | null) {
  const run = generation;
  try {
    const { data } = await feedService.peek(mode.value, asOf.value);
    if (run !== generation) return;
    const items = data.filter(
      (item) => (!only || only.has(item.post_id)) && !known(item.post_id) && !snoozedAuthors.value.has(item.author_id),
    );
    if (!items.length) return;
    const live = await hydrateFeed(items);
    if (run !== generation) return;
    items.forEach((i) => noteServed(itemKey("post", i.post_id), { st: i.st, surface: "home" }));
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

// Infinite scroll (08 §7.5): the next page is asked for when the sentinel comes
// within `prefetch_root_margin_vp` viewports, or when only `prefetch_remaining_items`
// rendered cards are left below the viewport, whichever comes first. The manual
// "load more" button remains as a keyboard/fallback affordance.
const sentinel = ref<HTMLElement | null>(null);
let observer: IntersectionObserver | null = null;
let markObserver: IntersectionObserver | null = null;
let markedId: string | null = null;
const observable = typeof IntersectionObserver !== "undefined";

const viewportPx = (vp: number) => Math.round(vp * (window.innerHeight || 800));

function setupSentinel() {
  if (!observable) return;
  observer?.disconnect();
  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0]?.isIntersecting) void load(false);
    },
    { rootMargin: `${viewportPx(cfg().prefetch_root_margin_vp)}px 0px` },
  );
  if (sentinel.value) observer.observe(sentinel.value);
  markObserver?.disconnect();
  markObserver = new IntersectionObserver(
    (entries) => {
      // The marked card reached the viewport (or is above it): few cards are left below.
      const e = entries[entries.length - 1];
      if (e && (e.isIntersecting || e.boundingClientRect.top < 0)) void load(false);
    },
    { rootMargin: "0px" },
  );
  markedId = null;
  retargetPrefetchMark();
}

function unobserveSentinel() {
  if (observer && sentinel.value) observer.unobserve?.(sentinel.value);
}

/** Watch the sentinel again, so the observer reports it afresh (it may still be in range). */
function reobserveSentinel() {
  if (!observer || !sentinel.value) return;
  observer.unobserve?.(sentinel.value);
  observer.observe(sentinel.value);
}

/** The card with `prefetch_remaining_items` cards after it. */
function retargetPrefetchMark() {
  if (!markObserver) return;
  const list = posts.value;
  const target = list.length > cfg().prefetch_remaining_items ? list[list.length - cfg().prefetch_remaining_items]?.id : null;
  if (target === markedId) return;
  markObserver.disconnect();
  markedId = target ?? null;
  if (!target) return;
  const node = [...document.querySelectorAll<HTMLElement>("[data-feed-item]")].find((n) => n.dataset.feedItem === target);
  if (node) markObserver.observe(node);
}

// Virtualization (08 §7.10). Step 1 is CSS (`content-visibility: auto` on every
// card). Step 2: once more than `virtualize_after_items` cards are loaded, a card
// farther than `keep_mounted_vp` viewports is swapped for a placeholder of its
// measured height (kept by post id) and mounted again as it comes back.
const parked = ref<Record<string, number>>({});
let farObserver: IntersectionObserver | null = null;
const watchedCards = new WeakSet<Element>();

function setupVirtualization() {
  if (!observable) return;
  farObserver?.disconnect();
  farObserver = new IntersectionObserver(
    (entries) => {
      const many = posts.value.length > cfg().virtualize_after_items;
      let next: Record<string, number> | null = null;
      for (const e of entries) {
        const id = (e.target as HTMLElement).dataset.feedItem;
        if (!id) continue;
        const isParked = id in parked.value;
        if (e.isIntersecting && isParked) {
          next ??= { ...parked.value };
          delete next[id];
        } else if (!e.isIntersecting && !isParked && many && e.boundingClientRect.height > 0) {
          next ??= { ...parked.value };
          next[id] = Math.round(e.boundingClientRect.height);
        }
      }
      if (next) parked.value = next;
    },
    { rootMargin: `${viewportPx(cfg().keep_mounted_vp)}px 0px` },
  );
  watchNewCards();
}

/** New cards (and placeholders) join the virtualization observer; removed ones leave it. */
const observedCards = new Set<Element>();
function watchNewCards() {
  if (!farObserver) return;
  for (const n of observedCards) {
    if (n.isConnected) continue;
    farObserver.unobserve?.(n);
    observedCards.delete(n);
  }
  document.querySelectorAll("[data-feed-item]").forEach((n) => {
    if (watchedCards.has(n)) return;
    farObserver?.observe(n);
    watchedCards.add(n);
    observedCards.add(n);
  });
}
// A parked card and its placeholder are different elements: watch whichever is in the DOM.
watch(
  [() => posts.value.length, parked],
  () => void nextTick(watchNewCards),
);

// Reload position (08 §7.6): chronological modes only.
let active = true;
function onPageHide() {
  if (!active || !isChronological(mode.value)) return;
  const top = topCard();
  if (!top) return;
  savePosition({ surface: "home", mode: mode.value, anchor_post_id: top.id, offset_px: top.offset, cursor: cursor.value });
}

/** A reload within the window: page forward until the card is in, then scroll back to it. */
async function restore(saved: FeedPosition): Promise<boolean> {
  await load(true, "reload");
  const { maxPages } = positionRules("home");
  const present = () => posts.value.some((p) => p.id === saved.anchor_post_id);
  for (let i = 1; i < maxPages && hasMore.value && !present(); i++) await load(false);
  await nextTick();
  if (!scrollToCard(saved.anchor_post_id, saved.offset_px)) return false;
  // Hydrated cards can be taller than their snapshots: put the card back once they are in.
  const stop = watch(snapshots, (left) => {
    if (Object.keys(left).length) return;
    stop();
    void nextTick(() => scrollToCard(saved.anchor_post_id, saved.offset_px));
  });
  return true;
}

onMounted(() => {
  setupSentinel();
  setupVirtualization();
  const saved = isReload() ? readPosition(mode.value) : null;
  if (saved) void restore(saved);
  else void load(true);
  unsubs = [
    realtime.on("feed.item.added", (frame) => onFeedItem(frame.post_id)),
    realtime.on("_reconnected", catchUp),
  ];
  window.addEventListener("pagehide", onPageHide);
});

onActivated(() => {
  active = true;
});
onDeactivated(() => {
  active = false;
  releaseRails();
});

watch(sentinel, (el) => {
  observer?.disconnect();
  if (el) observer?.observe(el);
});

onUnmounted(() => {
  observer?.disconnect();
  markObserver?.disconnect();
  farObserver?.disconnect();
  window.removeEventListener("pagehide", onPageHide);
  releaseRails();
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
          @click="setMode(m, true)"
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

      <!-- First load: three card skeletons sized like real cards (08 §7.7). -->
      <div v-if="loading" class="space-y-4" role="status" :aria-label="t('delivery.loading')" data-testid="feed-first-loading">
        <FeedCardSkeleton v-for="n in 3" :key="n" />
      </div>
      <ErrorState v-else-if="error" @retry="load(true)" />
      <EmptyState v-else-if="posts.length === 0 && mode === 'favorites' && modesSupported" class="card">
        {{ t("postsFeed.feeds.favoritesEmpty") }}
        <RouterLink to="/settings/content#favorites" class="mt-2 block font-semibold text-brand-600 hover:underline dark:text-brand-300">
          {{ t("postsFeed.feeds.favoritesLink") }}
        </RouterLink>
      </EmptyState>
      <EmptyState v-else-if="posts.length === 0 && !hasMore" class="card">{{ t("feed.empty") }}</EmptyState>

      <template v-else>
        <template v-for="(post, i) in posts" :key="post.id">
          <!-- Far from the screen after many cards: a placeholder of the card's measured height (08 §7.10). -->
          <div
            v-if="post.id in parked && !hidden[post.id] && !menuSnoozed[post.id]"
            :data-feed-item="post.id"
            data-feed-parked
            :style="{ height: `${parked[post.id]}px` }"
            aria-hidden="true"
          />
          <div
            v-else-if="hidden[post.id] || menuSnoozed[post.id] || !snoozedAuthors.has(post.author_id)"
            :data-feed-item="post.id"
            :data-feed-state="post.id in snapshots ? 'snapshot' : 'live'"
          >
            <!-- Drawn from the `/feed/` snapshot until `/posts/batch/` answers (08 §7.4). -->
            <FeedCardSkeleton
              v-if="post.id in snapshots && !hidden[post.id] && !menuSnoozed[post.id]"
              :snapshot="snapshots[post.id] ? post : null"
              :media="post.type !== 'text'"
              :eager="i === 0"
            />
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
            <!-- Kept mounted while the hide is being sent (it may be refused); unmounted once it is done. -->
            <PostCard
              v-if="!(post.id in snapshots) && (!hidden[post.id] || hidden[post.id].busy) && !menuSnoozed[post.id]"
              v-show="!hidden[post.id] && !menuSnoozed[post.id]"
              :post="post"
              :eager-media="i === 0"
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
          <!-- Real reels only (short vertical videos, 5.8), apart from the Videos rail. -->
          <ReelsRail v-if="i === Math.min(3, posts.length - 1)" />
          <!-- Narrow screens have no right column: its "People you may know" comes into the feed as a strip. -->
          <PeopleYouMayKnowStrip v-if="!railVisible && i === Math.min(2, posts.length - 1)" />
          <SponsoredCard v-if="adAt(i)" :ad="adAt(i)!" />
        </template>

        <FeedRetryCard v-if="nextFailed" :busy="loadingMore" @retry="retryNext" />
        <div v-else-if="hasMore" ref="sentinel" class="py-4 text-center" data-testid="feed-sentinel">
          <!-- Next page: two card skeletons (08 §7.7). -->
          <div v-if="loadingMore" class="space-y-4 text-start" role="status" :aria-label="t('delivery.loadingMore')" data-testid="feed-next-loading">
            <FeedCardSkeleton v-for="n in 2" :key="n" />
          </div>
          <button v-else class="btn-ghost mx-auto block" @click="load(false)">
            {{ t("feed.loadMore") }}
          </button>
        </div>
        <!-- Only when the server says there is nothing more (never while has_more). -->
        <FeedEndCard v-else-if="posts.length" />
      </template>
      <!-- An empty feed still offers real reels (the in-feed rail needs posts to sit between). -->
      <ReelsRail v-if="!loading && !error && posts.length === 0" />
    </div>
  </AppShell>
</template>

<style scoped>
/* Virtualization step 1 (08 §7.10): off-screen cards skip layout and paint. */
[data-feed-item] {
  content-visibility: auto;
  contain-intrinsic-size: auto 900px;
}
[data-feed-item][data-feed-parked] {
  content-visibility: visible;
}
</style>
