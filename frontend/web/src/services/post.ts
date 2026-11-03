import { api } from "@/lib/api";
import type { CursorPage, Post } from "@/types";

export type CommentPolicy = "everyone" | "friends" | "off";
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

const BATCH_LIMIT = 50;
// Upper bound on empty pages followed in a row, so one call can't run away.
const MAX_EMPTY_PAGES = 25;
const MAX_HASHTAG_PAGES = 3;

export const postService = {
  async create(payload: {
    body: string;
    audience?: string;
    media_ids?: string[];
    type?: string;
    poll?: { options: string[]; duration_hours?: number | null };
    comment_policy?: CommentPolicy;
  }): Promise<Post> {
    const mediaIds = payload.media_ids ?? [];
    const { data } = await api.post<{ data: Post }>("/posts/", {
      type: payload.type ?? (mediaIds.length ? "image" : "text"),
      audience: payload.audience ?? "public",
      media_ids: mediaIds,
      body: payload.body,
      ...(payload.poll ? { poll: payload.poll } : {}),
      ...(payload.comment_policy ? { comment_policy: payload.comment_policy } : {}),
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

  async setCommentPolicy(id: string, policy: CommentPolicy): Promise<Post> {
    const { data } = await api.patch<{ data: Post }>(`/posts/${id}/`, { comment_policy: policy });
    return data.data;
  },

  async report(id: string, reason: string): Promise<void> {
    await api.post(`/posts/${id}/report/`, { reason });
  },

  async byAuthor(authorId: string, cursor?: string): Promise<CursorPage<Post>> {
    const { data } = await api.get<CursorPage<Post>>(`/posts/`, {
      params: { author_id: authorId, cursor },
    });
    return data;
  },

  /**
   * The next page of a profile timeline that actually has something to show.
   * Audience filtering runs after paging, so a page can be short or even empty
   * while older posts remain: keep following next_cursor.
   */
  async timelinePage(authorId: string, cursor?: string): Promise<CursorPage<Post>> {
    let page = await this.byAuthor(authorId, cursor);
    for (let i = 0; i < MAX_EMPTY_PAGES; i++) {
      if (page.data.length || !page.page.has_more || !page.page.next_cursor) break;
      page = await this.byAuthor(authorId, page.page.next_cursor);
    }
    return page;
  },

  /** Current posts in requested order; missing ids were deleted or are no longer visible. */
  async batch(ids: string[]): Promise<Post[]> {
    const chunks: string[][] = [];
    for (let i = 0; i < ids.length; i += BATCH_LIMIT) chunks.push(ids.slice(i, i + BATCH_LIMIT));
    const pages = await Promise.all(
      chunks.map((chunk) => api.post<{ data: Post[] }>("/posts/batch/", { ids: chunk })),
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

  // SaveView is POST/DELETE.
  async save(id: string): Promise<void> {
    await api.post(`/posts/${id}/save/`);
  },
  async unsave(id: string): Promise<void> {
    await api.delete(`/posts/${id}/save/`);
  },

  /** One page of saved posts, newest save first. Posts no longer visible are left out. */
  async savedPage(cursor?: string): Promise<{ posts: Post[]; nextCursor: string | null }> {
    const { data } = await api.get<CursorPage<{ item_id: string }>>("/saved/", {
      params: { item_type: "post", cursor },
    });
    return {
      posts: await this.batch(data.data.map((s) => s.item_id)),
      nextCursor: data.page.next_cursor,
    };
  },
};
