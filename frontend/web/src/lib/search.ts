/**
 * Pure helpers for unified search (top-bar dropdown and the results page).
 * Kept free of Vue so the keyboard, grouping and URL rules are unit-tested.
 */
import type { LocationQuery, LocationQueryRaw } from "vue-router";

import type { Relationship, SearchFilters, SearchResult, SearchTab } from "@/services/search";
import { SEARCH_TABS } from "@/services/search";
import type { Listing } from "@/types";

// ---- keyboard navigation -------------------------------------------------------

/**
 * Next active row for a key press in a list of `count` rows. `-1` means no row
 * is active (the caret stays in the input). ArrowDown/ArrowUp wrap around and
 * are vertical, so they mean the same thing in RTL and LTR; Home/End jump.
 * Returns `null` for keys the list does not handle.
 */
export function nextActive(current: number, count: number, key: string): number | null {
  if (count <= 0) return key === "ArrowDown" || key === "ArrowUp" ? -1 : null;
  switch (key) {
    case "ArrowDown":
      return current < 0 || current >= count - 1 ? 0 : current + 1;
    case "ArrowUp":
      return current <= 0 ? count - 1 : current - 1;
    case "Home":
      return 0;
    case "End":
      return count - 1;
    default:
      return null;
  }
}

// ---- suggestion grouping --------------------------------------------------------

export const SUGGEST_ORDER = ["user", "page", "group", "hashtag"] as const;

export interface SuggestionGroup {
  type: string;
  items: SearchResult[];
}

/** Suggestions grouped by type in a fixed order; unknown types are dropped. */
export function groupSuggestions(results: SearchResult[]): SuggestionGroup[] {
  const seen = new Set<string>();
  return SUGGEST_ORDER.map((type) => ({
    type,
    items: results.filter((r) => {
      if (r.type !== type) return false;
      const key = `${r.type}:${r.id}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }),
  })).filter((g) => g.items.length > 0);
}

/** Sections of the "All" tab, in display order. */
export const ALL_SECTIONS: { type: string; tab: SearchTab }[] = [
  { type: "user", tab: "people" },
  { type: "page", tab: "pages" },
  { type: "group", tab: "groups" },
  { type: "post", tab: "posts" },
  { type: "listing", tab: "marketplace" },
  { type: "gathering", tab: "events" },
  { type: "hashtag", tab: "hashtags" },
];

/** Append a page of results, skipping any (type, id) already shown. */
export function mergeResults(current: SearchResult[], incoming: SearchResult[]): SearchResult[] {
  const seen = new Set(current.map((r) => `${r.type}:${r.id}`));
  const out = [...current];
  for (const r of incoming) {
    const key = `${r.type}:${r.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(r);
  }
  return out;
}

// ---- URL <-> filters ----------------------------------------------------------

export interface SearchState extends SearchFilters {
  q: string;
  type: SearchTab;
}

const DATES = ["any", "day", "week", "month", "year"] as const;
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

function one(value: LocationQuery[string]): string {
  const v = Array.isArray(value) ? value[0] : value;
  return typeof v === "string" ? v : "";
}

/** Which contextual filters a tab offers. */
export function filtersFor(tab: SearchTab): { date: boolean; category: boolean; location: boolean } {
  return {
    date: ["posts", "photos", "events", "marketplace"].includes(tab),
    category: ["pages", "groups", "marketplace"].includes(tab),
    location: ["people", "pages", "marketplace", "events"].includes(tab),
  };
}

/** Read the search state from the URL; invalid values fall back to defaults. */
export function stateFromQuery(query: LocationQuery): SearchState {
  const rawType = one(query.type);
  const type = (SEARCH_TABS as readonly string[]).includes(rawType) ? (rawType as SearchTab) : "all";
  const rawDate = one(query.date);
  const date = (DATES as readonly string[]).includes(rawDate) ? (rawDate as SearchState["date"]) : "any";
  const from = one(query.from);
  const to = one(query.to);
  return {
    q: one(query.q).trim(),
    type,
    sort: one(query.sort) === "recent" ? "recent" : "relevance",
    date,
    from: ISO_DAY.test(from) ? from : undefined,
    to: ISO_DAY.test(to) ? to : undefined,
    category: one(query.category).trim() || undefined,
    location: one(query.location).trim() || undefined,
  };
}

/** The URL query for a state: defaults and filters the tab does not use are left out. */
export function queryFromState(state: SearchState): LocationQueryRaw {
  const f = filtersFor(state.type);
  const out: LocationQueryRaw = { q: state.q };
  if (state.type !== "all") out.type = state.type;
  if (state.sort === "recent") out.sort = "recent";
  if (f.date && state.date && state.date !== "any") out.date = state.date;
  if (f.date && state.from) out.from = state.from;
  if (f.date && state.to) out.to = state.to;
  if (f.category && state.category) out.category = state.category;
  if (f.location && state.location) out.location = state.location;
  return out;
}

/** The filters to send for a state (only the ones the tab uses). */
export function filtersOf(state: SearchState): SearchFilters {
  const f = filtersFor(state.type);
  return {
    sort: state.sort,
    date: f.date ? state.date : undefined,
    from: f.date ? state.from : undefined,
    to: f.date ? state.to : undefined,
    category: f.category ? state.category : undefined,
    location: f.location ? state.location : undefined,
  };
}

// ---- result cards ----------------------------------------------------------------

export type PersonAction = "add" | "requested" | "confirm" | "friends" | "none";

/** The primary action a person card offers for the viewer's relationship. */
export function personAction(rel: Relationship | null | undefined): PersonAction {
  switch (rel?.state) {
    case "none":
      return "add";
    case "pending_out":
      return "requested";
    case "pending_in":
      return rel.request_id ? "confirm" : "requested";
    case "friends":
      return "friends";
    default:
      return "none"; // self, or graph did not answer: no action
  }
}

/** A Follow toggle is offered to non-friends only (and never for yourself). */
export function canFollow(rel: Relationship | null | undefined): boolean {
  return !!rel && rel.state !== "self" && rel.state !== "friends";
}

/** A listing hit as a `Listing`, so the marketplace card can render it. */
export function resultToListing(r: SearchResult): Listing {
  const category = r.category && typeof r.category === "object" ? r.category : null;
  return {
    id: r.id,
    seller_id: r.seller_id ?? r.owner_id ?? "",
    title: r.title,
    description: r.snippet ?? "",
    price: r.price ?? null,
    price_type: r.price_type,
    sale_price: r.sale_price ?? null,
    effective_price: r.effective_price ?? null,
    currency: r.currency ?? "",
    condition: r.condition ?? "good",
    location: r.location ?? "",
    status: "active",
    availability: "available",
    save_count: 0,
    created_at: r.created_at ?? "",
    category: category
      ? { id: category.slug, slug: category.slug, name: category.name, parent_id: null, position: 0 }
      : undefined,
    media: r.cover_media_id ? [{ media_id: r.cover_media_id, position: 0 }] : [],
  };
}

/** The category label of a page, group or listing hit. */
export function categoryLabel(r: SearchResult): string {
  if (!r.category) return "";
  return typeof r.category === "string" ? r.category : r.category.name;
}
