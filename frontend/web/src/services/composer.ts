// The composer's API (plan 08, track 2C): create with tags, location, feeling,
// drafts and scheduling; the author's drafts and scheduled posts; the
// "who can tag me" setting. Every rule is enforced by the post service.
import { api } from "@/lib/api";
import type { CommentPolicy } from "@/services/post";
import type { CursorPage, Post } from "@/types";

export type PostState = "published" | "draft" | "scheduled";
export type TagPolicy = "everyone" | "friends" | "nobody";
export const TAG_POLICIES: TagPolicy[] = ["everyone", "friends", "nobody"];

/** The fields 2C adds to a post (the shared `Post` type stays as it is). */
export interface ComposerFields {
  state?: PostState;
  publish_at?: string | null;
  location?: string;
  feeling?: string;
  tagged_ids?: string[];
  updated_at?: string;
}
export type ComposerPost = Post & ComposerFields;

/** Mirrors FEELING_KEYS / ACTIVITY_KEYS in services/post/posts/models.py. */
export const FEELINGS = [
  "happy",
  "loved",
  "excited",
  "grateful",
  "blessed",
  "proud",
  "relaxed",
  "motivated",
  "hopeful",
  "sad",
  "tired",
  "sick",
] as const;
export const ACTIVITIES = [
  "celebrating",
  "traveling",
  "eating",
  "drinking",
  "watching",
  "reading",
  "listening",
  "playing",
  "working",
  "studying",
  "exercising",
  "praying",
] as const;
export const FEELING_EMOJI: Record<string, string> = {
  happy: "😊",
  loved: "🥰",
  excited: "🤩",
  grateful: "🙏",
  blessed: "😇",
  proud: "😌",
  relaxed: "😎",
  motivated: "💪",
  hopeful: "🌱",
  sad: "😢",
  tired: "😴",
  sick: "🤒",
  celebrating: "🎉",
  traveling: "✈️",
  eating: "🍽️",
  drinking: "☕",
  watching: "🎬",
  reading: "📖",
  listening: "🎧",
  playing: "🎮",
  working: "💼",
  studying: "📚",
  exercising: "🏃",
  praying: "🕌",
};
export const isActivity = (key: string) => (ACTIVITIES as readonly string[]).includes(key);

/** Server limits (services/post/posts/composer.py). */
export const LOCATION_MAX = 120;
export const MAX_TAGS = 20;
export const MAX_SCHEDULE_DAYS = 75;

export interface ComposerPayload {
  body: string;
  audience?: string;
  media_ids?: string[];
  /** "video" for one transcoded video (services/video.ts); photos and text are inferred. */
  type?: "video";
  poll?: { options: string[]; duration_hours?: number | null };
  comment_policy?: CommentPolicy;
  group_id?: string;
  tagged_ids?: string[];
  location?: string;
  feeling?: string;
  /** Keep it as a draft. */
  draft?: boolean;
  /** ISO time: schedule it (in the future, at most 75 days ahead). */
  publish_at?: string | null;
}

export type DraftChanges = Partial<
  Pick<ComposerPayload, "body" | "audience" | "comment_policy" | "tagged_ids" | "location" | "feeling">
> & { publish_at?: string | null };

/** Error codes the composer explains itself (`errors.*` covers the rest). */
export const COMPOSER_ERRORS: Record<string, string> = {
  tag_not_allowed: "composer.errors.tagNotAllowed",
  too_many_tags: "composer.errors.tooManyTags",
  location_too_long: "composer.errors.locationTooLong",
  invalid_feeling: "composer.errors.invalidFeeling",
  publish_at_past: "composer.errors.publishAtPast",
  publish_at_too_far: "composer.errors.publishAtTooFar",
  group_drafts_not_supported: "composer.errors.groupDrafts",
};

export const composerService = {
  async create(payload: ComposerPayload): Promise<ComposerPost> {
    const mediaIds = payload.media_ids ?? [];
    const { data } = await api.post<{ data: ComposerPost }>("/posts/", {
      type: payload.type ?? (mediaIds.length ? "image" : "text"),
      audience: payload.audience ?? "public",
      media_ids: mediaIds,
      body: payload.body,
      ...(payload.poll ? { poll: payload.poll } : {}),
      ...(payload.comment_policy ? { comment_policy: payload.comment_policy } : {}),
      ...(payload.group_id ? { group_id: payload.group_id } : {}),
      ...(payload.tagged_ids?.length ? { tagged_ids: payload.tagged_ids } : {}),
      ...(payload.location ? { location: payload.location } : {}),
      ...(payload.feeling ? { feeling: payload.feeling } : {}),
      ...(payload.publish_at ? { publish_at: payload.publish_at } : payload.draft ? { draft: true } : {}),
    });
    return data.data;
  },

  async drafts(state?: "draft" | "scheduled", cursor?: string | null): Promise<CursorPage<ComposerPost>> {
    const { data } = await api.get<CursorPage<ComposerPost>>("/posts/drafts/", {
      params: { state: state || undefined, cursor: cursor || undefined },
    });
    return data;
  },

  /** One of my drafts or scheduled posts (404 for anything else): deep links. */
  async draft(id: string): Promise<ComposerPost> {
    const { data } = await api.get<{ data: ComposerPost }>(`/posts/drafts/${id}/`);
    return data.data;
  },

  async editDraft(id: string, changes: DraftChanges): Promise<ComposerPost> {
    const { data } = await api.patch<{ data: ComposerPost }>(`/posts/drafts/${id}/`, changes);
    return data.data;
  },

  async publishDraft(id: string): Promise<ComposerPost> {
    const { data } = await api.post<{ data: ComposerPost }>(`/posts/drafts/${id}/publish/`);
    return data.data;
  },

  async deleteDraft(id: string): Promise<void> {
    await api.delete(`/posts/drafts/${id}/`);
  },

  async settings(): Promise<{ who_can_tag: TagPolicy }> {
    const { data } = await api.get<{ data: { who_can_tag: TagPolicy } }>("/posts/settings/");
    return data.data;
  },

  async setWhoCanTag(value: TagPolicy): Promise<{ who_can_tag: TagPolicy }> {
    const { data } = await api.patch<{ data: { who_can_tag: TagPolicy } }>("/posts/settings/", { who_can_tag: value });
    return data.data;
  },

  /** Take my own tag off a post. */
  async removeMyTag(postId: string): Promise<void> {
    await api.delete(`/posts/${postId}/tags/me/`);
  },
};

// ---- the schedule picker: local time in, ISO out ------------------------------------

const pad = (n: number) => String(n).padStart(2, "0");

/** A `datetime-local` value (the viewer's own time zone) for a Date. */
export function toLocalInput(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** The ISO instant for a `datetime-local` value, read in the viewer's time zone. */
export function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const date = new Date(value); // no offset in the string: local time
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/** The earliest and latest values the picker offers (one minute ahead, 75 days ahead). */
export function scheduleBounds(now = new Date()): { min: string; max: string } {
  const min = new Date(now.getTime() + 60_000);
  const max = new Date(now.getTime() + MAX_SCHEDULE_DAYS * 86_400_000);
  return { min: toLocalInput(min), max: toLocalInput(max) };
}

/** `"past" | "far" | null` for a picked local time, as the server will judge it. */
export function scheduleProblem(value: string, now = new Date()): "past" | "far" | null {
  const iso = fromLocalInput(value);
  if (!iso) return "past";
  const at = new Date(iso).getTime();
  if (at <= now.getTime()) return "past";
  if (at > now.getTime() + MAX_SCHEDULE_DAYS * 86_400_000) return "far";
  return null;
}

export function timeZoneName(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}
