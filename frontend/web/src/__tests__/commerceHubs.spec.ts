// Track T6: marketplace hubs (photos, editing, owner menu, inbox, tabs) and the
// ads manager (schedule helpers, rejection notes, review queue paging).
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, type Component, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import CreateListingModal from "@/components/marketplace/CreateListingModal.vue";
import { tabFromQuery } from "@/components/marketplace/hubs";
import { categoryLabel } from "@/components/marketplace/useCategories";
import ListingOwnerMenu from "@/components/marketplace/ListingOwnerMenu.vue";
import ListingPhotos from "@/components/marketplace/ListingPhotos.vue";
import MarketplaceInbox from "@/components/marketplace/MarketplaceInbox.vue";
import { i18n } from "@/i18n";
import ar from "@/i18n/ar";
import en from "@/i18n/en";
import { scheduleLabel, toIso } from "@/lib/adSchedule";
import { api } from "@/lib/api";
import { adsService } from "@/services/ads";
import { chatService } from "@/services/chat";
import { marketplaceService } from "@/services/marketplace";
import { mediaService } from "@/services/media";
import { moderationService } from "@/services/moderation";
import { useAuthStore } from "@/stores/auth";
import AdReviewView from "@/views/AdReviewView.vue";
import ListingDetailView from "@/views/ListingDetailView.vue";

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;

async function flush() {
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
}

