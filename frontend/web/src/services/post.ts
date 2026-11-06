import { api } from "@/lib/api";
import type { CursorPage, Post } from "@/types";

export type CommentPolicy = "everyone" | "friends" | "off";
/** Report endpoints allow 20 an hour: say so rather than "try again in a moment". */
export const REPORT_ERRORS = { throttled: "errors.reportThrottled", rate_limited: "errors.reportThrottled" };

export const COMMENT_POLICIES: CommentPolicy[] = ["everyone", "friends", "off"];

export interface Comment {
  id: string;
  post_id: string;
  author_id: string;
  /** The thread root; null on a root. Replies are flattened onto it. */
  parent_id: string | null;
  /** The comment answered (a root or a reply); null on a root. */
  reply_to_id?: string | null;
  reply_to_author_id?: string | null;
  body: string;
  reply_count?: number;
  reaction_count?: number;
  my_reaction?: string | null;
  created_at: string;
  edited_at?: string | null;
}

export interface Reactor {
  account_id: string;
  type: string;
  created_at: string;
}

export interface Sharer {
  account_id: string;
  share_post_id: string;
  body: string;
  audience: string;
  created_at: string;
}

/** What the author may change on a published post (PostEditSerializer). */
export interface PostChanges {
  body?: string;
  audience?: string;
  comment_policy?: CommentPolicy;
  tagged_ids?: string[];
  location?: string;
  feeling?: string;
}

export interface SavedItem {
  id: string;
  item_type: string;
  item_id: string;
  collection_id: string;
  created_at: string;
}

export interface SavedCollection {
  id: string;
  name: string;
  is_default: boolean;
  item_count: number;
  created_at: string;
}

const BATCH_LIMIT = 50;

/**
 * Where a batch's ids were served (WP 3.6): `surface` and the candidate
 * source of each id, copied from feed's response. Post only uses them to
 * label its own count of the ids it does not return; they never change the answer.
 */
export interface BatchHints {
  surface: string;
  /** One source per id, parallel to `ids`. */
  src: string[];
}
// Upper bound on empty pages followed in a row, so one call can't run away.
const MAX_EMPTY_PAGES = 25;
const MAX_HASHTAG_PAGES = 3;

/**
 * A profile timeline's filters (plan 08): the year posted, who posted
 * (`others`: other people's posts that tag the person) and photos only
 * (`photo`) or posts with several photos (`album`).
 */
export interface TimelineFilters {
  year?: number | null;
  postedBy?: "author" | "others";
  media?: "photo" | "album" | null;
}

export function timelineParams(authorId: string, cursor?: string, filters?: TimelineFilters): Record<string, string | number | undefined> {
  const others = filters?.postedBy === "others";
  return {
    author_id: others ? undefined : authorId,
    tagged_id: others ? authorId : undefined,
    year: filters?.year || undefined,
    media: filters?.media || undefined,
    cursor,
  };
}

