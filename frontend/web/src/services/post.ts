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

  // Saved items (refs); resolve each post via get(). item_type filter on the server.
  async listSavedPostIds(): Promise<string[]> {
    const { data } = await api.get<{ data: { item_id: string; item_type: string }[] }>("/saved/", {
      params: { item_type: "post" },
    });
    return data.data.filter((s) => s.item_type === "post").map((s) => s.item_id);
  },
};