async function mount(component: Component, props: Record<string, unknown> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/home", component: Blank },
      { path: "/messages/:id?", name: "messages", component: Blank },
      { path: "/u/id/:id", name: "profile-by-id", component: Blank },
      { path: "/marketplace/sellers/:id", name: "marketplace-seller", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push("/home");
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({ render: () => h(component, props) });
  app.use(pinia).use(router).use(i18n);
  app.mount(host);
  await flush();
  return router;
}

let pinia = createPinia();
const $ = (sel: string) => document.body.querySelector<HTMLElement>(sel);
const $$ = (sel: string) => Array.from(document.body.querySelectorAll<HTMLElement>(sel));
const buttonNamed = (text: string) =>
  $$("button").find((b) => b.textContent?.trim() === text) as HTMLButtonElement | undefined;

async function click(el: HTMLElement | null | undefined) {
  expect(el).toBeTruthy();
  el!.click();
  await flush();
}

const listing = (extra: Record<string, unknown> = {}) => ({
  id: "l1",
  seller_id: "me-1",
  title: "Bike",
  description: "Red",
  price: "100",
  price_type: "fixed",
  sale_price: null,
  currency: "EGP",
  condition: "good",
  location: "Cairo",
  status: "active",
  availability: "available",
  save_count: 0,
  created_at: "2026-11-04T10:00:00Z",
  category: { id: "c1", slug: "vehicles", name: "Vehicles", parent_id: null },
  media: [{ media_id: "m1", position: 0 }],
  viewer: { is_owner: true, is_saved: false, has_inquired: false, can_review: false, has_reviewed: false },
  ...extra,
});

beforeEach(() => {
  pinia = createPinia();
  setActivePinia(pinia);
  localStorage.clear();
  i18n.global.locale.value = "en";
  useAuthStore().account = { id: "me-1", email: "me@example.com" } as never;
  vi.spyOn(mediaService, "resolveUrl").mockResolvedValue("blob:x");
  globalThis.URL.createObjectURL = vi.fn(() => "blob:new");
  globalThis.URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.restoreAllMocks();
});

describe("marketplace tabs", () => {
  it("maps the old tabs to their new hubs and rejects junk", () => {
    expect(tabFromQuery("mine")).toBe("selling");
    expect(tabFromQuery("saved")).toBe("buying");
    expect(tabFromQuery("inbox")).toBe("inbox");
    expect(tabFromQuery("<x>")).toBe("browse");
    expect(tabFromQuery(undefined)).toBe("browse");
  });

  it("has every commerce string in both languages", () => {
    const keys = (o: object, p = ""): string[] =>
      Object.entries(o).flatMap(([k, v]) => (typeof v === "object" ? keys(v, `${p}${k}.`) : [`${p}${k}`]));
    const enKeys = keys((en as Record<string, object>).commerce);
    expect(enKeys.length).toBeGreaterThan(50);
    expect(keys((ar as Record<string, object>).commerce)).toEqual(enKeys);
  });
});

describe("ListingPhotos", () => {
  it("uploads each picked photo and emits the ids in order", async () => {
    const upload = vi
      .spyOn(mediaService, "upload")
      .mockResolvedValueOnce({ id: "a", kind: "image", status: "processing", url: null })
      .mockResolvedValueOnce({ id: "b", kind: "image", status: "processing", url: null });
    const updates: string[][] = [];
    let ids: string[] = [];
    await mount(
      defineComponent({
        render: () =>
          h(ListingPhotos, {
            modelValue: ids,
            "onUpdate:modelValue": (v: string[]) => {
              ids = v;
              updates.push(v);
            },
          }),
      }),
    );
    const input = $("[data-testid=listing-photo-input]") as HTMLInputElement;
    const files = [new File(["1"], "a.jpg", { type: "image/jpeg" }), new File(["2"], "b.png", { type: "image/png" })];
    Object.defineProperty(input, "files", { value: files, configurable: true });
    input.dispatchEvent(new Event("change"));
    await flush();
    expect(upload).toHaveBeenCalledTimes(2);
    expect(upload.mock.calls[0][1]).toBe("image");
    expect(updates.at(-1)).toEqual(["a", "b"]);
  });

  it("removes and reorders photos", async () => {
    const updates: string[][] = [];
    await mount(ListingPhotos, { modelValue: ["a", "b", "c"], "onUpdate:modelValue": (v: string[]) => updates.push(v) });
    expect($$("[data-testid=listing-photo]")).toHaveLength(3);
    await click($('[aria-label="Remove photo 2"]'));
    expect(updates.at(-1)).toEqual(["a", "c"]);
    await click($('[aria-label="Move photo 1 later"]'));
    expect(updates.at(-1)).toEqual(["c", "a"]);
  });

  it("refuses non-images without uploading", async () => {
    const upload = vi.spyOn(mediaService, "upload");
    await mount(ListingPhotos, { modelValue: [] });
    const input = $("[data-testid=listing-photo-input]") as HTMLInputElement;
    Object.defineProperty(input, "files", { value: [new File(["x"], "a.pdf", { type: "application/pdf" })] });
    input.dispatchEvent(new Event("change"));
    await flush();
    expect(upload).not.toHaveBeenCalled();
    expect($("[role=alert]")?.textContent).toContain("Only photos");
  });
});

describe("CreateListingModal", () => {
  it("edits a listing: no category change, photos kept in order", async () => {
    const update = vi.spyOn(marketplaceService, "update").mockResolvedValue(listing({ title: "Bike 2" }) as never);
    const publish = vi.spyOn(marketplaceService, "publish");
    const saved: unknown[] = [];
    await mount(CreateListingModal, { categories: [], listing: listing(), onSaved: (l: unknown) => saved.push(l) });
    expect($("#listing-dialog-title")?.textContent).toContain("Edit listing");
    expect(($("#listing-category") as HTMLSelectElement).disabled).toBe(true);
    const title = $("#listing-title") as HTMLInputElement;
    expect(title.value).toBe("Bike");
    title.value = "Bike 2";
    title.dispatchEvent(new Event("input"));
    await flush();
    await click($("[data-testid=listing-submit]"));
    const payload = update.mock.calls[0][1] as Record<string, unknown>;
    expect(update.mock.calls[0][0]).toBe("l1");
    expect(payload).not.toHaveProperty("category_id");
    expect(payload).toMatchObject({ title: "Bike 2", media_ids: ["m1"], price: "100" });
    expect(publish).not.toHaveBeenCalled(); // an active listing is just saved
    expect(saved).toHaveLength(1);
  });

  it("resubmits a rejected listing after saving it", async () => {
    vi.spyOn(marketplaceService, "update").mockResolvedValue(listing({ status: "rejected" }) as never);
    const publish = vi.spyOn(marketplaceService, "publish").mockResolvedValue(listing({ status: "pending_review" }) as never);
    await mount(CreateListingModal, { categories: [], listing: listing({ status: "rejected" }) });
    const submit = $("[data-testid=listing-submit]");
    expect(submit?.textContent).toContain("Save and resubmit");
    await click(submit);
    expect(publish).toHaveBeenCalledWith("l1");
  });

  it("saves a new listing as a draft without publishing it", async () => {
    const create = vi.spyOn(marketplaceService, "create").mockResolvedValue(listing({ status: "draft" }) as never);
    const publish = vi.spyOn(marketplaceService, "publish");
    const created: unknown[] = [];
    await mount(CreateListingModal, {
      categories: [{ id: "c1", slug: "vehicles", name: "Vehicles", parent_id: null }],
      onCreated: (l: unknown) => created.push(l),
    });
    const title = $("#listing-title") as HTMLInputElement;
    title.value = "Lamp";
    title.dispatchEvent(new Event("input"));
    const price = $("#listing-price") as HTMLInputElement;
    price.value = "20";
    price.dispatchEvent(new Event("input"));
    await flush();
    await click($("[data-testid=listing-save-only]"));
    expect(create.mock.calls[0][0]).toMatchObject({ title: "Lamp", category_id: "c1", media_ids: [] });
    expect(publish).not.toHaveBeenCalled();
    expect(created).toHaveLength(1);
  });

  it("names a refused photo instead of a generic error", async () => {
    vi.spyOn(marketplaceService, "update").mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 400,
        data: { error: { code: "validation_error", message: "x", details: [{ field: "media_ids", code: "media_not_owned" }] } },
      },
    });
    await mount(CreateListingModal, { categories: [], listing: listing() });
    await click($("[data-testid=listing-submit]"));
    expect($("[role=alert]")?.textContent).toContain("can't be used");
  });
});

