import { api } from "@/lib/api";
import type { Listing, Post, Profile } from "@/types";

export interface SearchResults {
  people: Profile[];
  posts: Post[];
  listings: Listing[];
}

export const searchService = {
  async query(q: string, type: "all" | "people" | "posts" | "listings" = "all"): Promise<SearchResults> {
    const { data } = await api.get<{ data: SearchResults }>("/search/", { params: { q, type } });
    return data.data;
  },

  async suggest(q: string): Promise<string[]> {
    const { data } = await api.get<{ data: string[] }>("/search/autocomplete/", { params: { q } });
    return data.data;
  },
};
