import { api } from "@/lib/api";
import type { FeedItem, SponsoredSlot } from "@/types";

export interface FeedResponse {
  data: FeedItem[];
  sponsored: SponsoredSlot[];
  page: { next_cursor: string | null; has_more: boolean };
}

export const feedService = {
  /** Home feed. `sponsored` is a sibling of `data` in the envelope (see docs). */
  async home(cursor?: string): Promise<FeedResponse> {
    const { data } = await api.get<FeedResponse>("/feed/", { params: { cursor } });
    return data;
  },
};
