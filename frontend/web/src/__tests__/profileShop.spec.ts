import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, defineComponent, h, reactive } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

import ProfileHero from "@/components/profile/ProfileHero.vue";
import { i18n } from "@/i18n";
import { useProfile } from "@/lib/useProfile";
import { graphService } from "@/services/graph";
import { marketplaceService } from "@/services/marketplace";
import { postService } from "@/services/post";
import { profileService } from "@/services/profile";
import { relationshipsService } from "@/services/relationships";
import { useAuthStore } from "@/stores/auth";

// The profile's Marketplace tab (T6): it shows only when marketplace's seller
// page would open for this viewer, and a ?tab=marketplace link to someone
// without a shop lands on Posts.

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;
let state: ReturnType<typeof reactive<ReturnType<typeof useProfile>>> | null = null;

async function flush() {
  for (let i = 0; i < 15; i++) await new Promise((r) => setTimeout(r, 0));
}

function mockApi(shop: "yes" | "no") {
  for (const m of ["followingIds", "friends", "incomingRequests", "outgoingRequests", "socialFriends", "mutualFriends"] as const) {
    vi.spyOn(graphService, m).mockResolvedValue([] as never);
  }
  vi.spyOn(relationshipsService, "counts").mockRejectedValue(new Error("hidden"));
  vi.spyOn(postService, "timelinePage").mockResolvedValue({ data: [], page: { next_cursor: null, has_more: false } } as never);
  vi.spyOn(profileService, "getById").mockResolvedValue({
    account_id: "s1",
    display_name: "Sam",
    handle: "sam",
    is_self: false,
  } as never);
  // The profile never asks the seller page itself (its 404 logged an error on every profile).
  vi.spyOn(marketplaceService, "seller").mockRejectedValue(new Error("not asked by the profile"));
  return vi.spyOn(marketplaceService, "sellerHasShop").mockResolvedValue(shop === "yes");
}

async function mount(path: string): Promise<{ el: HTMLElement; router: Router }> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/u/id/:id", name: "profile-by-id", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push(path);
  await router.isReady();
  const Harness = defineComponent({
    setup() {
      state = reactive(useProfile());
      return () => (state!.profile ? h(ProfileHero, { state: state! }) : null);
    },
  });
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp(Harness);
  app.use(createPinia()).use(router).use(i18n);
  app.mount(host);
  await flush();
  return { el: host, router };
}

const q = (el: ParentNode, id: string) => el.querySelector<HTMLElement>(`[data-testid="${id}"]`);

beforeEach(() => {
  setActivePinia(createPinia());
  localStorage.clear();
  i18n.global.locale.value = "en";
  useAuthStore().account = { id: "me-1", email: "me@example.com" } as never;
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  state = null;
  vi.restoreAllMocks();
});

describe("profile Marketplace tab", () => {
  it("shows for a seller whose shop this viewer may open", async () => {
    const get = mockApi("yes");
    const { el } = await mount("/u/id/s1");
    expect(get).toHaveBeenCalledWith("s1");
    expect(marketplaceService.seller).not.toHaveBeenCalled();
    expect(state!.hasShop).toBe(true);
    expect(q(el, "profile-tab-marketplace")?.textContent).toContain("Marketplace");
  });

  it("stays hidden when marketplace answers has_shop false, and a deep link lands on Posts", async () => {
    mockApi("no");
    const { el, router } = await mount("/u/id/s1?tab=marketplace");
    expect(state!.hasShop).toBe(false);
    expect(q(el, "profile-tab-marketplace")).toBeNull();
    expect(state!.tab).toBe("posts");
    expect(router.currentRoute.value.query.tab).toBeUndefined();
  });

  it("opens straight on the shop from ?tab=marketplace", async () => {
    mockApi("yes");
    await mount("/u/id/s1?tab=marketplace");
    expect(state!.tab).toBe("marketplace");
  });

  it("asks the always-200 shop endpoint, not the seller page", async () => {
    const { api } = await import("@/lib/api");
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: { data: { has_shop: false } } } as never);
    expect(await marketplaceService.sellerHasShop("s1")).toBe(false);
    expect(get).toHaveBeenCalledWith("/marketplace/sellers/s1/shop/");
  });

  it("keeps the tab hidden and says so once when marketplace is down", async () => {
    mockApi("yes");
    vi.spyOn(marketplaceService, "sellerHasShop").mockRejectedValue(new Error("502"));
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    await mount("/u/id/s1");
    expect(state!.hasShop).toBe(false);
    expect(warn).toHaveBeenCalledTimes(1);
  });
});
