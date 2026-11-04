import { api } from "@/lib/api";
import { postService } from "@/services/post";
import type { CursorPage, FeedItem, Post, SponsoredSlot } from "@/types";

export interface FeedResponse {
  data: FeedItem[];
  sponsored: SponsoredSlot | null;
  page: { next_cursor: string | null; has_more: boolean };
  /** The ranking mode the server applied (2A). Absent from a server without modes. */
  mode?: string;
}

/** Feed ranking modes (plan 08, 2A): "For you", "Latest", "Favorites", "Following". */
export const FEED_MODES = ["for_you", "recent", "favorites", "following"] as const;
export type FeedMode = (typeof FEED_MODES)[number];

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

/** Live posts for feed items, in feed order. A post the batch omits is gone. */
export async function hydrateFeed(items: FeedItem[]): Promise<Post[]> {
  if (!items.length) return [];
  try {
    const live = new Map((await postService.batch(items.map((i) => i.post_id))).map((p) => [p.id, p]));
    return items.flatMap((i) => live.get(i.post_id) ?? []);
  } catch {
    return items.map(snapshotToPost);
  }
}

export const feedService = {
  /** Home feed. `sponsored` is a sibling of `data` in the envelope (see docs). */
  async home(cursor?: string, mode?: FeedMode): Promise<FeedResponse> {
    const { data } = await api.get<FeedResponse>("/feed/", { params: mode ? { cursor, mode } : { cursor } });
    return data;
  },

  /** The next hydrated page, skipping pages whose posts have all disappeared. */
  async page(cursor?: string, mode?: FeedMode): Promise<HydratedFeedPage> {
    let resp = await this.home(cursor, mode);
    const modeApplied = !!mode && resp.mode === mode;
    let posts = await hydrateFeed(resp.data);
    const reasons: Record<string, FeedReason> = {};
    const note = (items: FeedItem[]) => items.forEach((i) => (reasons[i.post_id] = i.reason as FeedReason));
    note(resp.data);
    const sponsored = resp.sponsored ? [resp.sponsored] : [];
    for (let i = 0; i < MAX_EMPTY_PAGES; i++) {
      if (posts.length || !resp.page.has_more || !resp.page.next_cursor) break;
      resp = await this.home(resp.page.next_cursor, mode);
      note(resp.data);
      posts = await hydrateFeed(resp.data);
    }
    return { posts, reasons, sponsored, nextCursor: resp.page.next_cursor, hasMore: resp.page.has_more, modeApplied };
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
