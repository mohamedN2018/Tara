import { describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { subscriptionJson, vapidKeyBytes } from "@/lib/pwa";
import { feedService } from "@/services/feed";

describe("vapidKeyBytes", () => {
  it("decodes url-safe base64 without padding", () => {
    expect([...vapidKeyBytes("AQID_-8")]).toEqual([1, 2, 3, 255, 239]);
  });
});

describe("subscriptionJson", () => {
  it("keeps only the endpoint and keys", () => {
    const sub = {
      toJSON: () => ({ endpoint: "https://fcm.googleapis.com/x", keys: { p256dh: "p", auth: "a" }, expirationTime: null }),
    } as unknown as PushSubscription;
    expect(subscriptionJson(sub)).toEqual({ endpoint: "https://fcm.googleapis.com/x", keys: { p256dh: "p", auth: "a" } });
  });
});

describe("feed sponsored slot", () => {
  it("turns the single slot the API sends into a list, with its serve token", async () => {
    const slot = { creative_id: "c1", headline: "Ad", token: "t", sponsored: true };
    const get = vi.spyOn(api, "get").mockResolvedValueOnce({
      data: { data: [], sponsored: slot, page: { next_cursor: null, has_more: false } },
    });
    const page = await feedService.page();
    expect(page.sponsored).toEqual([slot]);
    get.mockRestore();
  });

  it("is empty when there is no ad", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValueOnce({
      data: { data: [], sponsored: null, page: { next_cursor: null, has_more: false } },
    });
    expect((await feedService.page()).sponsored).toEqual([]);
    get.mockRestore();
  });
});
