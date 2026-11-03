import { api } from "@/lib/api";
import type { CursorPage, Post } from "@/types";

export interface Comment {
  id: string;
  post_id: string;
  author_id: string;
  parent_id: string | null;
  body: string;
  created_at: string;
}

const BATCH_LIMIT = 50;
// Upper bound on empty pages followed in a row, so one call can't run away.
const MAX_EMPTY_PAGES = 25;

export const postService = {
  async create(payload: {
    body: string;
    audience?: string;
    media_ids?: string[];
    type?: string;
  }): Promise<Post> {
    const mediaIds = payload.media_ids ?? [];
    const { data } = await api.post<{ data: Post }>("/posts/", {
      type: payload.type ?? (mediaIds.length ? "image" : "text"),
      audience: payload.audience ?? "public",
      media_ids: mediaIds,
      body: payload.body,
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

  async comments(id: string, cursor?: string): Promise<CursorPage<Comment>> {
    const { data } = await api.get<CursorPage<Comment>>(`/posts/${id}/comments/`, {
      params: { cursor },
    });
    return data;
  },
  async addComment(id: string, body: string): Promise<Comment> {
    const { data } = await api.post<{ data: Comment }>(`/posts/${id}/comments/`, { body });
    return data.data;
  },

  // Reply to a comment. The backend emits `comment.replied`, which notifies the
  // parent comment's author (the reply is "directed" at them).
  async reply(commentId: string, body: string): Promise<Comment> {
    const { data } = await api.post<{ data: Comment }>(`/comments/${commentId}/replies/`, { body });
    return data.data;
  },

  async share(id: string, body = ""): Promise<Post> {
    const { data } = await api.post<{ data: Post }>(`/posts/${id}/share/`, { body });
    return data.data;
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
