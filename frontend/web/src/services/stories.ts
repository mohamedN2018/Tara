// Stories (track T9, roadmap 1.9): photo and text stories that last 24 hours,
// audiences (public / friends / close friends), the author's viewer list, the
// archive of my own stories and my close friends list. Every rule is the post
// service's (services/post/stories): a story the viewer may not see is a 404.
import { api } from "@/lib/api";
import { chatService } from "@/services/chat";
import { mediaService } from "@/services/media";
import type { CursorPage } from "@/types";

export type StoryKind = "photo" | "text";
export type StoryAudience = "public" | "friends" | "close_friends";

export const STORY_AUDIENCES: StoryAudience[] = ["friends", "public", "close_friends"];
/** Mirrors services/post/stories/models.py BACKGROUNDS (names, not colours). */
export const STORY_BACKGROUNDS = ["violet", "dusk", "magenta", "night", "aurora", "sunset"] as const;
export type StoryBackground = (typeof STORY_BACKGROUNDS)[number];
export const STORY_MAX_TEXT = 500;
/** Mirrors gatherings.models.ReportReason, so the report event carries an enum. */
export const STORY_REPORT_REASONS = [
  "spam",
  "scam",
  "hate",
  "violence",
  "nudity",
  "harassment",
  "false_information",
  "other",
] as const;
export type StoryReportReason = (typeof STORY_REPORT_REASONS)[number];

/** Brand gradients for text stories (and cards without a photo). */
export const BACKGROUND_STYLES: Record<StoryBackground, string> = {
  violet: "linear-gradient(160deg,#6A00F4 0%,#A855F7 100%)",
  dusk: "linear-gradient(160deg,#0B0B1F 0%,#6A00F4 100%)",
  magenta: "linear-gradient(160deg,#A855F7 0%,#FF4ED8 100%)",
  night: "linear-gradient(160deg,#0B0B1F 0%,#2A1460 100%)",
  aurora: "linear-gradient(160deg,#6A00F4 0%,#22D3EE 100%)",
  sunset: "linear-gradient(160deg,#FF4ED8 0%,#FF8A65 100%)",
};

export function backgroundStyle(name: string | null | undefined): string {
  return BACKGROUND_STYLES[(name as StoryBackground) ?? "violet"] ?? BACKGROUND_STYLES.violet;
}

export interface Story {
  id: string;
  author_id: string;
  kind: StoryKind;
  media_id: string | null;
  text: string;
  background: StoryBackground;
  audience: StoryAudience;
  created_at: string;
  expires_at: string;
  is_mine: boolean;
  is_active: boolean;
  seen: boolean;
  my_reaction: string | null;
  /** The author's alone; null for anyone else. */
  view_count: number | null;
  reaction_count: number | null;
}

export interface StoryGroup {
  author_id: string;
  has_unseen: boolean;
  latest_at: string;
  stories: Story[];
}

export interface StoryViewer {
  account_id: string;
  viewed_at: string;
  reaction: string | null;
}

export interface CloseFriend {
  account_id: string;
  created_at: string;
}

export interface NewStory {
  kind: StoryKind;
  audience: StoryAudience;
  text?: string;
  background?: StoryBackground;
  media_id?: string | null;
}

/** Error codes the stories API answers with, mapped to friendly messages. */
export const STORY_ERRORS: Record<string, string> = {
  media_not_ready: "stories.errors.mediaNotReady",
  media_not_owned: "stories.errors.mediaFailed",
  media_kind_not_allowed: "stories.errors.mediaFailed",
  media_already_attached: "stories.errors.mediaFailed",
  media_required: "stories.errors.photoRequired",
  text_required: "stories.errors.textRequired",
  text_too_long: "stories.errors.textTooLong",
  story_limit: "stories.errors.limit",
  not_friend: "stories.errors.notFriend",
  not_found: "stories.errors.notFound",
  throttled: "errors.reportThrottled",
  rate_limited: "errors.reportThrottled",
};

function idempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export const storiesService = {
  /** Active stories of me and my friends, grouped by author (mine first). */
  async tray(): Promise<StoryGroup[]> {
    const { data } = await api.get<{ data: StoryGroup[] }>("/stories/tray/");
    return data.data;
  },

  /** One author's active stories I may see, oldest first. */
  async ofAuthor(authorId: string): Promise<Story[]> {
    const { data } = await api.get<{ data: Story[] }>("/stories/", { params: { author_id: authorId } });
    return data.data;
  },

  async get(id: string): Promise<Story> {
    const { data } = await api.get<{ data: Story }>(`/stories/${id}/`);
    return data.data;
  },

  async create(story: NewStory): Promise<Story> {
    const { data } = await api.post<{ data: Story }>("/stories/", story, {
      headers: { "Idempotency-Key": idempotencyKey() },
    });
    return data.data;
  },

  /** Upload a photo through the existing media flow; returns the media id. */
  async uploadPhoto(file: File): Promise<string> {
    return (await mediaService.upload(file, "image")).id;
  },

  async remove(id: string): Promise<void> {
    await api.delete(`/stories/${id}/`);
  },

  async markSeen(id: string): Promise<Story> {
    const { data } = await api.post<{ data: Story }>(`/stories/${id}/seen/`);
    return data.data;
  },

  async react(id: string, reaction: string): Promise<Story> {
    const { data } = await api.post<{ data: Story }>(`/stories/${id}/react/`, { reaction });
    return data.data;
  },

  async unreact(id: string): Promise<Story> {
    const { data } = await api.delete<{ data: Story }>(`/stories/${id}/react/`);
    return data.data;
  },

  /**
   * A reply goes to the author as a direct message (chat decides whether the
   * two may message), with a link back to the story. Returns the conversation.
   */
  async reply(story: Pick<Story, "author_id">, text: string, linkLine: string): Promise<string> {
    const conversation = await chatService.openDm(story.author_id);
    await chatService.send(conversation.id, { body: [text.trim(), linkLine].filter(Boolean).join("\n") });
    return conversation.id;
  },

  async report(id: string, reason: StoryReportReason): Promise<void> {
    await api.post(`/stories/${id}/report/`, { reason });
  },

  async viewers(id: string, cursor?: string | null): Promise<CursorPage<StoryViewer>> {
    const { data } = await api.get<CursorPage<StoryViewer>>(`/stories/${id}/viewers/`, {
      params: { cursor: cursor || undefined },
    });
    return data;
  },

  async archive(cursor?: string | null): Promise<CursorPage<Story>> {
    const { data } = await api.get<CursorPage<Story>>("/stories/archive/", {
      params: { cursor: cursor || undefined },
    });
    return data;
  },

  async closeFriends(cursor?: string | null): Promise<CursorPage<CloseFriend>> {
    const { data } = await api.get<CursorPage<CloseFriend>>("/stories/close-friends/", {
      params: { cursor: cursor || undefined },
    });
    return data;
  },

  /** Every close friend (the list is capped server-side at 500). */
  async allCloseFriends(): Promise<CloseFriend[]> {
    const all: CloseFriend[] = [];
    let cursor: string | null = null;
    for (let i = 0; i < 20; i++) {
      const page: CursorPage<CloseFriend> = await this.closeFriends(cursor);
      all.push(...page.data);
      if (!page.page?.has_more || !page.page.next_cursor) break;
      cursor = page.page.next_cursor;
    }
    return all;
  },

  async addCloseFriends(accountIds: string[]): Promise<string[]> {
    const { data } = await api.post<{ data: { added: string[] } }>("/stories/close-friends/", {
      account_ids: accountIds,
    });
    return data.data.added;
  },

  async removeCloseFriend(accountId: string): Promise<void> {
    await api.delete(`/stories/close-friends/${accountId}/`);
  },
};
