// Tara Intelligence R4 (owner decisions 8 and 24): with personalization off the tab
// collects nothing. The switch comes from the viewer's preference (read at sign-in and
// in My Algorithm) and from a Home first page's `meta.personalization_off`; turning it
// on drops the queued batch.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { syncPersonalization } from "@/lib/personalization";
import { flush, pendingSignals, personalizationOff, resetSignals, setPersonalizationOff, signalSessionId, track } from "@/lib/signals";
import { tokenStore } from "@/lib/tokens";
import { feedService } from "@/services/feed";

const ID = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

function jwt(expSeconds: number): string {
  const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${b64({ alg: "none" })}.${b64({ sub: ID(999), exp: expSeconds })}.sig`;
}

let sent: unknown[];

beforeEach(() => {
  resetSignals();
  sent = [];
  tokenStore.set(jwt(Math.floor(Date.now() / 1000) + 3600), "refresh");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      sent.push({ url, body: init.body });
      return { ok: true, status: 202 } as Response;
    }),
  );
});

afterEach(() => {
  resetSignals();
  tokenStore.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("personalization off on the client (R4)", () => {
  it("follows the viewer's preference and drops what was queued", async () => {
    expect(track({ t: "post_open", item: `post:${ID(1)}`, surface: "home" })).toBe(true);
    expect(pendingSignals()).toHaveLength(1);
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: { default_mode: null, version: 3, personalization_off: true } } });
    expect(await syncPersonalization()).toBe(true);
    expect(personalizationOff()).toBe(true);
    expect(pendingSignals()).toHaveLength(0);
    for (const t of ["feed_impression", "feed_dwell", "post_open", "video_start", "reel_view", "profile_visit"] as const) {
      expect(track({ t, item: `post:${ID(2)}`, surface: "home", dwell_ms: 1200 })).toBe(false);
    }
    expect(signalSessionId()).toBeUndefined();
    await flush();
    expect(sent).toHaveLength(0);
  });

  it("turns collection back on when the preference says so, and keeps state on a failed read", async () => {
    setPersonalizationOff(true);
    vi.spyOn(api, "get").mockResolvedValueOnce({ data: { data: { default_mode: null, version: 3, personalization_off: false } } });
    expect(await syncPersonalization()).toBe(false);
    expect(personalizationOff()).toBe(false);
    setPersonalizationOff(true);
    vi.spyOn(api, "get").mockRejectedValueOnce(new Error("down"));
    expect(await syncPersonalization()).toBeNull();
    expect(personalizationOff()).toBe(true);
  });

  it("an older server that sends no flag changes nothing", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: { default_mode: "recent", version: 1 } } });
    expect(await syncPersonalization()).toBeNull();
    expect(personalizationOff()).toBe(false);
  });

  it("reads meta.personalization_off and the item topics from a Home first page", async () => {
    vi.spyOn(api, "post").mockResolvedValue({ data: { data: [] } }); // the live batch
    vi.spyOn(api, "get").mockResolvedValue({
      data: {
        data: [
          {
            id: "f1",
            post_id: ID(5),
            author_id: ID(6),
            reason: "friend",
            snapshot: { excerpt: "hi" },
            post_created_at: "2026-11-06T00:00:00Z",
            topics: [
              { slug: "cooking", label_ar: "طبخ", label_en: "Cooking" },
              { slug: 7, label_ar: "x" },
            ],
          },
        ],
        sponsored: null,
        page: { next_cursor: null, has_more: false },
        mode: "recent",
        meta: { personalization_off: true },
      },
    });
    const page = await feedService.page(undefined, "recent", undefined, { snapshots: true });
    expect(page.personalizationOff).toBe(true);
    expect(page.topics).toEqual({ [ID(5)]: [{ slug: "cooking", label_ar: "طبخ", label_en: "Cooking" }] });
  });
});