export const postService = {
  async create(payload: {
    body: string;
    audience?: string;
    media_ids?: string[];
    type?: string;
    poll?: { options: string[]; duration_hours?: number | null };
    comment_policy?: CommentPolicy;
    /** Post into a group: the server forces the `group` audience. */
    group_id?: string;
  }): Promise<Post> {
    const mediaIds = payload.media_ids ?? [];
    const { data } = await api.post<{ data: Post }>("/posts/", {
      type: payload.type ?? (mediaIds.length ? "image" : "text"),
      audience: payload.audience ?? "public",
      media_ids: mediaIds,
      body: payload.body,
      ...(payload.poll ? { poll: payload.poll } : {}),
      ...(payload.comment_policy ? { comment_policy: payload.comment_policy } : {}),
      ...(payload.group_id ? { group_id: payload.group_id } : {}),
    });
    return data.data;
  },

  async get(id: string): Promise<Post> {
    const { data } = await api.get<{ data: Post }>(`/posts/${id}/`);
    return data.data;
  },

  async edit(id: string, body: string): Promise<Post> {
    const { data } = await api.patch<{ data: Post }>(`/posts/${id}/`, { body });
    return data.data;
  },

  /** Change a published post (author): text, audience, tags, feeling, location or comment policy. */
  async update(id: string, changes: PostChanges): Promise<Post> {
    const { data } = await api.patch<{ data: Post }>(`/posts/${id}/`, changes);
    return data.data;
  },

  /** Published video posts the viewer may see, newest first (a page can be short: keep paging). */
  /** `limit`: the page size from `delivery.video` (08 §7.2); the server's default without it. */
  async videos(cursor?: string | null, authorId?: string, limit?: number): Promise<CursorPage<Post>> {
    const { data } = await api.get<CursorPage<Post>>("/posts/", {
      params: { type: "video", cursor: cursor || undefined, author_id: authorId, limit },
    });
    return data;
  },

  async setCommentPolicy(id: string, policy: CommentPolicy): Promise<Post> {
    const { data } = await api.patch<{ data: Post }>(`/posts/${id}/`, { comment_policy: policy });
    return data.data;
  },

  async report(id: string, reason: string): Promise<void> {
    await api.post(`/posts/${id}/report/`, { reason });
  },

  async byAuthor(authorId: string, cursor?: string, filters?: TimelineFilters): Promise<CursorPage<Post>> {
    const { data } = await api.get<CursorPage<Post>>(`/posts/`, {
      params: timelineParams(authorId, cursor, filters),
    });
    return data;
  },

  /**
   * The next page of a profile timeline that actually has something to show.
   * Audience filtering runs after paging, so a page can be short or even empty
   * while older posts remain: keep following next_cursor.
   */
  async timelinePage(authorId: string, cursor?: string, filters?: TimelineFilters): Promise<CursorPage<Post>> {
    let page = await this.byAuthor(authorId, cursor, filters);
    for (let i = 0; i < MAX_EMPTY_PAGES; i++) {
      if (page.data.length || !page.page.has_more || !page.page.next_cursor) break;
      page = await this.byAuthor(authorId, page.page.next_cursor, filters);
    }
    return page;
  },

  /** Current posts in requested order; missing ids were deleted or are no longer visible. */
  async batch(ids: string[], hints?: BatchHints): Promise<Post[]> {
    const starts: number[] = [];
    for (let i = 0; i < ids.length; i += BATCH_LIMIT) starts.push(i);
    const useHints = !!hints && hints.src.length === ids.length;
    const pages = await Promise.all(
      starts.map((i) =>
        api.post<{ data: Post[] }>("/posts/batch/", {
          ids: ids.slice(i, i + BATCH_LIMIT),
          ...(useHints ? { surface: hints.surface, src: hints.src.slice(i, i + BATCH_LIMIT) } : {}),
        }),
      ),
    );
    return pages.flatMap((p) => p.data.data);
  },

  async remove(id: string): Promise<void> {
    await api.delete(`/posts/${id}/`);
  },

  // ReactionView is POST/DELETE and the serializer field is `type`.
  async react(id: string, type = "like"): Promise<void> {
    await api.post(`/posts/${id}/reactions/`, { type });
  },
  async unreact(id: string): Promise<void> {
    await api.delete(`/posts/${id}/reactions/`);
  },

  /** Who reacted, newest first; `type` keeps one reaction type. */
  async reactions(id: string, type?: string | null, cursor?: string | null): Promise<CursorPage<Reactor>> {
    const { data } = await api.get<CursorPage<Reactor>>(`/posts/${id}/reactions/`, {
      params: { type: type || undefined, cursor: cursor || undefined },
    });
    return data;
  },

  /**
   * Who shared, newest first. The server lists only shares this viewer could
   * open, after paging, so a page can be empty while more remain: keep going.
   */
  async shares(id: string, cursor?: string | null): Promise<CursorPage<Sharer>> {
    const fetchPage = async (c?: string | null) =>
      (await api.get<CursorPage<Sharer>>(`/posts/${id}/shares/`, { params: { cursor: c || undefined } })).data;
    let page = await fetchPage(cursor);
    for (let i = 0; i < MAX_EMPTY_PAGES; i++) {
      if (page.data.length || !page.page.has_more || !page.page.next_cursor) break;
      page = await fetchPage(page.page.next_cursor);
    }
    return page;
  },

  /** Thread roots, oldest first, each with `reply_count`. */
  async comments(id: string, cursor?: string | null): Promise<CursorPage<Comment>> {
    const { data } = await api.get<CursorPage<Comment>>(`/posts/${id}/comments/`, {
      params: { cursor: cursor || undefined },
    });
    return data;
  },
  async addComment(id: string, body: string): Promise<Comment> {
    const { data } = await api.post<{ data: Comment }>(`/posts/${id}/comments/`, { body });
    return data.data;
  },

  /** One thread's replies, oldest first. */
  async replies(rootId: string, cursor?: string | null): Promise<CursorPage<Comment>> {
    const { data } = await api.get<CursorPage<Comment>>(`/comments/${rootId}/replies/`, {
      params: { cursor: cursor || undefined },
    });
    return data;
  },

  // Reply to any comment, root or reply. The server files it under the thread
  // root and notifies the author of the comment answered (`comment.replied`).
  async reply(commentId: string, body: string): Promise<Comment> {
    const { data } = await api.post<{ data: Comment }>(`/comments/${commentId}/replies/`, { body });
    return data.data;
  },

  async editComment(commentId: string, body: string): Promise<Comment> {
    const { data } = await api.patch<{ data: Comment }>(`/comments/${commentId}/`, { body });
    return data.data;
  },

  /** Returns the post's new comment count (a root takes its replies with it). */
  async deleteComment(commentId: string): Promise<{ comment_count: number }> {
    const { data } = await api.delete<{ data: { comment_count: number } }>(`/comments/${commentId}/`);
    return data.data;
  },

  async reactComment(commentId: string, type = "like"): Promise<number> {
    const { data } = await api.post<{ data: { reaction_count: number } }>(
      `/comments/${commentId}/reactions/`,
      { type },
    );
    return data.data.reaction_count;
  },
  async unreactComment(commentId: string): Promise<void> {
    await api.delete(`/comments/${commentId}/reactions/`);
  },

  async reportComment(commentId: string, reason: string): Promise<void> {
    await api.post(`/comments/${commentId}/report/`, { reason });
  },

  async share(id: string, body = "", audience?: string): Promise<Post> {
    const { data } = await api.post<{ data: Post }>(`/posts/${id}/share/`, { body, audience });
    return data.data;
  },

  async vote(id: string, optionId: string): Promise<Post> {
    const { data } = await api.post<{ data: Post }>(`/posts/${id}/vote/`, { option_id: optionId });
    return data.data;
  },

  /** Posts with a hashtag the viewer may see. Filtering runs after paging, as on a timeline. */
  async byHashtag(tag: string): Promise<Post[]> {
    const posts: Post[] = [];
    let cursor: string | undefined;
    for (let i = 0; i < MAX_HASHTAG_PAGES; i++) {
      const { data } = await api.get<CursorPage<Post>>("/posts/", {
        params: { hashtag: tag, cursor },
      });
      posts.push(...data.data);
      if (!data.page.next_cursor) break;
      cursor = data.page.next_cursor;
    }
    return posts;
  },

  // SaveView is POST/DELETE. With a collection, a saved post moves there.
  async save(id: string, collectionId?: string | null): Promise<SavedItem | null> {
    const { data } = await api.post<{ data?: SavedItem }>(
      `/posts/${id}/save/`,
      collectionId ? { collection_id: collectionId } : undefined,
    );
    return data?.data?.item_id ? data.data : null;
  },
  async unsave(id: string): Promise<void> {
    await api.delete(`/posts/${id}/save/`);
  },

  /**
   * One page of saved posts, newest save first, optionally one collection.
   * Posts no longer visible are left out; `savedIds` maps a post to its saved-item id.
   */
  async savedPage(
    cursor?: string,
    collectionId?: string | null,
  ): Promise<{
    posts: Post[];
    nextCursor: string | null;
    savedIds: Record<string, string>;
    collectionIds: Record<string, string>;
  }> {
    const { data } = await api.get<CursorPage<SavedItem>>("/saved/", {
      params: { item_type: "post", cursor, collection_id: collectionId || undefined },
    });
    return {
      posts: await this.batch(data.data.map((s) => s.item_id)),
      nextCursor: data.page.next_cursor,
      savedIds: Object.fromEntries(data.data.map((s) => [s.item_id, s.id])),
      collectionIds: Object.fromEntries(data.data.map((s) => [s.item_id, s.collection_id])),
    };
  },

  /**
   * One page of my saved reels (a profile's "Saved reels"), newest save first:
   * the reel ids only. Load each through `/reels/<id>/`, which checks it may
   * still be seen (a hidden one is 404 and is left out).
   */
  async savedReelIds(cursor?: string | null): Promise<{ ids: string[]; nextCursor: string | null; hasMore: boolean }> {
    const { data } = await api.get<CursorPage<SavedItem>>("/saved/", {
      params: { post_type: "reel", cursor: cursor || undefined },
    });
    return { ids: data.data.map((s) => s.item_id), nextCursor: data.page.next_cursor, hasMore: data.page.has_more };
  },

  // ---- saved collections (owner-only; another account's ids are 404) ----
  async collections(): Promise<SavedCollection[]> {
    const { data } = await api.get<{ data: SavedCollection[] }>("/saved/collections/");
    return data.data ?? [];
  },
  async createCollection(name: string): Promise<SavedCollection> {
    const { data } = await api.post<{ data: SavedCollection }>("/saved/collections/", { name });
    return data.data;
  },
  async renameCollection(id: string, name: string): Promise<SavedCollection> {
    const { data } = await api.patch<{ data: SavedCollection }>(`/saved/collections/${id}/`, { name });
    return data.data;
  },
  /** Its items move back to the default collection. */
  async deleteCollection(id: string): Promise<void> {
    await api.delete(`/saved/collections/${id}/`);
  },
  /** Move a saved item (by its saved-item id) to a collection; null is the default one. */
  async moveSaved(savedId: string, collectionId: string | null): Promise<SavedItem> {
    const { data } = await api.patch<{ data: SavedItem }>(`/saved/${savedId}/`, { collection_id: collectionId });
    return data.data;
  },
};
