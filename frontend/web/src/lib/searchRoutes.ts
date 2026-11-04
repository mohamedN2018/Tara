import type { RouteLocationRaw } from "vue-router";

/**
 * Where a search entity (a suggestion, a recent search, a result) opens.
 * Listings and events open their own page; anything without a page of its own
 * falls back to a text search.
 */
export function entityRoute(type: string, id: string, title: string, handle?: string | null): RouteLocationRaw {
  if (type === "user") return { name: "profile-by-id", params: { id } };
  if (type === "page" && handle) return { name: "page", params: { handle } };
  if (type === "group") return `/groups/${encodeURIComponent(handle || id)}`;
  if (type === "listing") return { name: "listing", params: { id } };
  if (type === "gathering") return { name: "event", params: { id } };
  if (type === "post") return { name: "post", params: { id } };
  if (type === "hashtag") return { name: "search", query: { q: title.startsWith("#") ? title : `#${title}` } };
  return { name: "search", query: { q: title, type: type === "page" ? "pages" : undefined } };
}

/** The search route for a trending tag. */
export function tagRoute(tag: string): RouteLocationRaw {
  return { name: "search", query: { q: `#${tag.replace(/^#/, "")}` } };
}
