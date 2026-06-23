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
  // NOTE: there is no "am I following X" endpoint; follow state defaults to
  // unknown. Use GET /follows/following/ and check membership if needed.

  async sendFriendRequest(userId: string): Promise<void> {
    await api.post(`/friends/requests/`, { to_user_id: userId });
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
  async friends(): Promise<string[]> {
    // Returns { friends: [<id>, ...] }.
    const { data } = await api.get<{ data: { friends: string[] } }>("/friends/");
    return data.data.friends;
  },

  async block(userId: string): Promise<void> {
    await api.post(`/blocks/${userId}/`);
  },
  async unblock(userId: string): Promise<void> {
    await api.delete(`/blocks/${userId}/`);
  },
};