describe("category names", () => {
  it("translates the seeded slugs and keeps the server's name for others", () => {
    const { t, te } = i18n.global;
    i18n.global.locale.value = "ar";
    expect(categoryLabel({ slug: "electronics", name: "Electronics" }, t, te)).toBe("إلكترونيات");
    expect(categoryLabel({ slug: "home-garden", name: "Home & Garden" }, t, te)).toBe("المنزل والحديقة");
    expect(categoryLabel({ slug: "boats", name: "Boats" }, t, te)).toBe("Boats");
    i18n.global.locale.value = "en";
    expect(categoryLabel({ slug: "home-garden", name: "Home & Garden" }, t, te)).toBe("Home & Garden");
    expect(categoryLabel(null, t, te)).toBe("");
  });
});

describe("listing page for its seller", () => {
  function stubPage(status: string) {
    vi.spyOn(marketplaceService, "get").mockResolvedValue({ ...listing({ status, media: [] }), moderation: null } as never);
    vi.spyOn(marketplaceService, "categories").mockResolvedValue([]);
    vi.spyOn(marketplaceService, "seller").mockRejectedValue(new Error("not under test"));
    vi.spyOn(mediaService, "resolveUrl").mockResolvedValue(null);
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: [] } });
  }

  it("shows the moderator's reason and the appeal state from my Support cases", async () => {
    stubPage("removed");
    const cases = vi.spyOn(moderationService, "myCases").mockResolvedValue({
      data: [
        { id: "k0", target_type: "post", target_id: "p9", decision: "remove", reason: "other", decided_at: null, appeal_status: null, appealed_at: null, can_appeal: false },
        { id: "k1", target_type: "listing", target_id: "l1", decision: "remove", reason: "Counterfeit goods", decided_at: "2026-11-03T10:00:00Z", appeal_status: "open", appealed_at: null, can_appeal: false },
      ],
      page: { next_cursor: null, prev_cursor: null, has_more: false },
    });
    await mount(ListingDetailView);
    expect(cases).toHaveBeenCalled();
    expect($("[data-testid=moderation-reason]")?.textContent).toContain("Counterfeit goods");
    expect($("[data-testid=moderation-appeal]")?.textContent).toContain("under review");
    // A removed listing has nothing to manage: no edit, no empty "..." menu.
    expect($("[data-testid=owner-edit]")).toBeNull();
    expect($("[data-testid=listing-owner-menu]")).toBeNull();
  });

  it("keeps the main action, Edit and the menu on one row for an active listing", async () => {
    stubPage("active");
    const cases = vi.spyOn(moderationService, "myCases");
    await mount(ListingDetailView);
    expect(cases).not.toHaveBeenCalled();
    const row = $("[data-testid=owner-action-row]");
    expect(row?.className).not.toContain("flex-wrap");
    expect(row?.querySelector("[data-testid=owner-mark-sold]")).not.toBeNull();
    expect(row?.querySelector("[data-testid=owner-edit]")).not.toBeNull();
    expect(row?.querySelector("[data-testid=listing-owner-menu]")).not.toBeNull();
  });
});

