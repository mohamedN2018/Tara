import { api } from "@/lib/api";

export type FriendState = "none" | "pending_out" | "pending_in" | "friends";

export interface FriendRequest {
  id: string;
  from_user_id: string;
  to_user_id: string;
  created_at: string;
}

// Raw friendship row as serialized by the graph service.
interface Friendship {
  id: string;
  account_low_id: string;
  account_high_id: string;
  status: string;
  requested_by: string;
  created_at: string;
  accepted_at: string | null;
}

export const graphService = {
  async follow(userId: string): Promise<void> {
    await api.post(`/follows/${userId}/`);
  },
  async unfollow(userId: string): Promise<void> {
    await api.delete(`/follows/${userId}/`);
  },
  async followPage(pageId: string): Promise<void> {
    await api.post(`/follows/${pageId}/`, { target_type: "page" });
  },
  async unfollowPage(pageId: string): Promise<void> {
    await api.delete(`/follows/${pageId}/`, { params: { target_type: "page" } });
  },
  // NOTE: there is no "am I following X" endpoint; follow state defaults to
  // unknown. Use GET /follows/following/ and check membership if needed.

  /** Returns the new request's id (needed to cancel it through reject/). */
  async sendFriendRequest(userId: string): Promise<string | undefined> {
    const { data } = await api.post<{ data?: Friendship } | Friendship>(`/friends/requests/`, { to_user_id: userId });
    const row = data && "data" in data ? data.data : (data as Friendship | undefined);
    return row?.id;
  },
  async acceptFriendRequest(requestId: string): Promise<void> {
    await api.post(`/friends/requests/${requestId}/accept/`);
  },
  async declineFriendRequest(requestId: string): Promise<void> {
    await api.post(`/friends/requests/${requestId}/reject/`);
  },
  async removeFriend(userId: string): Promise<void> {
    await api.delete(`/friends/${userId}/`);
  },
  async incomingRequests(): Promise<FriendRequest[]> {
    // Default direction is incoming; rows are Friendship objects (requested_by
    // is the sender). Normalize to the FriendRequest shape the UI expects.
    const { data } = await api.get<{ data: Friendship[] }>("/friends/requests/");
    return data.data.map((f) => ({
      id: f.id,
      from_user_id: f.requested_by,
      to_user_id: "",
      created_at: f.created_at,
    }));
  },
  async outgoingRequests(): Promise<FriendRequest[]> {
    // For outgoing, requested_by is me; the target is the other account in the pair.
    const { data } = await api.get<{ data: Friendship[] }>("/friends/requests/", {
      params: { direction: "outgoing" },
    });
    return data.data.map((f) => ({
      id: f.id,
      from_user_id: f.requested_by,
      to_user_id: f.account_low_id === f.requested_by ? f.account_high_id : f.account_low_id,
      created_at: f.created_at,
    }));
  },
  async friends(): Promise<string[]> {
    // Returns { friends: [<id>, ...] }.
    const { data } = await api.get<{ data: { friends: string[] } }>("/friends/");
    return data.data.friends;
  },

  // Who I follow / who follows me (for real follow-state + counts).
  async followingIds(): Promise<string[]> {
    const { data } = await api.get<{
      data: { following: { target_id: string; target_type: string }[] };
    }>("/follows/following/");
    return data.data.following.filter((f) => f.target_type === "user").map((f) => f.target_id);
  },
  async followerIds(): Promise<string[]> {
    const { data } = await api.get<{ data: { followers: string[] } }>("/follows/followers/");
    return data.data.followers;
  },

  // Public relationship lists for any user_id.
  async socialFriends(userId: string): Promise<string[]> {
    const { data } = await api.get<{ data: { friends: string[] } }>(`/social/${userId}/friends/`);
    return data.data.friends;
  },
  async socialFollowers(userId: string): Promise<string[]> {
    const { data } = await api.get<{ data: { followers: string[] } }>(
      `/social/${userId}/followers/`,
    );
    return data.data.followers;
  },
  /** What another account follows (people and pages); 404 while hidden from you. */
  async socialFollowing(userId: string): Promise<{ target_id: string; target_type: string }[]> {
    const { data } = await api.get<{ data: { following: { target_id: string; target_type: string }[] } }>(
      `/social/${userId}/following/`,
    );
    return data.data.following;
  },
  async mutualFriends(userId: string): Promise<string[]> {
    const { data } = await api.get<{ data: { mutual: string[] } }>(`/social/${userId}/mutual/`);
    return data.data.mutual;
  },

  async block(userId: string): Promise<void> {
    await api.post(`/blocks/${userId}/`);
  },
  async unblock(userId: string): Promise<void> {
    await api.delete(`/blocks/${userId}/`);
  },
  async blockedIds(): Promise<string[]> {
    const { data } = await api.get<{ data: { blocked: string[] } }>("/blocks/");
    return data.data.blocked;
  },
};
