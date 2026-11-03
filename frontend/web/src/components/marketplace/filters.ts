// Marketplace browse state <-> API query <-> route query. One shape, so the URL
// is shareable and back/forward restore the same filters.
import type { ListingQuery } from "@/services/marketplace";

export const SORTS = ["newest", "price_asc", "price_desc"] as const;
export type SortKey = (typeof SORTS)[number];
export const CONDITIONS = ["new", "like_new", "good", "fair"] as const;
export const AVAILABILITIES = ["available", "reserved", "sold"] as const;

export interface BrowseFilters {
  q: string;
  category: string;
  condition: string[];
  price_type: string[];
  availability: string[]; // empty = the server default ("available")
  location: string;
  currency: string;
  min_price: string;
  max_price: string;
  sort: SortKey;
}

export function emptyFilters(): BrowseFilters {
  return {
    q: "",
    category: "",
    condition: [],
    price_type: [],
    availability: [],
    location: "",
    currency: "",
    min_price: "",
    max_price: "",
    sort: "newest",
  };
}

const list = (v: unknown): string[] =>
  typeof v === "string" && v ? v.split(",").filter(Boolean) : [];
const text = (v: unknown): string => (typeof v === "string" ? v : "");

/** Read filters from a route query, dropping anything malformed. */
export function fromRouteQuery(query: Record<string, unknown>): BrowseFilters {
  const f = emptyFilters();
  f.q = text(query.q).slice(0, 100);
  f.category = text(query.category);
  f.condition = list(query.condition).filter((c) => (CONDITIONS as readonly string[]).includes(c));
  f.price_type = list(query.price_type).filter((p) => ["fixed", "negotiable", "free"].includes(p));
  f.availability = list(query.availability).filter((a) =>
    (AVAILABILITIES as readonly string[]).includes(a),
  );
  f.location = text(query.location).slice(0, 160);
  f.currency = text(query.currency).toUpperCase();
  const price = (v: unknown) => (/^\d+(\.\d+)?$/.test(text(v)) ? text(v) : "");
  f.min_price = price(query.min_price);
  f.max_price = price(query.max_price);
  const sort = text(query.sort);
  f.sort = (SORTS as readonly string[]).includes(sort) ? (sort as SortKey) : "newest";
  return f;
}

/** Only non-default values, so URLs stay short. */
export function toRouteQuery(f: BrowseFilters): Record<string, string> {
  const out: Record<string, string> = {};
  if (f.q.trim()) out.q = f.q.trim();
  if (f.category) out.category = f.category;
  if (f.condition.length) out.condition = f.condition.join(",");
  if (f.price_type.length) out.price_type = f.price_type.join(",");
  if (f.availability.length) out.availability = f.availability.join(",");
  if (f.location.trim()) out.location = f.location.trim();
  if (f.currency) out.currency = f.currency;
  if (f.min_price) out.min_price = f.min_price;
  if (f.max_price) out.max_price = f.max_price;
  if (f.sort !== "newest") out.sort = f.sort;
  return out;
}

export function toApiQuery(f: BrowseFilters, cursor?: string): ListingQuery {
  return { ...toRouteQuery(f), ...(cursor ? { cursor } : {}) };
}

/** Toggle one value in a multi-select dimension (returns a new array). */
export function toggle(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}

/**
 * Availability toggle. No filter means "available" (the server default), so a
 * toggle starts from that, and a result of just "available" is stored as none.
 */
export function toggleAvailability(values: string[], value: string): string[] {
  const next = toggle(values.length ? values : ["available"], value);
  return next.length === 1 && next[0] === "available" ? [] : next;
}

/** How many filters are on (the search box and sort excluded), for the filter button badge. */
export function activeCount(f: BrowseFilters): number {
  return (
    (f.category ? 1 : 0) +
    f.condition.length +
    f.price_type.length +
    f.availability.length +
    (f.location.trim() ? 1 : 0) +
    (f.currency ? 1 : 0) +
    (f.min_price || f.max_price ? 1 : 0)
  );
}
