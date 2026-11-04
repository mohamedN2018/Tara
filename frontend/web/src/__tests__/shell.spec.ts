import { createPinia, getActivePinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type Component, createApp, defineComponent, type App } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import LeftSidebar from "@/components/layout/LeftSidebar.vue";
import { navItems, SIDEBAR_COLLAPSED_COUNT, SIDEBAR_EXPANDED_KEY, loadSidebarExpanded, saveSidebarExpanded, visibleNavItems } from "@/components/layout/navItems";
import RightSidebar from "@/components/layout/RightSidebar.vue";
import { railAd, railVisible, setRailAd, upcomingEvents } from "@/components/layout/rightRail";
import { clearShortcutsCache, loadShortcuts } from "@/components/layout/shortcuts";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import { isLegalDoc, LEGAL_VERSIONS, PRIVACY_VERSION, TERMS_VERSION } from "@/lib/legal";
import { legalContent } from "@/lib/legalContent";
import { router as appRouter } from "@/router";
import { useAuthStore } from "@/stores/auth";
import type { Profile } from "@/types";

const page = <T>(data: T[]) => ({ data: { data, page: { next_cursor: null, prev_cursor: null, has_more: false } } });

/** Answers GETs by path (and the scope/mine params), empty for anything else. */
function mockGets(routes: Record<string, unknown>) {
  return vi.spyOn(api, "get").mockImplementation(async (url: string, config?: { params?: Record<string, unknown> }) => {
    const p = config?.params ?? {};
    const key = p.scope ? `${url}?scope=${p.scope}` : p.mine ? `${url}?mine=1` : url;
    if (key in routes) return routes[key];
    if (url === "/friends/") return { data: { data: { friends: [] } } };
    return page([]);
  });
}

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;

async function flush() {
  for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0));
}

function signIn() {
  const auth = useAuthStore();
  auth.account = { id: "me-1", email: "me@example.com" } as never;
  auth.profile = { handle: "laila", display_name: "Laila", avatar_media_id: null, cover_media_id: null, visibility: "public" } as Profile;
}

beforeEach(() => {
  const pinia = createPinia();
  setActivePinia(pinia);
  localStorage.clear();
  clearShortcutsCache();
  setRailAd(null);
  i18n.global.locale.value = "en";
  vi.spyOn(api, "post").mockResolvedValue({ data: { data: [] } });
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
});

describe("left sidebar: See more / See less", () => {
  it("persists the expanded state in localStorage", () => {
    expect(loadSidebarExpanded()).toBe(false);
    saveSidebarExpanded(true);
    expect(localStorage.getItem(SIDEBAR_EXPANDED_KEY)).toBe("1");
    expect(loadSidebarExpanded()).toBe(true);
    saveSidebarExpanded(false);
    expect(localStorage.getItem(SIDEBAR_EXPANDED_KEY)).toBeNull();
  });

  it("falls back to collapsed when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(loadSidebarExpanded()).toBe(false);
    expect(() => saveSidebarExpanded(true)).not.toThrow();
  });

  it("hides staff items from everyone else", () => {
    expect(visibleNavItems(navItems, { isStaff: false }).some((i) => i.staff)).toBe(false);
    expect(visibleNavItems(navItems, { isStaff: true }).some((i) => i.route === "/admin")).toBe(true);
  });

  it("shows the first items, expands on click, and remembers it on the next mount", async () => {
    mockGets({});
    signIn();
    const total = visibleNavItems(navItems, { isStaff: false }).length;
    expect(total).toBeGreaterThan(SIDEBAR_COLLAPSED_COUNT);

    let el = await mountWithPinia(LeftSidebar);
    const rows = () => el.querySelectorAll('[data-testid="sidebar-items"] a').length;
    const toggle = () => el.querySelector<HTMLButtonElement>('[data-testid="sidebar-see-more"]')!;
    expect(rows()).toBe(SIDEBAR_COLLAPSED_COUNT);
    expect(toggle().textContent).toContain("See more");
    expect(toggle().getAttribute("aria-expanded")).toBe("false");

    toggle().click();
    await flush();
    expect(rows()).toBe(total);
    expect(toggle().textContent).toContain("See less");
    expect(localStorage.getItem(SIDEBAR_EXPANDED_KEY)).toBe("1");

    app?.unmount();
    host?.remove();
    el = await mountWithPinia(LeftSidebar);
    expect(rows()).toBe(total);

    toggle().click();
    await flush();
    expect(rows()).toBe(SIDEBAR_COLLAPSED_COUNT);
    expect(localStorage.getItem(SIDEBAR_EXPANDED_KEY)).toBeNull();
  });

  it("links the profile row and the legal footer", async () => {
    mockGets({});
    signIn();
    const el = await mountWithPinia(LeftSidebar);
    expect(el.querySelector('[data-testid="sidebar-profile"]')?.getAttribute("href")).toBe("/u/laila");
    const footer = el.querySelector('[data-testid="sidebar-footer"]')!;
    const hrefs = [...footer.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(expect.arrayContaining(["/legal/terms", "/legal/privacy"]));
    expect(footer.textContent).toContain(`© Tara ${new Date().getFullYear()}`);
  });
});

