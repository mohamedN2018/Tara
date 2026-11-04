// Creator studio (track T8): the signed-in author's own numbers, content
// library and planner calendar. Every read is scoped to the caller by the post
// service (services/post/posts/studio.py); writes reuse the composer's draft
// endpoints and the post's own delete.
import { api } from "@/lib/api";
import type { ComposerPost } from "@/services/composer";
import type { CursorPage } from "@/types";

export interface StudioSummary {
  /** Live published posts. */
  posts: number;
  reactions: number;
  comments: number;
  shares: number;
  /** How many times other people saved my published posts. */
  saves: number;
  drafts: number;
  scheduled: number;
  /** Up to three published posts with the most interactions. */
  top_posts: ComposerPost[];
}

export type LibraryType = "text" | "image" | "video" | "link" | "share" | "poll";
export const LIBRARY_TYPES: LibraryType[] = ["text", "image", "video", "link", "share", "poll"];

export interface CalendarPage {
  data: ComposerPost[];
  meta: { truncated: boolean };
}

/** Insights: my published posts per type, with what they received. */
export interface StudioTypeRow {
  type: LibraryType | string;
  posts: number;
  reactions: number;
  comments: number;
  shares: number;
}
export interface StudioInsights {
  by_type: StudioTypeRow[];
  /** Up to ten published posts with the most interactions. */
  top_posts: ComposerPost[];
}

/** Engagement: someone else's comment on one of my published posts. */
export interface StudioComment {
  id: string;
  post_id: string;
  author_id: string;
  parent_id: string | null;
  body: string;
  reaction_count: number;
  created_at: string;
  /** The start of the post the comment is on. */
  post_excerpt: string;
  post_type: string;
}

export const studioService = {
  async summary(): Promise<StudioSummary> {
    const { data } = await api.get<{ data: StudioSummary }>("/posts/studio/summary/");
    return data.data;
  },

  async insights(): Promise<StudioInsights> {
    const { data } = await api.get<{ data: StudioInsights }>("/posts/studio/insights/");
    return data.data;
  },

  async comments(cursor?: string | null): Promise<CursorPage<StudioComment>> {
    const { data } = await api.get<CursorPage<StudioComment>>("/posts/studio/comments/", {
      params: { cursor: cursor || undefined },
    });
    return data;
  },

  async published(type?: LibraryType | "", cursor?: string | null): Promise<CursorPage<ComposerPost>> {
    const { data } = await api.get<CursorPage<ComposerPost>>("/posts/studio/published/", {
      params: { type: type || undefined, cursor: cursor || undefined },
    });
    return data;
  },

  /** Scheduled and published posts in `[from, to)` (ISO instants, at most 43 days). */
  async calendar(from: string, to: string): Promise<CalendarPage> {
    const { data } = await api.get<CalendarPage>("/posts/calendar/", { params: { from, to } });
    return data;
  },
};
