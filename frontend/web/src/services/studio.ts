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

/** One local day of what my published posts received from other people. */
export interface StudioDay {
  date: string;
  /** Reel views (one per viewer per day); other posts have no view telemetry. */
  views: number;
  reactions: number;
  comments: number;
  shares: number;
  saves: number;
  /** Posts I published that day. */
  posts: number;
}
export type DailyMetric = Exclude<keyof StudioDay, "date">;
export interface StudioDaily {
  from: string;
  to: string;
  tz: string;
  days: StudioDay[];
  totals: Record<DailyMetric, number>;
}

/** The content library's filters (published tab). `from`/`to` are ISO instants. */
export interface LibraryFilter {
  type?: LibraryType | "";
  q?: string;
  from?: string | null;
  to?: string | null;
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

  async published(filter: LibraryType | "" | LibraryFilter = "", cursor?: string | null, limit?: number): Promise<CursorPage<ComposerPost>> {
    const f: LibraryFilter = typeof filter === "string" ? { type: filter } : filter;
    const { data } = await api.get<CursorPage<ComposerPost>>("/posts/studio/published/", {
      params: {
        type: f.type || undefined,
        q: f.q?.trim() || undefined,
        from: f.from || undefined,
        to: f.to || undefined,
        cursor: cursor || undefined,
        limit: limit || undefined,
      },
    });
    return data;
  },

  /** Per local day, `from`..`to` inclusive (YYYY-MM-DD, at most 366 days). */
  async daily(from: string, to: string, tz: string): Promise<StudioDaily> {
    const { data } = await api.get<{ data: StudioDaily }>("/posts/studio/daily/", { params: { from, to, tz } });
    return data.data;
  },

  /** Scheduled and published posts in `[from, to)` (ISO instants, at most 43 days). */
  async calendar(from: string, to: string): Promise<CalendarPage> {
    const { data } = await api.get<CalendarPage>("/posts/calendar/", { params: { from, to } });
    return data;
  },
};