describe("ListingOwnerMenu", () => {
  it("offers the actions that fit the status", async () => {
    await mount(ListingOwnerMenu, { listing: listing({ status: "draft" }) });
    await click($("[data-testid=listing-owner-menu]"));
    const items = $$("[role=menuitem]").map((b) => b.textContent?.trim());
    expect(items).toEqual(["Edit listing", "Publish", "Archive listing"]);
  });

  it("shows no menu at all for a removed listing (nothing is left to manage)", async () => {
    await mount(ListingOwnerMenu, { listing: listing({ status: "removed" }) });
    expect($("[data-testid=listing-owner-menu]")).toBeNull();
    expect($$("[role=menuitem]")).toHaveLength(0);
  });

  it("archives only after the confirmation", async () => {
    const transition = vi.spyOn(marketplaceService, "transition").mockResolvedValue(listing({ status: "archived" }) as never);
    const updated: unknown[] = [];
    await mount(ListingOwnerMenu, { listing: listing(), onUpdated: (l: unknown) => updated.push(l) });
    await click($("[data-testid=listing-owner-menu]"));
    await click(buttonNamed("Archive listing"));
    expect(transition).not.toHaveBeenCalled();
    expect($("[data-testid=confirm-action]")).toBeTruthy();
    const confirm = $$("[data-testid=confirm-action] button").find((b) => b.textContent?.includes("Archive listing"));
    await click(confirm);
    expect(transition).toHaveBeenCalledWith("l1", "archive");
    expect(updated[0]).toMatchObject({ status: "archived" });
  });
});

