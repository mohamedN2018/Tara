import { describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import {
  canFollow,
  filtersFor,
  filtersOf,
  groupSuggestions,
  mergeResults,
  nextActive,
  personAction,
  queryFromState,
  resultToListing,
  stateFromQuery,
} from "@/lib/search";
import { type SearchResult, searchService } from "@/services/search";

const hit = (type: string, id: string, extra: Partial<SearchResult> = {}): SearchResult => ({
  type,
  id,
  title: `${type} ${id}`,
  snippet: "",
  owner_id: null,
  ...extra,
});

describe("keyboard navigation", () => {
  it("ArrowDown walks forward and wraps to the first row", () => {
    expect(nextActive(-1, 3, "ArrowDown")).toBe(0);
    expect(nextActive(0, 3, "ArrowDown")).toBe(1);
    expect(nextActive(2, 3, "ArrowDown")).toBe(0);
  });

  it("ArrowUp from the field or the first row goes to the last row", () => {
    expect(nextActive(-1, 3, "ArrowUp")).toBe(2);
    expect(nextActive(0, 3, "ArrowUp")).toBe(2);
    expect(nextActive(2, 3, "ArrowUp")).toBe(1);
  });

  it("is direction-agnostic: Left/Right are not list keys (caret moves in RTL and LTR)", () => {
    expect(nextActive(1, 3, "ArrowLeft")).toBeNull();
    expect(nextActive(1, 3, "ArrowRight")).toBeNull();
    expect(nextActive(1, 3, "Enter")).toBeNull();
  });

  it("an empty list keeps no active row", () => {
    expect(nextActive(-1, 0, "ArrowDown")).toBe(-1);
    expect(nextActive(-1, 0, "Escape")).toBeNull();
  });

  it("Home and End jump", () => {
    expect(nextActive(1, 4, "Home")).toBe(0);
    expect(nextActive(1, 4, "End")).toBe(3);
  });
});

describe("suggestion grouping", () => {
  it("groups people, pages, groups and hashtags in that order and drops other types", () => {
    const groups = groupSuggestions([
      hit("hashtag", "tara"),
      hit("user", "u1"),
      hit("listing", "l1"),
      hit("group", "g1"),
      hit("user", "u2"),
      hit("page", "p1"),
    ]);
    expect(groups.map((g) => g.type)).toEqual(["user", "page", "group", "hashtag"]);
    expect(groups[0].items.map((i) => i.id)).toEqual(["u1", "u2"]);
  });

  it("never shows the same hit twice", () => {
    const groups = groupSuggestions([hit("user", "u1"), hit("user", "u1")]);
    expect(groups[0].items).toHaveLength(1);
  });

  it("merging a next page skips results already shown", () => {
    const merged = mergeResults([hit("user", "a"), hit("post", "a")], [hit("user", "a"), hit("user", "b")]);
    expect(merged.map((r) => `${r.type}:${r.id}`)).toEqual(["user:a", "post:a", "user:b"]);
  });
});

describe("URL <-> filters", () => {
  it("reads a full query and falls back to defaults for junk", () => {
    expect(
      stateFromQuery({ q: " احمد ", type: "marketplace", sort: "recent", date: "week", from: "2026-01-01", category: "cars", location: "Cairo" }),
    ).toEqual({ q: "احمد", type: "marketplace", sort: "recent", date: "week", from: "2026-01-01", to: undefined, category: "cars", location: "Cairo" });
    const junk = stateFromQuery({ q: "x", type: "videos", sort: "best", date: "decade", from: "yesterday" });
    expect(junk).toMatchObject({ type: "all", sort: "relevance", date: "any", from: undefined });
  });

  it("writes only non-default filters the tab uses", () => {
    expect(queryFromState({ q: "x", type: "all", sort: "relevance", date: "any" })).toEqual({ q: "x" });
    expect(queryFromState({ q: "x", type: "people", sort: "recent", date: "week", category: "c", location: "Giza" })).toEqual({
      q: "x",
      type: "people",
      sort: "recent",
      location: "Giza",
    });
    expect(queryFromState({ q: "x", type: "events", date: "month", to: "2026-12-31" })).toEqual({
      q: "x",
      type: "events",
      date: "month",
      to: "2026-12-31",
    });
  });

  it("round-trips through the URL", () => {
    const state = stateFromQuery({ q: "bike", type: "marketplace", date: "day", category: "bikes", location: "Alex" });
    expect(stateFromQuery(queryFromState(state) as Record<string, string>)).toEqual(state);
  });

  it("offers contextual filters per tab and never videos, reels, companies or jobs", () => {
    expect(filtersFor("people")).toEqual({ date: false, category: false, location: true });
    expect(filtersFor("marketplace")).toEqual({ date: true, category: true, location: true });
    expect(filtersFor("hashtags")).toEqual({ date: false, category: false, location: false });
    expect(filtersOf({ q: "x", type: "people", date: "week", category: "c", location: "Giza" })).toMatchObject({
      date: undefined,
      category: undefined,
      location: "Giza",
    });
    expect(stateFromQuery({ q: "x", type: "reels" }).type).toBe("all");
  });
});

describe("people actions", () => {
  it("maps the viewer's relationship to the card's action", () => {
    expect(personAction({ state: "none", following: false, request_id: null })).toBe("add");
    expect(personAction({ state: "pending_out", following: false, request_id: null })).toBe("requested");
    expect(personAction({ state: "pending_in", following: false, request_id: "r1" })).toBe("confirm");
    expect(personAction({ state: "friends", following: true, request_id: null })).toBe("friends");
    expect(personAction({ state: "self", following: false, request_id: null })).toBe("none");
    expect(personAction(null)).toBe("none"); // graph did not answer: no action
  });

  it("offers Follow to non-friends only", () => {
    expect(canFollow({ state: "none", following: false, request_id: null })).toBe(true);
    expect(canFollow({ state: "friends", following: true, request_id: null })).toBe(false);
    expect(canFollow({ state: "self", following: false, request_id: null })).toBe(false);
    expect(canFollow(null)).toBe(false);
  });

  it("turns a listing hit into a Listing for the marketplace card", () => {
    const listing = resultToListing(
      hit("listing", "l1", {
        title: "دراجة",
        price: "100.0000",
        currency: "EGP",
        seller_id: "s1",
        location: "الإسكندرية",
        category: { slug: "bikes", name: "Bikes" },
        cover_media_id: "m1",
      }),
    );
    expect(listing).toMatchObject({ id: "l1", seller_id: "s1", status: "active", availability: "available", price: "100.0000" });
    expect(listing.media).toEqual([{ media_id: "m1", position: 0 }]);
    expect(listing.category?.slug).toBe("bikes");
  });
});

describe("search service", () => {
  it("sends only the filters that are set and reads the keyset page", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({
      data: { data: { results: [hit("user", "u1")], types: ["people"], degraded: false }, page: { next_cursor: "c2", has_more: true } },
    });
    const page = await searchService.search("x", "people", { sort: "relevance", date: "any", location: "Giza" }, "c1");
    expect(get).toHaveBeenCalledWith("/search/", { params: { q: "x", type: "people", cursor: "c1", location: "Giza" } });
    expect(page).toMatchObject({ nextCursor: "c2", hasMore: true, types: ["people"] });
  });

  it("records queries and entities, and clears history on the server", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: { id: "r1" } } });
    const del = vi.spyOn(api, "delete").mockResolvedValue({});
    await searchService.rememberQuery("احمد");
    await searchService.rememberEntity("user", "u1");
    await searchService.forget("r1");
    await searchService.clearRecent();
    expect(post).toHaveBeenNthCalledWith(1, "/search/recent/", { query: "احمد" });
    expect(post).toHaveBeenNthCalledWith(2, "/search/recent/", { doc_type: "user", doc_id: "u1" });
    expect(del).toHaveBeenNthCalledWith(1, "/search/recent/r1/");
    expect(del).toHaveBeenNthCalledWith(2, "/search/recent/");
  });
});
