import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ctaKey, ctaLabel } from "@/lib/adCta";
import { api } from "@/lib/api";
import { createBatchLoader, retryAfterMs, retryable } from "@/lib/batchLoader";
import { i18n } from "@/i18n";
import { clearMediaCache, mediaService } from "@/services/media";
import { videoService } from "@/services/video";

// One home load used to ask media for every image on its own (about 200
// calls), ran into the rate limit and left tiles blank. Lookups made in the same
// tick now go out as one batch, with 429s retried.

const rateLimited = (retryAfter?: string) =>
  Object.assign(new Error("429"), { response: { status: 429, headers: retryAfter ? { "retry-after": retryAfter } : {} } });

type Item = { id: string };

describe("createBatchLoader", () => {
  it("sends the lookups of one tick as one request and shares duplicates", async () => {
    const fetch = vi.fn(async (ids: string[]) => ids.filter((id) => id !== "hidden").map((id) => ({ id })));
    const loader = createBatchLoader<Item>({ fetch, idOf: (i) => i.id, windowMs: 0 });

    const answers = await Promise.all(["a", "b", "a", "hidden"].map((id) => loader.load(id)));

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith(["a", "b", "hidden"]);
    expect(answers).toEqual([{ id: "a" }, { id: "b" }, { id: "a" }, null]);
  });

  it("splits more than `max` ids into several requests", async () => {
    const fetch = vi.fn(async (ids: string[]) => ids.map((id) => ({ id })));
    const loader = createBatchLoader<Item>({ fetch, idOf: (i) => i.id, windowMs: 0, max: 100 });
    const ids = Array.from({ length: 250 }, (_, i) => `m${i}`);

    const answers = await Promise.all(ids.map((id) => loader.load(id)));

    expect(fetch.mock.calls.map(([batch]) => batch.length)).toEqual([100, 100, 50]);
    expect(answers.every((a, i) => a?.id === ids[i])).toBe(true);
  });

  it("retries a 429 with backoff, honouring Retry-After", async () => {
    const sleep = vi.fn(async (_ms: number) => {});
    let calls = 0;
    const fetch = vi.fn(async (ids: string[]) => {
      calls += 1;
      if (calls === 1) throw rateLimited("2");
      if (calls === 2) throw rateLimited();
      return ids.map((id) => ({ id }));
    });
    const loader = createBatchLoader<Item>({ fetch, idOf: (i) => i.id, windowMs: 0, backoffMs: 100, sleep });

    expect(await loader.load("a")).toEqual({ id: "a" });
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(sleep.mock.calls.map(([ms]) => ms)).toEqual([2000, 200]);
  });

  it("gives up after its retries, rejects every waiter and warns once", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const fetch = vi.fn(async () => {
      throw rateLimited();
    });
    const loader = createBatchLoader<Item>({ fetch, idOf: (i) => i.id, windowMs: 0, retries: 2, sleep: async () => {} });

    await expect(Promise.all([loader.load("a"), loader.load("b")])).rejects.toThrow("429");
    await expect(loader.load("c")).rejects.toThrow("429");

    expect(fetch).toHaveBeenCalledTimes(6); // two batches, three tries each
    expect(warn).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });

  it("does not retry an answer that will not change", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const fetch = vi.fn(async () => {
      throw Object.assign(new Error("400"), { response: { status: 400 } });
    });
    const loader = createBatchLoader<Item>({ fetch, idOf: (i) => i.id, windowMs: 0, sleep: async () => {} });
    await expect(loader.load("a")).rejects.toThrow("400");
    expect(fetch).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });

  it("asks again once an earlier answer has come back", async () => {
    const fetch = vi.fn(async (ids: string[]) => ids.map((id) => ({ id })));
    const loader = createBatchLoader<Item>({ fetch, idOf: (i) => i.id, windowMs: 0 });
    await loader.load("a");
    await loader.load("a");
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("classifies errors and reads Retry-After", () => {
    expect(retryable(rateLimited())).toBe(true);
    expect(retryable(new Error("network"))).toBe(true);
    expect(retryable({ response: { status: 503 } })).toBe(true);
    expect(retryable({ response: { status: 404 } })).toBe(false);
    expect(retryAfterMs(rateLimited("3"))).toBe(3000);
    expect(retryAfterMs(rateLimited("600"))).toBe(10_000);
    expect(retryAfterMs(rateLimited())).toBeNull();
    expect(retryAfterMs(rateLimited("soon"))).toBeNull();
  });
});

