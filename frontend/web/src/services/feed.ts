import { api } from "@/lib/api";
import { postService } from "@/services/post";
import type { FeedItem, Post, SponsoredSlot } from "@/types";

export interface FeedResponse {
  data: FeedItem[];
  sponsored: SponsoredSlot[] | null;
  page: { next_cursor: string | null; has_more: boolean };
}

export interface HydratedFeedPage {
  posts: Post[];
  sponsored: SponsoredSlot[];
  nextCursor: string | null;
  hasMore: boolean;
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
  async home(cursor?: string): Promise<FeedResponse> {
    const { data } = await api.get<FeedResponse>("/feed/", { params: { cursor } });
    return data;
  },

  /** The next hydrated page, skipping pages whose posts have all disappeared. */
  async page(cursor?: string): Promise<HydratedFeedPage> {
    let resp = await this.home(cursor);
    let posts = await hydrateFeed(resp.data);
    const sponsored = resp.sponsored ?? [];
    for (let i = 0; i < MAX_EMPTY_PAGES; i++) {
      if (posts.length || !resp.page.has_more || !resp.page.next_cursor) break;
      resp = await this.home(resp.page.next_cursor);
      posts = await hydrateFeed(resp.data);
    }
    return { posts, sponsored, nextCursor: resp.page.next_cursor, hasMore: resp.page.has_more };
  },
};
