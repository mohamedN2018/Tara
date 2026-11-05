import { api } from "@/lib/api";
import { postService } from "@/services/post";
import type { CursorPage, FeedItem, Post, SponsoredSlot } from "@/types";

export interface FeedResponse {
  data: FeedItem[];
  sponsored: SponsoredSlot | null;
  /** One ad per configured slot at most (WP 4.9); absent from older servers. */
  sponsored_slots?: SponsoredSlot[];
  page: { next_cursor: string | null; has_more: boolean };
  /** The ranking mode the server applied (2A). Absent from a server without modes. */
  mode?: string;
  /** First pages: the ad positions from the server's config, and the server time. */
  meta?: { ad_slots?: number[]; as_of?: string };
}

/** `?peek=1` (WP 4.7): new rows for the "new posts" pill, no session or ads touched. */
export interface FeedPeek {
  data: FeedItem[];
  mode: string;
  peek: true;
  new_count: number;
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

/** Why a post is in this viewer's feed (feed's FeedItem.Reason). */
export type FeedReason = "self" | "friend" | "follow";

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
  async home(cursor?: string, mode?: FeedMode, modeHint?: FeedMode): Promise<FeedResponse> {
    const params: Record<string, string | undefined> = { cursor };
    if (mode) params.mode = mode;
    else if (modeHint) params.mode_hint = modeHint;
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
  async page(cursor?: string, mode?: FeedMode, modeHint?: FeedMode): Promise<HydratedFeedPage> {
    let resp = await this.home(cursor, mode, modeHint);
    const served = isFeedMode(resp.mode) ? resp.mode : undefined;
    const modeApplied = !!served && (!mode || served === mode);
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
    for (let i = 0; i < MAX_EMPTY_PAGES; i++) {
      if (posts.length || !resp.page.has_more || !resp.page.next_cursor) break;
      // Later pages carry the served mode, so a remembered mode keeps its cursor.
      resp = await this.home(resp.page.next_cursor, mode ?? served);
      note(resp.data);
      posts = await hydrateFeed(resp.data);
    }
    return {
      posts,
      reasons,
      sponsored,
      nextCursor: resp.page.next_cursor,
      hasMore: resp.page.has_more,
      modeApplied,
      serveTokens,
      mode: served,
      adSlots,
      asOf,
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
