import { api } from "@/lib/api";

// Both /search/ and /search/autocomplete/ return a unified hit list:
//   { data: { results: Suggestion[], … } }
export interface Suggestion {
  type: string; // "user" | "post" | "listing"
  id: string;
  title: string;
  snippet: string;
  owner_id: string;
}

export const searchService = {
  async query(
    q: string,
    type: "all" | "people" | "posts" | "listings" = "all",
  ): Promise<Suggestion[]> {
    const { data } = await api.get<{ data: { results: Suggestion[] } }>("/search/", {
      params: { q, type },
    });
    return data.data?.results ?? [];
  },

  async suggest(q: string): Promise<Suggestion[]> {
    const { data } = await api.get<{ data: { results: Suggestion[] } }>("/search/autocomplete/", {
      params: { q },
    });
    return data.data?.results ?? [];
  },
};
