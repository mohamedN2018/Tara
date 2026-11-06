import { api } from "@/lib/api";
import { applyDelivery, type DeliveryBlock } from "@/lib/delivery";
import { postService } from "@/services/post";
import type { CursorPage, FeedItem, Post, SponsoredSlot } from "@/types";

export interface FeedResponse {
  data: FeedItem[];
  sponsored: SponsoredSlot | null;
  /** One ad per configured slot at most (WP 4.9); absent from older servers. */
  sponsored_slots?: SponsoredSlot[];
  page: { next_cursor: string | null; has_more: boolean; prev_cursor?: string | null; fallback?: boolean };
  /** The ranking mode the server applied (2A). Absent from a server without modes. */
  mode?: string;
  /** First pages: the ad positions from the server's config, and the server time. */
  meta?: {
    ad_slots?: number[];
    as_of?: string;
    /** For-you pages (4b.6): where the viewer's own circle ran out and suggestions begin. */
    caught_up_index?: number | null;
    /** The `delivery` block of the Home config (08 §7.2): page sizes, prefetch, video policy… */
    delivery?: DeliveryBlock;
    /** First pages (R3, 06 §6.2): the visit; null with personalization off. */
    visit?: FeedVisit | null;
    /** First pages (06 §6.1): away this long → the "new posts" pill (seconds). */
    refresh_after_s?: number;
    /** First pages (06 §6.1): away this long at the top → a silent refresh (seconds). */
    auto_refetch_after_s?: number;
  };
}

/** `meta.visit` (06 §6.2): what changed since the viewer's last visit. */
export interface FeedVisit {
  kind: string;
  /** Start of the previous visit (ISO); the peek's `since`. */
  since: string | null;
  /** Eligible rows newer than `since` (never a raw count). */
  new_count: number;
  /** Where the new rows end in this page; null when there is no boundary. */
  anchor_index: number | null;
  /** The divider shows only from this many new rows. */
  min_to_show: number;
}

/**
 * Why a first page is asked for (06 §4.2, a hint the server classifies with its own
 * timestamps): `load` a full page load, `nav` in-app navigation, `reload` a browser
 * reload, `return` the automatic refresh after time away, `pull` pull-to-refresh or
 * the refresh control. `open` and `refresh` are the R2 names (= `nav`, `pull`).
 */
export const FEED_ENTRIES = ["nav", "load", "reload", "return", "pull", "open", "refresh"] as const;
export type FeedEntry = (typeof FEED_ENTRIES)[number];

/** `?peek=1` (WP 4.7): new rows for the "new posts" pill, no session or ads touched. */
export interface FeedPeek {
  data: FeedItem[];
  mode: string;
  peek: true;
  /** Eligible new rows since `since` (the pill shows exactly this). */
  new_count: number;
  /** `new_count` hit the server's cap: "N or more". */
  new_count_capped?: boolean;
  /** The new rows' post ids (eligible only). */
  ids?: string[];
  /** The `since` the server applied (clamped). */
  since?: string;
}

/** Feed ranking modes (plan 08, 2A; friends WP 4.6): For you, Latest, Favorites, Following, Friends. */
export const FEED_MODES = ["for_you", "recent", "favorites", "following", "friends"] as const;
export type FeedMode = (typeof FEED_MODES)[number];
export const isFeedMode = (v: unknown): v is FeedMode => typeof v === "string" && (FEED_MODES as readonly string[]).includes(v);

/** Ad positions in the Home list when the server does not say (today's single slot). */
export const DEFAULT_AD_SLOTS: readonly number[] = [4];

/** My Algorithm settings served so far (WP 4.6): the remembered Home mode. */
export interface FeedPreferences {
  default_mode: FeedMode | null;
  version: number;
}

/** One reason in "Why am I seeing this?" (WP 4.8). Only the viewer's own data. */
export interface WhyFactor {
  code: string;
  author_id?: string;
  topic?: string;
  format?: string;
}
export interface WhyExplanation {
  item: string;
  mode: string | null;
  surface: string;
  cfg_version: string | null;
  factors: WhyFactor[];
}

/** Why the viewer hid a post (feed's fixed list, 2A). */
export const HIDE_REASONS = ["not_interested", "spam", "sexual", "annoying", "dislike_creator", "other"] as const;
export type HideReason = (typeof HIDE_REASONS)[number];