describe("Your shortcuts", () => {
  const pages = [{ id: "p1", handle: "bakery", name: "Nesma Bakery", avatar_media_id: "m1", my_role: "owner" }];
  const groups = [
    { id: "g1", handle: "readers", name: "Readers", cover_media_id: null, viewer: { state: "active" } },
    { id: "g2", handle: "", name: "Hidden club", cover_media_id: null, viewer: { state: "active" } },
    { id: "g3", handle: "pending", name: "Pending", cover_media_id: null, viewer: { state: "requested" } },
  ];

  it("come from the pages (mine=1) and groups (scope=mine) APIs", async () => {
    const get = mockGets({ "/pages/?mine=1": page(pages), "/groups/?scope=mine": page(groups) });
    const list = await loadShortcuts();
    expect(get).toHaveBeenCalledWith("/pages/", expect.objectContaining({ params: expect.objectContaining({ mine: 1 }) }));
    expect(get).toHaveBeenCalledWith("/groups/", expect.objectContaining({ params: expect.objectContaining({ scope: "mine" }) }));
    expect(list).toEqual([
      { kind: "page", id: "p1", name: "Nesma Bakery", to: "/pages/bakery", mediaId: "m1" },
      { kind: "group", id: "g1", name: "Readers", to: "/groups/readers", mediaId: null },
      { kind: "group", id: "g2", name: "Hidden club", to: "/groups/g2", mediaId: null },
    ]);
  });

  it("render in the sidebar, and a failing source only drops its half", async () => {
    vi.spyOn(api, "get").mockImplementation(async (url: string) => {
      if (url === "/pages/") throw new Error("down");
      if (url === "/groups/") return page(groups.slice(0, 1));
      return page([]);
    });
    signIn();
    const el = await mountWithPinia(LeftSidebar);
    const names = [...el.querySelectorAll('[data-testid="sidebar-shortcuts"] a bdi')].map((s) => s.textContent?.trim());
    expect(names).toEqual(["Readers"]);
  });

  it("are not rendered when the account has none", async () => {
    mockGets({});
    signIn();
    const el = await mountWithPinia(LeftSidebar);
    expect(el.querySelector('[data-testid="sidebar-shortcuts"]')).toBeNull();
  });
});