describe("mediaService.resolveUrl", () => {
  beforeEach(() => clearMediaCache());
  afterEach(() => vi.restoreAllMocks());

  it("resolves a page of ids in one POST /media/resolve/ and caches the answers", async () => {
    const post = vi.spyOn(api, "post").mockImplementation(async (_url: string, body?: unknown) => {
      const ids = (body as { ids: string[] }).ids;
      return { data: { data: ids.filter((id) => id !== "gone").map((id) => ({ id, kind: "image", status: "ready", url: `/s/${id}` })) } };
    });
    const get = vi.spyOn(api, "get");

    const urls = await Promise.all(["a", "b", "gone", "a"].map((id) => mediaService.resolveUrl(id)));

    expect(urls).toEqual(["/s/a", "/s/b", null, "/s/a"]);
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith("/media/resolve/", { ids: ["a", "b", "gone"] });
    expect(get).not.toHaveBeenCalled();
    expect(mediaService.cachedUrl("a")).toBe("/s/a");

    // Cached URLs and recent misses are not asked again.
    expect(await Promise.all([mediaService.resolveUrl("a"), mediaService.resolveUrl("gone")])).toEqual(["/s/a", null]);
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("asks again for an asset that was still processing", async () => {
    const post = vi
      .spyOn(api, "post")
      .mockResolvedValueOnce({ data: { data: [{ id: "p", kind: "image", status: "processing", url: null }] } })
      .mockResolvedValueOnce({ data: { data: [{ id: "p", kind: "image", status: "ready", url: "/s/p" }] } });
    expect(await mediaService.resolveUrl("p")).toBeNull();
    expect(await mediaService.resolveUrl("p")).toBe("/s/p");
    expect(post).toHaveBeenCalledTimes(2);
  });
});

describe("videoService.playback", () => {
  afterEach(() => vi.restoreAllMocks());

  it("batches the playbacks of a page and answers 404 for an absent video", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({
      data: {
        data: [{ id: "v1", status: "ready", failure_code: null, duration_ms: 1000, width: 640, height: 360, hls_url: "media/v1/hls/master.m3u8?token=t", mp4_url: null, poster_url: null, expires_in: 300 }],
      },
    });

    const [ok, missing] = await Promise.allSettled([videoService.playback("v1"), videoService.playback("v2")]);

    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith("/media/playback/resolve/", { ids: ["v1", "v2"] });
    expect(ok.status === "fulfilled" && ok.value.hls_url).toMatch(/\/media\/v1\/hls\/master\.m3u8\?token=t$/);
    expect(missing.status).toBe("rejected");
    expect((missing as PromiseRejectedResult).reason.response.status).toBe(404);
  });
});

describe("ad call-to-action", () => {
  const t = (key: string) => i18n.global.t(key);
  afterEach(() => {
    i18n.global.locale.value = "en";
  });

  it("maps the stored defaults in either language to one key", () => {
    expect(ctaKey("Learn more")).toBe("learn_more");
    expect(ctaKey("  LEARN   MORE ")).toBe("learn_more");
    expect(ctaKey("اعرف المزيد")).toBe("learn_more");
    expect(ctaKey("shop_now")).toBe("shop_now");
    expect(ctaKey("Visit our bakery")).toBeNull();
    expect(ctaKey(null)).toBeNull();
  });

  it("shows a known call-to-action in the reader's language and own words as written", () => {
    i18n.global.locale.value = "ar";
    expect(ctaLabel("Learn more", t)).toBe("اعرف المزيد");
    expect(ctaLabel("Shop now", t)).toBe("تسوّق الآن");
    i18n.global.locale.value = "en";
    expect(ctaLabel("اعرف المزيد", t)).toBe("Learn more");
    expect(ctaLabel("زوروا مخبزنا", t)).toBe("زوروا مخبزنا");
  });
});
