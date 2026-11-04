import { api } from "@/lib/api";

// Graph's relationship privacy, suggestions and owner-private preferences
// (roadmap 1.6, plan 08 track 2D). Everything lives under /social/, which the
// edge routes to graph.

export type ListVisibility = "public" | "friends" | "only_me";

export interface RelationshipSettings {
  friends_list_visibility: ListVisibility;
  follow_lists_visibility: ListVisibility;
  counts_visibility: ListVisibility;
  friend_requests_from: "everyone" | "friends_of_friends";
}

export interface RelationshipCounts {
  friends_count: number;
  followers_count: number;
  following_count: number;
  /** Null for yourself, or while their friend list is hidden from you. */
  mutual_count: number | null;
}

export interface PersonSuggestion {
  account_id: string;
  mutual_count: number;
  reason: "mutual_friends" | "follows_you";
}

export interface PageSuggestion {
  page_id: string;
  handle: string;
  name: string;
  category: string;
  avatar_media_id: string | null;
  followers_count: number;
}

export type Preference = "mutes" | "restricted" | "favorites";
const LIST_KEY: Record<Preference, string> = { mutes: "muted", restricted: "restricted", favorites: "favorites" };

export const relationshipsService = {
  async settings(): Promise<RelationshipSettings> {
    const { data } = await api.get<{ data: RelationshipSettings }>("/social/settings/");
    return data.data;
  },
  async updateSettings(changes: Partial<RelationshipSettings>): Promise<RelationshipSettings> {
    const { data } = await api.patch<{ data: RelationshipSettings }>("/social/settings/", changes);
    return data.data;
  },
  /** 404 (rejected) when their counts are hidden from you. */
  async counts(userId: string): Promise<RelationshipCounts> {
    const { data } = await api.get<{ data: RelationshipCounts }>(`/social/${userId}/counts/`);
    return data.data;
  },

  async people(limit = 10): Promise<PersonSuggestion[]> {
    const { data } = await api.get<{ data: { results?: PersonSuggestion[] } }>("/social/suggestions/", {
      params: { limit },
    });
    return data.data?.results ?? [];
  },
  async pages(limit = 5): Promise<PageSuggestion[]> {
    const { data } = await api.get<{ data: { results?: PageSuggestion[] } }>("/social/suggestions/pages/", {
      params: { limit },
    });
    return data.data?.results ?? [];
  },
  async dismiss(targetId: string, targetType: "user" | "page" = "user"): Promise<void> {
    await api.post(`/social/suggestions/${targetId}/dismiss/`, { target_type: targetType });
  },

  /** Undo a dismissal: the person or page can be suggested again. */
  async undismiss(targetId: string, targetType: "user" | "page" = "user"): Promise<void> {
    await api.delete(`/social/suggestions/${targetId}/dismiss/`, { params: { target_type: targetType } });
  },

  /** Owner-only lists: who I muted, restricted or marked as a favorite. */
  async list(kind: Preference): Promise<string[]> {
    const { data } = await api.get<{ data: Record<string, string[]> }>(`/social/${kind}/`);
    return data.data?.[LIST_KEY[kind]] ?? [];
  },
  async add(kind: Preference, userId: string): Promise<void> {
    await api.post(`/social/${kind}/${userId}/`);
  },
  async remove(kind: Preference, userId: string): Promise<void> {
    await api.delete(`/social/${kind}/${userId}/`);
  },
};