/** Why a post is in this viewer's feed (feed's FeedItem.Reason). `rec_*` (4b.6):
 * a suggestion from the popular or fresh pools (`source: "discovery"`). */
export type FeedReason = "self" | "friend" | "follow" | "rec_popular" | "rec_fresh";

/** A suggestion from outside the viewer's circle (shows the "Suggested" label). */
export const isSuggestedReason = (r: FeedReason | null | undefined): boolean => !!r && r.startsWith("rec_");

export interface Snooze {
  author_id: string;
  until: string;
  snoozed_at: string;
}

export interface HydratedFeedPage {
  posts: Post[];
  /** post id -> why it reached this feed. */
  reasons: Record<string, FeedReason>;
  sponsored: SponsoredSlot[];
  nextCursor: string | null;
  hasMore: boolean;
  /** The server ranked by the requested mode (it echoes `mode`), so the switcher may show. */
  modeApplied: boolean;
  /** post id -> the serve token it came with (signals attribution, WP 2.8); empty on older servers. */
  serveTokens?: Record<string, string>;
  /** The mode the server served (the remembered one when none was asked for). */
  mode?: FeedMode;
  /** Where the sponsored items go in the list (first pages only). */
  adSlots?: number[];
  /** Server time of the first page: later peeks ask for rows after it. */
  asOf?: string;
  /** For-you (4b.6): index in this page's items where suggestions begin; null when none. */
  caughtUpIndex?: number | null;
  /**
   * Snapshot-first pages (08 §7.4): `posts` are the `/feed/` snapshots, to draw at
   * once, and this resolves the live posts in feed order (a post the batch omits is
   * gone). It rejects when the batch cannot be reached.
   */
  hydrated?: Promise<Post[]>;
  /** post id -> the snapshot carried content (public, or the viewer's own); else ids only. */
  snapshotContent?: Record<string, boolean>;
  /** The server continued a ranked session in chronological order (08 §7.3). */
  fallback?: boolean;
  /** First pages (R3): the visit, and the refresh timers in seconds. */
  visit?: FeedVisit | null;
  refreshAfterS?: number;
  autoRefetchAfterS?: number;
  /** The page's post ids in server order (`meta` indices refer to these). */
  ids?: string[];
}

/** The R3 first-page fields of `meta`, checked (a malformed one is dropped). */
function visitFields(resp: FeedResponse): Pick<HydratedFeedPage, "visit" | "refreshAfterS" | "autoRefetchAfterS" | "ids"> {
  const m = resp.meta ?? {};
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : undefined);
  const v = m.visit;
  const visit =
    v && typeof v === "object" && Number.isInteger(v.new_count) && Number.isInteger(v.min_to_show)
      ? { ...v, anchor_index: Number.isInteger(v.anchor_index) ? v.anchor_index : null }
      : v === null
        ? null
        : undefined;
  return {
    visit,
    refreshAfterS: num(m.refresh_after_s),
    autoRefetchAfterS: num(m.auto_refetch_after_s),
    ids: resp.data.map((i) => i.post_id),
  };
}

/** Whether the server sent this item's content in its snapshot (it strips it otherwise). */
export function snapshotHasContent(item: FeedItem): boolean {
  const s = item.snapshot ?? {};
  const media = Array.isArray(s.media_ids) && s.media_ids.length > 0;
  return (typeof s.excerpt === "string" && s.excerpt.length > 0) || (typeof s.body === "string" && s.body.length > 0) || media;
}

/** Live posts for feed items, in feed order; throws when the batch fails (no snapshot fallback). */
export async function hydrateLive(items: FeedItem[]): Promise<Post[]> {
  if (!items.length) return [];
  const hints = { surface: "home", src: items.map((i) => i.source ?? i.reason ?? "") };
  const live = new Map((await postService.batch(items.map((i) => i.post_id), hints)).map((p) => [p.id, p]));
  return items.flatMap((i) => live.get(i.post_id) ?? []);
}

// Upper bound on fully-filtered pages followed in a row.
const MAX_EMPTY_PAGES = 10;

