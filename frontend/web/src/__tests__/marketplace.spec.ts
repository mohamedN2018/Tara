import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  activeCount,
  emptyFilters,
  fromRouteQuery,
  toApiQuery,
  toggleAvailability,
  toRouteQuery,
} from "@/components/marketplace/filters";
import { formatMoney, priceView, pricingError } from "@/components/marketplace/money";
import { _reloadCompare, MAX_COMPARE, useCompare } from "@/components/marketplace/useCompare";
import ar from "@/i18n/ar";
import en from "@/i18n/en";
import { api } from "@/lib/api";
import { marketplaceService } from "@/services/marketplace";

describe("money", () => {
  it("keeps three-decimal currencies at three decimals", () => {
    expect(formatMoney("12.1250", "KWD", "en")).toContain("12.125");
    expect(formatMoney("12.1250", "KWD", "en")).not.toContain("12.13");
  });

  it("drops decimals on whole amounts and keeps two otherwise", () => {
    expect(formatMoney("1500.0000", "EGP", "en")).toMatch(/1,500(?!\.)/);
    expect(formatMoney("9.5", "USD", "en")).toContain("9.50");
  });

  it("falls back to number plus code for garbage input", () => {
    expect(formatMoney("abc", "USD")).toBe("abc USD");
  });

  it("maps the three price states", () => {
    const base = { currency: "EGP", sale_price: null };
    expect(priceView({ ...base, price: "0", price_type: "free" }).kind).toBe("free");
    expect(priceView({ ...base, price: null, price_type: "negotiable" }).kind).toBe("offer");
    const sale = priceView({ price: "100", sale_price: "80", price_type: "fixed", currency: "USD" }, "en");
    expect(sale).toMatchObject({ kind: "price", negotiable: false });
    if (sale.kind === "price") {
      expect(sale.amount).toContain("80");
      expect(sale.was).toContain("100");
    }
    const nego = priceView({ ...base, price: "50", price_type: "negotiable" });
    expect(nego).toMatchObject({ kind: "price", negotiable: true, was: null });
  });

  it("mirrors the server pricing rules", () => {
    const ok = { price_type: "fixed" as const, price: "100", sale_price: "", currency: "EGP" };
    expect(pricingError(ok)).toBeNull();
    expect(pricingError({ ...ok, price: "" })).toBe("price_required");
    expect(pricingError({ ...ok, sale_price: "100" })).toBe("sale_not_below_price");
    expect(pricingError({ ...ok, price: "1.234" })).toBe("too_many_decimals");
    expect(pricingError({ ...ok, price: "1.234", currency: "KWD" })).toBeNull();
    expect(pricingError({ ...ok, currency: "XYZ" })).toBe("currency");
    expect(pricingError({ ...ok, price_type: "negotiable", price: "" })).toBeNull();
    expect(pricingError({ ...ok, price_type: "negotiable", price: "", sale_price: "5" })).toBe(
      "sale_without_price",
    );
    expect(pricingError({ ...ok, price_type: "free", sale_price: "5" })).toBe("sale_price_not_allowed");
  });
});

describe("browse filters", () => {
  it("round-trips through the route query, dropping defaults and junk", () => {
    const f = fromRouteQuery({
      q: "bike",
      condition: "new,broken,good",
      availability: "sold",
      min_price: "10",
      max_price: "abc",
      currency: "egp",
      sort: "price_desc",
    });
    expect(f.condition).toEqual(["new", "good"]);
    expect(f.max_price).toBe("");
    expect(f.currency).toBe("EGP");
    expect(toRouteQuery(f)).toEqual({
      q: "bike",
      condition: "new,good",
      availability: "sold",
      min_price: "10",
      currency: "EGP",
      sort: "price_desc",
    });
    expect(toRouteQuery(emptyFilters())).toEqual({});
    expect(fromRouteQuery({ sort: "random" }).sort).toBe("newest");
  });

  it("adds the cursor to the API query only when paging", () => {
    expect(toApiQuery(emptyFilters())).toEqual({});
    expect(toApiQuery(emptyFilters(), "abc")).toEqual({ cursor: "abc" });
  });

  it("toggles availability starting from the default", () => {
    expect(toggleAvailability([], "sold")).toEqual(["available", "sold"]);
    expect(toggleAvailability(["available", "sold"], "sold")).toEqual([]);
    expect(toggleAvailability(["available", "sold"], "available")).toEqual(["sold"]);
  });

  it("counts active filters for the badge", () => {
    const f = { ...emptyFilters(), q: "x", category: "phones", condition: ["new", "good"], min_price: "1", max_price: "9" };
    expect(activeCount(f)).toBe(4);
  });
});

