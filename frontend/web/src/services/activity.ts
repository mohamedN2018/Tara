// The settings activity log (GET /posts/activity/): the signed-in account's own
// posts, comments, reactions, comment reactions, saves and poll votes, newest
// first. Searches come from the search service's own recent-searches list.
// Owner-only on the server: there is no account id to pass.
import { api } from "@/lib/api";
import type { CursorPage } from "@/types";

export type ActivityKind = "post" | "comment" | "reaction" | "comment_reaction" | "save" | "vote";

export interface ActivityTarget {
  post_id: string;
  author_id: string;
  author_type: string;
  type: string;
  excerpt: string;
}

export interface ActivityRow {
  id: string;
  kind: ActivityKind;
  created_at: string;
  /** Reactions: the reaction type. */
  reaction: string | null;
  /** My own text: a post's or comment's start, a voted option, a reacted comment's start. */
  text: string;
  /** Posts: the post type. Saves: post | listing | page | video. */
  item_type: string | null;
  /** Comments: the comment id. Saves: the saved item's id. */
  item_id: string | null;
  /** The post acted on, while I may still see it; null otherwise. */
  target: ActivityTarget | null;
}

export const activityService = {
  async list(kind?: ActivityKind | null, cursor?: string | null): Promise<CursorPage<ActivityRow>> {
    const { data } = await api.get<CursorPage<ActivityRow>>("/posts/activity/", {
      params: { kind: kind || undefined, cursor: cursor || undefined },
    });
    return data;
  },
};