/** The feed delivers a stale snapshot: `partial` marks `body` as a possibly cut excerpt. */
export function snapshotToPost(item: FeedItem): Post {
  const { snapshot } = item;
  return {
    id: item.post_id,
    author_id: (snapshot.author_id as string) ?? item.author_id,
    author_type: (snapshot.author_type as string) ?? "user",
    type: (snapshot.type as string) ?? "text",
    body: (snapshot.body as string) ?? (snapshot.excerpt as string) ?? "",
    audience: (snapshot.audience as string) ?? "public",
    media_ids: (snapshot.media_ids as string[]) ?? [],
    reaction_count: (snapshot.reaction_count as number) ?? 0,
    comment_count: (snapshot.comment_count as number) ?? 0,
    share_count: (snapshot.share_count as number) ?? 0,
    created_at: (snapshot.created_at as string) ?? item.post_created_at,
    partial: true,
  };
}

/**
 * Live posts for feed items, in feed order. A post the batch omits is gone.
 * The batch carries the Home surface and each item's source as hints, so post
 * can count what it drops (WP 3.6).
 */
export async function hydrateFeed(items: FeedItem[]): Promise<Post[]> {
  if (!items.length) return [];
  try {
    const hints = { surface: "home", src: items.map((i) => i.source ?? i.reason ?? "") };
    const live = new Map((await postService.batch(items.map((i) => i.post_id), hints)).map((p) => [p.id, p]));
    return items.flatMap((i) => live.get(i.post_id) ?? []);
  } catch {
    return items.map(snapshotToPost);
  }
}

export const feedService = {
  /** Home feed. `sponsored` is a sibling of `data` in the envelope (see docs). */
  /** `modeHint`: the offline fallback, used by the server only when it remembers no mode. */
  /** `entry`: first pages only (08 §7.6). No `limit`: the server applies the delivery page sizes. */
  /** `sid`: the tab's telemetry session (a hint for the visit, first pages only). */
  async home(cursor?: string, mode?: FeedMode, modeHint?: FeedMode, entry?: FeedEntry, sid?: string): Promise<FeedResponse> {
    const params: Record<string, string | undefined> = { cursor };
    if (mode) params.mode = mode;
    else if (modeHint) params.mode_hint = modeHint;
    if (entry && !cursor) params.entry = entry;
    if (sid && !cursor) params.sid = sid;
    const { data } = await api.get<FeedResponse>("/feed/", { params });
    return data;
  },

  /** New rows since `since` for the pill (WP 4.7). Never replaces the ranked session. */
  async peek(mode: FeedMode, since?: string): Promise<FeedPeek> {
    const { data } = await api.get<FeedPeek>("/feed/", { params: { mode, peek: 1, since } });
    return data;
  },

  /** The next hydrated page, skipping pages whose posts have all disappeared.
   * With no `mode` the server picks the viewer's remembered one (`modeHint` as fallback). */
  async page(
    cursor?: string,
    mode?: FeedMode,
    modeHint?: FeedMode,
    options: { entry?: FeedEntry; snapshots?: boolean; sid?: string } = {},
  ): Promise<HydratedFeedPage> {
    let resp = await this.home(cursor, mode, modeHint, options.entry, options.sid);
    const served = isFeedMode(resp.mode) ? resp.mode : undefined;
    const modeApplied = !!served && (!mode || served === mode);
    if (resp.meta?.delivery) applyDelivery("home", resp.meta.delivery);
    if (options.snapshots) return snapshotPage(resp, served, modeApplied);
    let posts = await hydrateFeed(resp.data);
    const reasons: Record<string, FeedReason> = {};
    const serveTokens: Record<string, string> = {};
    const note = (items: FeedItem[]) =>
      items.forEach((i) => {
        reasons[i.post_id] = i.reason as FeedReason;
        if (typeof i.st === "string" && i.st) serveTokens[i.post_id] = i.st;
      });
    note(resp.data);
    const sponsored = resp.sponsored_slots ?? (resp.sponsored ? [resp.sponsored] : []);
    const adSlots = resp.meta?.ad_slots?.filter((n) => Number.isInteger(n) && n >= 0);
    const asOf = resp.meta?.as_of;
    const first = visitFields(resp);
    for (let i = 0; i < MAX_EMPTY_PAGES; i++) {
      if (posts.length || !resp.page.has_more || !resp.page.next_cursor) break;
      // Later pages carry the served mode, so a remembered mode keeps its cursor.
      resp = await this.home(resp.page.next_cursor, mode ?? served);
      note(resp.data);
      posts = await hydrateFeed(resp.data);
    }
    const caught = resp.meta?.caught_up_index;
    return {
      posts,
      reasons,
      sponsored,
      caughtUpIndex: Number.isInteger(caught) ? (caught as number) : null,
      nextCursor: resp.page.next_cursor,
      hasMore: resp.page.has_more,
      modeApplied,
      serveTokens,
      mode: served,
      adSlots,
      asOf,
      fallback: resp.page.fallback === true,
      ...(cursor ? {} : first),
    };
  },

  /** The viewer's My Algorithm settings (WP 4.6). */
  async preferences(): Promise<FeedPreferences> {
    const { data } = await api.get<{ data: FeedPreferences }>("/feed/preferences/");
    return data.data;
  },

  /** Remember the Home mode on the server, so it follows the viewer to a new browser. */
  async setDefaultMode(mode: FeedMode): Promise<FeedPreferences> {
    const { data } = await api.patch<{ data: FeedPreferences }>("/feed/preferences/", { default_mode: mode });
    return data.data;
  },

  /** "Why am I seeing this?" (WP 4.8). 404 unless the item was served to this viewer. */
  async why(postId: string, st?: string): Promise<WhyExplanation> {
    const { data } = await api.get<{ data: WhyExplanation }>(`/feed/why/post/${postId}/`, { params: st ? { st } : {} });
    return data.data;
  },

  /** Hide a post from this viewer's feed, with why (201). */
  async hide(postId: string, reason: HideReason): Promise<void> {
    await api.post("/feed/hide/", { post_id: postId, reason });
  },

  /** Undo a hide (204). */
  async unhide(postId: string): Promise<void> {
    await api.delete(`/feed/hide/${postId}/`);
  },

  /** Keep an author out of this viewer's feed for 30 days. */
  async snooze(authorId: string): Promise<void> {
    await api.post("/feed/snooze/", { author_id: authorId });
  },

  async unsnooze(authorId: string): Promise<void> {
    await api.delete(`/feed/snooze/${authorId}/`);
  },

  /** Active snoozes, newest first (feed preferences). */
  async snoozes(cursor?: string | null): Promise<CursorPage<Snooze>> {
    const { data } = await api.get<CursorPage<Snooze>>("/feed/snoozes/", { params: { cursor: cursor || undefined } });
    return data;
  },
};