describe("compare selection", () => {
  beforeEach(() => {
    window.localStorage.clear();
    _reloadCompare();
  });

  it("holds at most four and persists", () => {
    const c = useCompare();
    for (let i = 0; i < MAX_COMPARE; i++) expect(c.toggle(`id${i}`)).toBe(true);
    expect(c.toggle("one-too-many")).toBe(false);
    expect(c.isFull.value).toBe(true);
    expect(JSON.parse(window.localStorage.getItem("tara.market.compare")!)).toHaveLength(4);
    c.toggle("id0");
    expect(c.has("id0")).toBe(false);
    _reloadCompare();
    expect(useCompare().selected.value).toEqual(["id1", "id2", "id3"]);
  });

  it("survives corrupt storage", () => {
    window.localStorage.setItem("tara.market.compare", "{not json");
    _reloadCompare();
    expect(useCompare().selected.value).toEqual([]);
  });
});

describe("marketplace service", () => {
  it("asks for the listing's marketplace thread and sends the message there", async () => {
    const post = vi.spyOn(api, "post").mockImplementation(async (url: string) => {
      if (url.endsWith("/contact/")) return { data: { data: {} } };
      return { data: { data: { id: "m1" } } };
    });
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: { data: [{ id: "t1" }] } });
    const id = await marketplaceService.messageSeller({ id: "L1", seller_id: "s1" }, "Hi ", "https://x/l");
    expect(id).toBe("t1");
    expect(get).toHaveBeenCalledWith("/conversations/", {
      params: { type: "marketplace", listing_id: "L1", with: "s1" },
    });
    expect(post.mock.calls.map((c) => c[0])).toEqual(["/marketplace/listings/L1/contact/", "/conversations/t1/messages/"]);
    expect((post.mock.calls[1][1] as { body: string }).body).toBe("Hi\nhttps://x/l");
  });

  it("falls back to the DM when chat has not opened the thread", async () => {
    const post = vi.spyOn(api, "post").mockImplementation(async (url: string) => {
      if (url.endsWith("/contact/")) return { data: { data: {} } };
      if (url === "/conversations/") return { data: { data: { id: "c1" } } };
      return { data: { data: { id: "m1" } } };
    });
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: [] } });
    const id = await marketplaceService.messageSeller({ id: "L1", seller_id: "s1" }, "Hi", "", 0);
    expect(id).toBe("c1");
    expect(post.mock.calls[1]).toEqual(["/conversations/", { type: "dm", other_id: "s1" }]);
  });

  it("opens no conversation when the listing refuses the contact", async () => {
    const post = vi.spyOn(api, "post").mockRejectedValue(new Error("404"));
    await expect(marketplaceService.messageSeller({ id: "L1", seller_id: "s1" }, "Hi", "")).rejects.toThrow();
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("sends facets the filters but not paging or sort", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: { data: { total: 0 } } });
    await marketplaceService.facets({ q: "a", cursor: "c", limit: 5, sort: "price_asc" });
    expect(get).toHaveBeenCalledWith("/marketplace/listings/facets/", { params: { q: "a" } });
  });

  it("caps compare at four ids and skips the call when empty", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: { data: [] } });
    expect(await marketplaceService.compare([])).toEqual([]);
    expect(get).not.toHaveBeenCalled();
    await marketplaceService.compare(["a", "b", "c", "d", "e"]);
    expect(get).toHaveBeenCalledWith("/marketplace/compare/", { params: { ids: "a,b,c,d" } });
  });
});

describe("marketplace translations", () => {
  it("has every price type, availability, sort and hint in both languages", () => {
    for (const dict of [en, ar]) {
      const m = dict.market as unknown as Record<string, Record<string, unknown>>;
      expect(Object.keys(m.priceTypes)).toEqual(["fixed", "negotiable", "free"]);
      expect(Object.keys(m.availability)).toEqual(["available", "reserved", "sold"]);
      expect(Object.keys(m.sort)).toEqual(expect.arrayContaining(["newest", "price_asc", "price_desc"]));
      expect(Object.keys((m.seller as Record<string, object>).hints)).toHaveLength(4);
    }
  });
});