describe("MarketplaceInbox", () => {
  const row = (extra: Record<string, unknown> = {}) => ({
    id: "i1",
    role: "seller",
    listing_id: "l1",
    listing: {
      id: "l1",
      title: "Bike",
      status: "active",
      availability: "available",
      price_type: "fixed",
      price: "100",
      sale_price: null,
      currency: "EGP",
      category_slug: "vehicles",
      cover_media_id: null,
    },
    counterpart_id: "buyer-1",
    first_message: "Still available?",
    message_count: 1,
    created_at: "2026-11-04T10:00:00Z",
    last_activity_at: "2026-11-04T10:00:00Z",
    ...extra,
  });
  const page = (data: unknown[]) => ({ data, page: { next_cursor: null, prev_cursor: null, has_more: false } });

  it("lists each side and opens the listing's marketplace thread", async () => {
    const inquiries = vi
      .spyOn(marketplaceService, "inquiries")
      .mockResolvedValueOnce(page([row()]) as never)
      .mockResolvedValueOnce(page([row({ id: "i2", role: "buyer", listing: null })]) as never);
    const openDm = vi.spyOn(chatService, "openDm");
    const thread = vi.spyOn(chatService, "listingThread").mockResolvedValue({ id: "conv-9" } as never);
    const router = await mount(MarketplaceInbox);
    expect(inquiries).toHaveBeenCalledWith("seller");
    expect($$("[data-testid=inquiry-row]")).toHaveLength(1);
    expect(document.body.textContent).toContain("Still available?");
    await click($("[data-testid=inbox-role-buyer]"));
    expect(inquiries).toHaveBeenLastCalledWith("buyer");
    expect(document.body.textContent).toContain("no longer available");
    await click($$("[data-testid=inquiry-row] button").at(-1));
    expect(thread).toHaveBeenCalledWith(expect.any(String), "buyer-1", 3000);
    expect(openDm).not.toHaveBeenCalled();
    expect(router.currentRoute.value.fullPath).toBe("/messages/conv-9?folder=marketplace");
  });
});

describe("ads manager", () => {
  it("turns local date-times into ISO and back into one line", () => {
    expect(toIso("")).toBeNull();
    expect(toIso("nope")).toBeNull();
    expect(toIso("2026-12-01T10:00")).toMatch(/^2026-12-01T\d\d:00:00\.000Z$/);
    const t = (k: string, n?: Record<string, unknown>) => `${k}:${Object.keys(n ?? {}).join(",")}`;
    expect(scheduleLabel({ schedule_start: "2026-12-01T10:00:00Z", schedule_end: "2026-12-02T10:00:00Z" }, "en", t)).toBe(
      "commerce.ads.runs:start,end",
    );
    expect(scheduleLabel({ schedule_end: "2026-12-02T10:00:00Z" }, "en", t)).toBe("commerce.ads.ends:end");
    expect(scheduleLabel({}, "en", t)).toBe("");
  });

  it("sends a slot request only for the marketplace placement", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: { data: { sponsored: null } } });
    expect(await adsService.slot("marketplace")).toBeNull();
    expect(get).toHaveBeenCalledWith("/ads/slot/", { params: { placement: "marketplace" } });
  });

  it("needs a reason to reject and pages the queue", async () => {
    const item = (id: string) => ({
      id,
      ad_set_id: "s1",
      headline: `Ad ${id}`,
      body: "",
      cta: "Go",
      link_url: "",
      media_id: null,
      review_status: "pending",
      campaign_name: "C",
      advertiser_name: "A",
      placement: "feed",
    });
    const queue = vi
      .spyOn(adsService, "reviewQueue")
      .mockResolvedValueOnce({ data: [item("1")], page: { next_cursor: "n1", prev_cursor: null, has_more: true } } as never)
      .mockResolvedValueOnce({ data: [item("2")], page: { next_cursor: null, prev_cursor: null, has_more: false } } as never);
    const review = vi.spyOn(adsService, "review").mockResolvedValue();
    await mount(AdReviewView);
    expect($$("[data-testid=review-item]")).toHaveLength(1);
    await click(buttonNamed("Load more"));
    expect(queue).toHaveBeenLastCalledWith("n1");
    expect($$("[data-testid=review-item]")).toHaveLength(2);

    await click($$("[data-testid=review-item]")[0].querySelector("button"));
    const confirm = $("[data-testid=confirm-reject]") as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    const notes = $("textarea") as HTMLTextAreaElement;
    notes.value = "Misleading claim";
    notes.dispatchEvent(new Event("input"));
    await flush();
    await click(confirm);
    expect(review).toHaveBeenCalledWith("1", "rejected", "Misleading claim");
    expect($$("[data-testid=review-item]")).toHaveLength(1);
  });
});
