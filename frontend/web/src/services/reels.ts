// Reels (roadmap 5.5 / 5.8): short vertical videos, distinct from video posts.
// A reel is a post of type "reel" (its id is the post id), so likes, comments,
// shares, saves, edits and deletion go through postService. The server decides
// what may be a reel from the transcoded video (portrait around 9:16, at most
// 90 s); a landscape or longer clip is offered as a normal video post instead.
import { api } from "@/lib/api";
import type { CursorPage, Post } from "@/types";

export type ReelTab = "for_you" | "following";
export const REEL_TABS: readonly ReelTab[] = ["for_you", "following"];
export type ReelAudience = "public" | "friends" | "followers" | "only_me";
export const REEL_AUDIENCES: readonly ReelAudience[] = ["public", "friends", "followers", "only_me"];
export const REEL_MAX_SECONDS = 90;
export const REEL_MAX_CAPTION = 2200;

export interface ReelInfo {
  media_id: string;
  cover_media_id: string | null;
  duration_ms: number;
  width: number;
  height: number;
  view_count: number;
  viewed_today: boolean;
}

export interface Reel extends Post {
  type: "reel";
  reel: ReelInfo;
}

export interface ReelEligibility {
  media_id: string;
  eligible: boolean;
  /** Why not: reel_not_vertical | reel_too_long | reel_video_not_ready | ... */
  code: string | null;
  duration_ms: number | null;
  width: number | null;
  height: number | null;
  max_duration_ms: number;
}

/** Server codes → i18n keys (toasts.error / errorMessage). */
export const REEL_ERRORS: Record<string, string> = {
  reel_not_vertical: "reels.errors.notVertical",
  reel_too_long: "reels.errors.tooLong",
  reel_video_not_ready: "reels.errors.notReady",
  reel_video_required: "reels.errors.videoRequired",
  reel_cover_invalid: "reels.errors.coverInvalid",
  media_not_owned: "reels.errors.mediaFailed",
  media_not_ready: "reels.errors.coverNotReady",
  media_already_attached: "reels.errors.alreadyPosted",
  reel_own: "reels.errors.own",
};

export const reelsService = {
  async feed(tab: ReelTab = "for_you", cursor?: string | null): Promise<CursorPage<Reel>> {
    const { data } = await api.get<CursorPage<Reel>>("/reels/", { params: { tab, cursor: cursor || undefined } });
    return data;
  },

  /** One profile's or page's reels (their Reels tab), newest first. */
  async byAuthor(authorId: string, cursor?: string | null): Promise<CursorPage<Reel>> {
    const { data } = await api.get<CursorPage<Reel>>("/reels/", { params: { author_id: authorId, cursor: cursor || undefined } });
    return data;
  },

  async get(id: string): Promise<Reel> {
    const { data } = await api.get<{ data: Reel }>(`/reels/${id}/`);
    return data.data;
  },

  async eligibility(mediaId: string): Promise<ReelEligibility> {
    const { data } = await api.post<{ data: ReelEligibility }>("/reels/eligibility/", { media_id: mediaId });
    return data.data;
  },

  async create(payload: {
    media_id: string;
    cover_media_id?: string | null;
    caption?: string;
    audience?: ReelAudience;
  }): Promise<Reel> {
    const { data } = await api.post<{ data: Reel }>("/reels/", {
      media_id: payload.media_id,
      cover_media_id: payload.cover_media_id || null,
      caption: payload.caption ?? "",
      audience: payload.audience ?? "public",
    });
    return data.data;
  },

  /** Counted once per viewer per day by the server, after at least 1 s of real
   * play (`watchMs`, D12); the author's never count. */
  async view(id: string, watchMs: number): Promise<{ view_count: number; counted: boolean }> {
    const { data } = await api.post<{ data: { view_count: number; counted: boolean } }>(`/reels/${id}/view/`, {
      watch_ms: Math.max(0, Math.round(watchMs)),
    });
    return data.data;
  },

  async hide(id: string): Promise<void> {
    await api.post(`/reels/${id}/hide/`);
  },

  async unhide(id: string): Promise<void> {
    await api.delete(`/reels/${id}/hide/`);
  },
};

export const isReel = (post: Pick<Post, "type"> | null | undefined): boolean => post?.type === "reel";
