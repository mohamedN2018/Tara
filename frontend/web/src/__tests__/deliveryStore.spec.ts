// WP 4c.2-B3 on the web (08 §7.2): the delivery store. The web's only delivery
// values are the SAFE_DEFAULTS fallback, and it must equal the backend's package
// defaults, read here from the repo so the two cannot drift.
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import {
  applyDelivery,
  delivery,
  DELIVERY_SURFACES,
  deliverySource,
  holdRails,
  loadDelivery,
  parseBlock,
  positionRules,
  railsHeld,
  railsReady,
  releaseRails,
  resetDelivery,
  SAFE_DEFAULTS,
} from "@/lib/delivery";

const here = dirname(fileURLToPath(import.meta.url));
const defaultsDir = resolve(here, "../../../../services/feed/intel/config/defaults");
const backend = (surface: string) => JSON.parse(readFileSync(resolve(defaultsDir, `${surface}.json`), "utf8")).delivery;

beforeEach(() => {
  sessionStorage.clear();
  resetDelivery();
});
afterEach(() => resetDelivery());

describe("SAFE_DEFAULTS", () => {
  for (const surface of DELIVERY_SURFACES) {
    it(`equals the backend package defaults for ${surface}`, () => {
      const server = backend(surface);
      expect(server, `services/feed/intel/config/defaults/${surface}.json has a delivery block`).toBeTruthy();
      // Every key the web reads, with the backend's value (server-only keys may exist there).
      const picked = Object.fromEntries(Object.keys(SAFE_DEFAULTS[surface]).map((k) => [k, server[k]]));
      expect(picked).toEqual(SAFE_DEFAULTS[surface]);
      expect(parseBlock(server)).not.toBeNull();
    });
  }

  it("is what a surface uses before the server answers, and says so", () => {
    expect(deliverySource("home")).toBe("safe");
    expect(delivery("home")).toEqual(SAFE_DEFAULTS.home);
  });
});

describe("server values", () => {
  it("win over the fallback once applied, and survive in sessionStorage", () => {
    expect(applyDelivery("home", { ...SAFE_DEFAULTS.home, first_page_size: 7 })).toBe(true);
    expect(delivery("home").first_page_size).toBe(7);
    expect(deliverySource("home")).toBe("server");
    expect(JSON.parse(sessionStorage.getItem("tara.delivery.v1")!).home.first_page_size).toBe(7);
  });

  it("reject a junk or partial block (the fallback stays)", () => {
    expect(applyDelivery("home", { first_page_size: 10 })).toBe(false);
    expect(applyDelivery("home", { ...SAFE_DEFAULTS.home, video: { ...SAFE_DEFAULTS.home.video, autoplay: "always" } })).toBe(false);
    expect(applyDelivery("home", { ...SAFE_DEFAULTS.home, impression: { ...SAFE_DEFAULTS.home.impression, def_version: 0 } })).toBe(false);
    expect(applyDelivery("home", { ...SAFE_DEFAULTS.home, page_size: -1 })).toBe(false);
    expect(deliverySource("home")).toBe("safe");
  });

  it("GET /feed/delivery/ once per session, in the background; a failure keeps the fallback", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValueOnce({
      data: { data: { home: { ...SAFE_DEFAULTS.home, page_size: 30 }, reels: SAFE_DEFAULTS.reels, video: { ...SAFE_DEFAULTS.video, first_page_size: 12 } } },
    } as never);
    await Promise.all([loadDelivery(), loadDelivery()]);
    await loadDelivery();
    expect(get).toHaveBeenCalledTimes(1);
    expect(get).toHaveBeenCalledWith("/feed/delivery/");
    expect(delivery("home").page_size).toBe(30);
    expect(delivery("video").first_page_size).toBe(12);

    resetDelivery();
    get.mockRejectedValueOnce(new Error("503"));
    await loadDelivery();
    expect(deliverySource("reels")).toBe("safe");
  });

  it("reads a stored block when sessionStorage is blocked: no throw, fallback used", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => applyDelivery("reels", SAFE_DEFAULTS.reels)).not.toThrow();
    expect(delivery("video")).toEqual(SAFE_DEFAULTS.video);
  });
});

describe("reload position rules", () => {
  it("come from the server's block (reload_window_min, reload_max_pages), the fallback's until then", () => {
    expect(positionRules()).toEqual({ windowMs: 30 * 60_000, maxPages: 3 });
    applyDelivery("home", { ...SAFE_DEFAULTS.home, reload_window_min: 10, reload_max_pages: 5 });
    expect(positionRules()).toEqual({ windowMs: 10 * 60_000, maxPages: 5 });
  });

  it("an older server's block without the keys keeps the fallback's", () => {
    const older: Record<string, unknown> = { ...SAFE_DEFAULTS.home };
    delete older.reload_window_min;
    delete older.reload_max_pages;
    expect(applyDelivery("home", older)).toBe(true);
    expect(positionRules()).toEqual({ windowMs: 30 * 60_000, maxPages: 3 });
  });
});

describe("rail gate", () => {
  it("is open by default (rails start at once off Home)", async () => {
    expect(railsHeld()).toBe(false);
    await expect(railsReady()).resolves.toBeUndefined();
  });

  it("holds until released, or until the maximum wait", async () => {
    vi.useFakeTimers();
    try {
      holdRails(1500);
      let done = 0;
      void railsReady().then(() => done++);
      void railsReady().then(() => done++);
      await vi.advanceTimersByTimeAsync(1000);
      expect(done).toBe(0);
      releaseRails();
      await vi.advanceTimersByTimeAsync(0);
      expect(done).toBe(2);
      expect(railsHeld()).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });
});