function noteOf(items: FeedItem[]) {
  const reasons: Record<string, FeedReason> = {};
  const serveTokens: Record<string, string> = {};
  for (const i of items) {
    reasons[i.post_id] = i.reason as FeedReason;
    if (typeof i.st === "string" && i.st) serveTokens[i.post_id] = i.st;
  }
  return { reasons, serveTokens };
}

/** A page to draw from its snapshots at once; `hydrated` brings the live posts (08 §7.4). */
function snapshotPage(resp: FeedResponse, served: FeedMode | undefined, modeApplied: boolean): HydratedFeedPage {
  const { reasons, serveTokens } = noteOf(resp.data);
  const snapshotContent: Record<string, boolean> = {};
  const posts = resp.data.map((item) => {
    const content = snapshotHasContent(item);
    snapshotContent[item.post_id] = content;
    const post = snapshotToPost(item);
    // Only what the server sent: no content, no audience guess.
    return content ? post : { ...post, body: "", media_ids: [], audience: (item.snapshot?.audience as string) ?? "" };
  });
  const caught = resp.meta?.caught_up_index;
  const hydrated = hydrateLive(resp.data);
  // A rejection is handled by the caller; keep it from being reported as unhandled meanwhile.
  hydrated.catch(() => undefined);
  return {
    posts,
    reasons,
    serveTokens,
    sponsored: resp.sponsored_slots ?? (resp.sponsored ? [resp.sponsored] : []),
    caughtUpIndex: Number.isInteger(caught) ? (caught as number) : null,
    nextCursor: resp.page.next_cursor,
    hasMore: resp.page.has_more,
    modeApplied,
    mode: served,
    adSlots: resp.meta?.ad_slots?.filter((n) => Number.isInteger(n) && n >= 0),
    asOf: resp.meta?.as_of,
    hydrated,
    snapshotContent,
    fallback: resp.page.fallback === true,
    ...visitFields(resp),
  };
}