describe("right column", () => {
  const ad = { creative_id: "c1", headline: "Fresh bread", body: "Daily", cta: "Order", link_url: "https://example.com", token: "tok", sponsored: true };

  beforeEach(() => {
    // SponsoredCard reports impressions through an IntersectionObserver (absent in jsdom).
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        observe() {}
        disconnect() {}
      },
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    railVisible.value = false;
  });

  it("renders no ad card when no ad was served", async () => {
    mockGets({});
    signIn();
    railVisible.value = true;
    const el = await mountWithPinia(RightSidebar);
    expect(railAd.value).toBeNull();
    expect(el.querySelector('[data-testid="rail-sponsored"]')).toBeNull();
    expect(el.querySelector('[data-testid="sponsored"]')).toBeNull();
    expect(el.textContent).not.toContain("Sponsored");
  });

  it("ignores an empty slot", () => {
    setRailAd({ ...ad, creative_id: "", headline: "" });
    expect(railAd.value).toBeNull();
    setRailAd(undefined);
    expect(railAd.value).toBeNull();
  });

  it("shows the served ad on Home while the column is on screen, nowhere else", async () => {
    mockGets({});
    signIn();
    setRailAd(ad);
    railVisible.value = true;
    let el = await mountWithPinia(RightSidebar, "/home");
    expect(el.querySelector('[data-testid="rail-sponsored"] [data-testid="sponsored"]')?.textContent).toContain("Fresh bread");

    app?.unmount();
    host?.remove();
    el = await mountWithPinia(RightSidebar, "/friends");
    expect(el.querySelector('[data-testid="sponsored"]')).toBeNull();

    app?.unmount();
    host?.remove();
    railVisible.value = false;
    el = await mountWithPinia(RightSidebar, "/home");
    expect(el.querySelector('[data-testid="sponsored"]')).toBeNull();
  });

  it("accepts a friend request through the graph API", async () => {
    mockGets({
      "/friends/requests/": {
        data: { data: [{ id: "fr1", account_low_id: "u2", account_high_id: "me-1", status: "pending", requested_by: "u2", created_at: "2026-11-04T10:00:00Z", accepted_at: null }] },
      },
    });
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: [] } });
    signIn();
    const el = await mountWithPinia(RightSidebar);
    expect(el.querySelectorAll('[data-testid="rail-request"]').length).toBe(1);
    el.querySelector<HTMLButtonElement>('[data-testid="rail-request-accept"]')!.click();
    await flush();
    expect(post).toHaveBeenCalledWith("/friends/requests/fr1/accept/");
    expect(el.querySelector('[data-testid="rail-requests"]')).toBeNull();
    // The new friend joins the contacts.
    expect(el.querySelectorAll('[data-testid="rail-contact"]').length).toBe(1);
  });

  it("lists the viewer's upcoming events (going + hosting), soonest first, without cancelled ones", async () => {
    const ev = (id: string, starts_at: string, status = "scheduled") => ({ id, title: id, starts_at, ends_at: null, status });
    mockGets({
      "/events/?scope=going": page([ev("b", "2026-12-02T10:00:00Z"), ev("x", "2026-11-20T10:00:00Z", "cancelled")]),
      "/events/?scope=hosting": page([ev("a", "2026-11-30T10:00:00Z"), ev("b", "2026-12-02T10:00:00Z")]),
    });
    expect((await upcomingEvents()).map((e) => e.id)).toEqual(["a", "b"]);
  });
});

describe("legal pages", () => {
  it("export the versions registration records consent against", () => {
    expect(TERMS_VERSION).toBe("2026-11-04-draft");
    expect(PRIVACY_VERSION).toBe("2026-11-04-draft");
    expect(LEGAL_VERSIONS).toEqual({ terms: TERMS_VERSION, privacy: PRIVACY_VERSION });
    expect(isLegalDoc("terms")).toBe(true);
    expect(isLegalDoc("cookies")).toBe(false);
  });

  it.each(["terms", "privacy"] as const)("%s has the same sections in Arabic and English, none empty", (kind) => {
    const { ar, en } = legalContent[kind];
    expect(ar.sections.map((s) => s.id)).toEqual(en.sections.map((s) => s.id));
    for (const doc of [ar, en]) {
      expect(doc.title && doc.intro).toBeTruthy();
      for (const s of doc.sections) expect((s.paragraphs?.length ?? 0) + (s.bullets?.length ?? 0)).toBeGreaterThan(0);
    }
  });

  it("covers the required topics", () => {
    const ids = (kind: "terms" | "privacy") => legalContent[kind].en.sections.map((s) => s.id);
    expect(ids("terms")).toEqual(expect.arrayContaining(["accounts", "content", "moderation", "ip", "security", "termination", "contact"]));
    expect(ids("privacy")).toEqual(expect.arrayContaining(["collect", "purposes", "retention", "rights", "cookies", "security", "contact"]));
    expect(legalContent.terms.en.sections[0].paragraphs?.join(" ")).toContain("13");
  });

  it("are public routes; /menu needs a session", () => {
    expect(appRouter.resolve("/legal/terms").name).toBe("legal");
    expect(appRouter.resolve("/legal/privacy").meta).toEqual({});
    expect(appRouter.resolve("/legal/other").name).toBe("not-found");
    expect(appRouter.resolve("/menu").meta.auth).toBe(true);
  });
});

/** Mount a component with router, i18n and the test's active pinia. */
async function mountWithPinia(component: Component, path = "/home") {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/home", name: "home", component: Blank },
      { path: "/u/id/:id", name: "profile-by-id", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push(path);
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp(component);
  app.use(getActivePinia()!).use(router).use(i18n);
  app.mount(host);
  await flush();
  return host;
}
