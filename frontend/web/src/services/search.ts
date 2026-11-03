import { api } from "@/lib/api";

/** Result kinds the search service indexes (`type` on every hit). */
export type ResultType = "user" | "post" | "page" | "group" | "listing" | "gathering" | "hashtag";

/** Tabs of the results page. Videos, reels, companies and jobs do not exist yet. */
export const SEARCH_TABS = [
  "all",
  "people",
  "posts",
  "photos",
  "pages",
  "groups",
  "marketplace",
  "events",
  "hashtags",
] as const;
export type SearchTab = (typeof SEARCH_TABS)[number];

export type RelationshipState = "self" | "friends" | "pending_out" | "pending_in" | "none";

export interface Relationship {
  state: RelationshipState;
  following: boolean;
  request_id: string | null;
}

/**
 * One hit from /search/ or /search/suggest/. The common fields are always set;
 * the rest depend on `type` (see the API contract), so they are optional here.
 */
export interface SearchResult {
  type: ResultType | string;
  id: string;
  title: string;
  snippet: string;
  owner_id: string | null;
  // people
  handle?: string;
  display_name?: string;
  avatar_media_id?: string | null;
  city?: string | null;
  relationship?: Relationship | null;
  mutual_count?: number | null;
  // pages and groups
  name?: string;
  category?: string | { slug: string; name: string } | null;
  followers_count?: number | null;
  following?: boolean | null;
  privacy?: "public" | "private";
  description?: string | null;
  member_count?: number | null;
  // listings
  price?: string | null;
  sale_price?: string | null;
  effective_price?: string | null;
  price_type?: "fixed" | "negotiable" | "free";
  currency?: string;
  condition?: string;
  location?: string;
  cover_media_id?: string | null;
  seller_id?: string;
  created_at?: string;
  // posts
  author_id?: string;
  author_type?: string;
  post_type?: string;
  media_ids?: string[];
  // events
  starts_at?: string;
  ends_at?: string | null;
  location_type?: "place" | "online";
  host_id?: string;
  going_count?: number;
  interested_count?: number;
  status?: string;
  // hashtags
  tag?: string;
  post_count?: number;
}

/** Kept for older importers (autocomplete, mentions). */
export type Suggestion = SearchResult;

export interface SearchFilters {
  sort?: "relevance" | "recent";
  date?: "any" | "day" | "week" | "month" | "year";
  from?: string;
  to?: string;
  category?: string;
  location?: string;
}

export interface SearchPage {
  results: SearchResult[];
  types: string[];
  degraded: boolean;
  nextCursor: string | null;
  hasMore: boolean;
}

export interface RecentSearch {
  id: string;
  kind: "query" | "entity";
  query: string;
  doc_type: string | null;
  doc_id: string | null;
  title: string;
  /** People, pages and groups: the handle their route needs. */
  handle?: string | null;
  avatar_media_id: string | null;
  created_at: string;
}

export interface TrendingTag {
  tag: string;
  authors: number;
  posts: number;
}

interface SearchResponse {
  data: { results: SearchResult[]; types?: string[]; degraded?: boolean };
  page?: { next_cursor: string | null; has_more: boolean };
}

/** Drop empty filter values so the URL and the request stay minimal. */
function clean(params: Record<string, string | number | undefined | null>) {
  return Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""),
  );
}

export const searchService = {
  async search(
    q: string,
    type: SearchTab = "all",
    filters: SearchFilters = {},
    cursor?: string | null,
    limit?: number,
  ): Promise<SearchPage> {
    const date = filters.date && filters.date !== "any" ? filters.date : undefined;
    const sort = filters.sort && filters.sort !== "relevance" ? filters.sort : undefined;
    const { data } = await api.get<SearchResponse>("/search/", {
      params: clean({
        q,
        type,
        cursor: cursor ?? undefined,
        limit,
        sort,
        date,
        from: filters.from,
        to: filters.to,
        category: filters.category,
        location: filters.location,
      }),
    });
    return {
      results: data.data?.results ?? [],
      types: data.data?.types ?? [...SEARCH_TABS],
      degraded: !!data.data?.degraded,
      nextCursor: data.page?.next_cursor ?? null,
      hasMore: !!data.page?.has_more,
    };
  },

  /** Back-compatible flat list (first page of `all`). */
  async query(q: string, type: SearchTab = "all"): Promise<SearchResult[]> {
    return (await this.search(q, type)).results;
  },

  /** Fast autocomplete over people, pages, groups and hashtags (≤ 8). */
  async suggest(q: string): Promise<SearchResult[]> {
    const { data } = await api.get<{ data: { results: SearchResult[] } }>("/search/suggest/", {
      params: { q },
    });
    return data.data?.results ?? [];
  },

  async recent(): Promise<RecentSearch[]> {
    const { data } = await api.get<{ data: RecentSearch[] }>("/search/recent/");
    return data.data ?? [];
  },
  async rememberQuery(query: string): Promise<RecentSearch> {
    const { data } = await api.post<{ data: RecentSearch }>("/search/recent/", { query });
    return data.data;
  },
  async rememberEntity(docType: string, docId: string): Promise<RecentSearch> {
    const { data } = await api.post<{ data: RecentSearch }>("/search/recent/", {
      doc_type: docType,
      doc_id: docId,
    });
    return data.data;
  },
  async forget(id: string): Promise<void> {
    await api.delete(`/search/recent/${id}/`);
  },
  async clearRecent(): Promise<void> {
    await api.delete("/search/recent/");
  },

  async trending(window: "day" | "week" = "week"): Promise<TrendingTag[]> {
    const { data } = await api.get<{ data: TrendingTag[] }>("/search/trending/", {
      params: { window },
    });
    return data.data ?? [];
  },
};
