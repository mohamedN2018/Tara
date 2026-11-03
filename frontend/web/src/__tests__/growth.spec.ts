import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { subscriptionJson, vapidKeyBytes } from "@/lib/pwa";
import { adminService } from "@/services/admin";
import { adErrorKey, CAMPAIGN_CURRENCIES } from "@/services/ads";
import { mediaErrorKey } from "@/lib/errors";
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

const failure = (status: number, code: string, details?: { field: string | null; code: string }[]) => ({
  response: { status, data: { error: { code, message: "raw", details: details?.map((d) => ({ ...d, message: "m" })) } } },
});

describe("ads errors", () => {
  it("names the field or the media problem", () => {
    expect(adErrorKey(failure(400, "validation_error", [{ field: "media_id", code: "media_not_ready" }]))).toBe("errors.mediaNotReady");
    expect(adErrorKey(failure(400, "validation_error", [{ field: "media_id", code: "media_not_owned" }]))).toBe("errors.mediaNotOwned");
    // Profile sends the same problem as the error code itself.
    expect(mediaErrorKey(failure(400, "media_kind_not_allowed"))).toBe("errors.mediaKind");
    expect(mediaErrorKey(failure(400, "validation_error"))).toBeNull();
    expect(adErrorKey(failure(400, "validation_error", [{ field: "schedule_end", code: "invalid" }]))).toBe("ads.errors.scheduleEnd");
    expect(adErrorKey(failure(400, "validation_error", [{ field: "currency", code: "invalid" }]))).toBe("ads.errors.currency");
    expect(adErrorKey(failure(503, "dependency_unavailable"))).toBe("ads.errors.unavailable");
    expect(adErrorKey(failure(403, "permission_denied"))).toBe("errors.permission_denied");
  });

  it("offers exactly the currencies the server accepts", () => {
    expect(CAMPAIGN_CURRENCIES).toEqual(["AED", "BHD", "EGP", "EUR", "GBP", "JOD", "KWD", "OMR", "QAR", "SAR", "USD"]);
  });
});

describe("moderation appeals", () => {
  afterEach(() => vi.restoreAllMocks());

  it("lists open appeals and follows the cursor", async () => {
    const row = { id: "ap1", case_id: "c1", target_type: "post", target_id: "t1", account_id: "a1", text: "x", status: "open", created_at: "2026-11-03T00:00:00Z" };
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: { data: [row], page: { next_cursor: "n2", prev_cursor: null, has_more: true } } });
    const page = await adminService.appeals("open", "n1");
    expect(get).toHaveBeenCalledWith("/moderation/appeals/", { params: { status: "open", cursor: "n1" } });
    expect(page.data).toEqual([row]);
    expect(page.page.next_cursor).toBe("n2");
  });

  it("tolerates an empty answer", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ data: {} });
    expect(await adminService.appeals()).toEqual({ data: [], page: { next_cursor: null, prev_cursor: null, has_more: false } });
  });

  it("resolves with the decision", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: {} } });
    await adminService.resolveAppeal("ap1", "overturned");
    expect(post).toHaveBeenCalledWith("/moderation/appeals/ap1/resolve/", { status: "overturned" });
  });
});
