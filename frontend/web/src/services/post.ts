import { api } from "@/lib/api";
import type { CursorPage, Post } from "@/types";

export interface Comment {
  id: string;
  post_id: string;
  author_id: string;
  body: string;
  created_at: string;
}

export const postService = {
  async create(payload: { body: string; audience?: string; media_ids?: string[] }): Promise<Post> {
    const { data } = await api.post<{ data: Post }>("/posts/", {
      type: "text",
      audience: "public",
      media_ids: [],
      ...payload,
    });
    return data.data;
  },

  async get(id: string): Promise<Post> {
    const { data } = await api.get<{ data: Post }>(`/posts/${id}/`);
    return data.data;
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

  async react(id: string, kind = "like"): Promise<void> {
    await api.put(`/posts/${id}/reactions/`, { kind });
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

  async share(id: string, body = ""): Promise<Post> {
    const { data } = await api.post<{ data: Post }>(`/posts/${id}/share/`, { body });
    return data.data;
  },

  async save(id: string): Promise<void> {
    await api.put(`/posts/${id}/save/`);
  },
  async unsave(id: string): Promise<void> {
    await api.delete(`/posts/${id}/save/`);
  },
};
