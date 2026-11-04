import { createPinia, getActivePinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, type Component, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import { resetRelationshipPrefs } from "@/lib/useRelationshipPrefs";
import ConnectionsView from "@/views/ConnectionsView.vue";
import FriendsView from "@/views/FriendsView.vue";
import RailPageSuggestions from "@/components/layout/RailPageSuggestions.vue";
import RailPeopleSuggestions from "@/components/layout/RailPeopleSuggestions.vue";
import FriendButton from "@/components/social/FriendButton.vue";
import PersonActionsMenu from "@/components/social/PersonActionsMenu.vue";

// Track T2: Friends hub (deep-linkable sections, suggestions with undo),
// Connections lists (muted/restricted/favorites), the people "..." menu and the
// privacy center. Every action must hit the real graph/profile endpoint.

vi.mock("@/components/layout/AppShell.vue", () => ({
  default: defineComponent({ setup: (_, { slots }) => () => h("div", slots.default?.()) }),
}));

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;
let router: Router;

type Handler = (url: string, config?: unknown) => unknown;
function mockGet(routes: Record<string, unknown>, fallback?: Handler) {
  return vi.spyOn(api, "get").mockImplementation(async (url: string, config?: unknown) => {
    if (url in routes) return { data: { data: routes[url] } };
    const out = fallback?.(url, config);
    if (out !== undefined) return out as never;
    return { data: { data: [], page: { next_cursor: null, prev_cursor: null, has_more: false } } };
  });
}

async function flush() {
  for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0));
}

async function mount(component: Component, path = "/x", props: Record<string, unknown> = {}) {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/u/id/:id", name: "profile-by-id", component: Blank },
      { path: "/connections", name: "connections", component: Blank },
      { path: "/pages/:handle", name: "page", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push(path);
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({ render: () => h(component, props) });
  app.use(getActivePinia()!).use(router).use(i18n);
  app.mount(host);
  await flush();
  return host;
}

const q = (el: ParentNode, id: string) => el.querySelector<HTMLElement>(`[data-testid="${id}"]`);
const qa = (el: ParentNode, id: string) => [...el.querySelectorAll<HTMLElement>(`[data-testid="${id}"]`)];
const byText = (el: ParentNode, text: string) =>
  [...el.querySelectorAll<HTMLElement>("button, a")].find((b) => b.textContent?.trim().includes(text));

beforeEach(() => {
  setActivePinia(createPinia());
  localStorage.clear();
  resetRelationshipPrefs();
  i18n.global.locale.value = "en";
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.restoreAllMocks();
});

describe("Friends hub", () => {
  it("opens the section named in ?tab= and writes the section back to the URL", async () => {
    mockGet({ "/social/suggestions/": { results: [{ account_id: "u1", mutual_count: 2, reason: "mutual_friends" }] } });
    const el = await mount(FriendsView, "/friends?tab=suggestions");
    expect(q(el, "friends-tab-suggestions")?.getAttribute("aria-current")).toBe("page");
    expect(qa(el, "friend-suggestion-card")).toHaveLength(1);
    q(el, "friends-tab-sent")!.click();
    await flush();
    expect(router.currentRoute.value.query.tab).toBe("sent");
  });

  it("removes a suggestion through graph and undoes it", async () => {
    mockGet({ "/social/suggestions/": { results: [{ account_id: "u1", mutual_count: 1, reason: "mutual_friends" }] } });
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: {} });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: {} });
    const el = await mount(FriendsView, "/friends?tab=suggestions");
    q(el, "suggestion-remove")!.click();
    await flush();
    expect(post).toHaveBeenCalledWith("/social/suggestions/u1/dismiss/", { target_type: "user" });
    expect(el.textContent).toContain("Removed from suggestions");
    byText(el, "Undo")!.click();
    await flush();
    expect(del).toHaveBeenCalledWith("/social/suggestions/u1/dismiss/", { params: { target_type: "user" } });
    expect(q(el, "suggestion-add")).not.toBeNull();
  });

  it("sends a request from a suggestion and cancels it with the returned id", async () => {
    mockGet({ "/social/suggestions/": { results: [{ account_id: "u1", mutual_count: 0, reason: "follows_you" }] } });
    const post = vi.spyOn(api, "post").mockImplementation(async (url: string) =>
      url === "/friends/requests/" ? { data: { data: { id: "req-9" } } } : { data: {} },
    );
    const el = await mount(FriendsView, "/friends?tab=suggestions");
    q(el, "suggestion-add")!.click();
    await flush();
    expect(post).toHaveBeenCalledWith("/friends/requests/", { to_user_id: "u1" });
    byText(el, "Cancel request")!.click();
    await flush();
    expect(post).toHaveBeenCalledWith("/friends/requests/req-9/reject/");
  });
});

describe("Connections lists", () => {
  it("lists muted accounts from graph and unmutes one", async () => {
    mockGet({ "/social/mutes/": { muted: ["m1", "m2"] } });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: {} });
    const el = await mount(ConnectionsView, "/connections?tab=muted");
    expect(q(el, "connections-tab-muted")?.getAttribute("aria-selected")).toBe("true");
    const list = q(el, "connections-list-muted")!;
    expect(list.querySelectorAll("li")).toHaveLength(2);
    byText(list, "Unmute")!.click();
    await flush();
    expect(del).toHaveBeenCalledWith("/social/mutes/m1/");
    expect(q(el, "connections-list-muted")!.querySelectorAll("li")).toHaveLength(1);
  });

  it("shows an error, not an empty list, when a private list cannot load", async () => {
    vi.spyOn(api, "get").mockRejectedValue(new Error("down"));
    const el = await mount(ConnectionsView, "/connections?tab=favorites");
    expect(q(el, "connections-list-favorites")).toBeNull();
    expect(el.textContent).not.toContain("No favorites yet");
  });
});

describe("Person actions menu", () => {
  const lists = { "/social/mutes/": { muted: [] }, "/social/restricted/": { restricted: [] }, "/social/favorites/": { favorites: [] }, "/blocks/": { blocked: [] } };

  it("offers favorites, mute, restrict, block and report for another person", async () => {
    mockGet(lists);
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: {} });
    const el = await mount(PersonActionsMenu, "/x", { userId: "u7", name: "Mona" });
    q(el, "person-actions")!.click();
    await flush();
    const menu = q(el, "person-actions-menu")!;
    for (const label of ["Add to Favorites", "Mute Mona", "Restrict", "Find support or report profile"]) {
      expect(byText(menu, label)).toBeTruthy();
    }
    byText(menu, "Add to Favorites")!.click();
    await flush();
    expect(post).toHaveBeenCalledWith("/social/favorites/u7/");
  });

  it("hides list-based items whose list failed to load", async () => {
    vi.spyOn(api, "get").mockRejectedValue(new Error("down"));
    const el = await mount(PersonActionsMenu, "/x", { userId: "u7", name: "Mona" });
    q(el, "person-actions")!.click();
    await flush();
    const menu = q(el, "person-actions-menu")!;
    expect(byText(menu, "Mute Mona")).toBeUndefined();
    expect(byText(menu, "Find support or report profile")).toBeTruthy();
  });
});

// The old /settings/privacy page (PrivacySettingsView) is gone: its cards live in the
// settings centre and are covered by settingsCenter.spec.ts.

describe("Rail suggestions undo", () => {
  it("links People you may know to the Friends suggestions section and undoes a removal", async () => {
    mockGet({ "/social/suggestions/": { results: [{ account_id: "u1", mutual_count: 1, reason: "mutual_friends" }] } });
    vi.spyOn(api, "post").mockResolvedValue({ data: {} });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: {} });
    const el = await mount(RailPeopleSuggestions);
    expect(q(el, "rail-people-see-all")?.getAttribute("href")).toBe("/friends?tab=suggestions");
    q(el, "rail-person-dismiss")!.click();
    await flush();
    expect(qa(el, "rail-person")).toHaveLength(0);
    q(el, "rail-person-undo")!.click();
    await flush();
    expect(del).toHaveBeenCalledWith("/social/suggestions/u1/dismiss/", { params: { target_type: "user" } });
    expect(qa(el, "rail-person")).toHaveLength(1);
  });

  it("dismisses a suggested page as a page and can undo it", async () => {
    mockGet({
      "/social/suggestions/pages/": {
        results: [{ page_id: "p1", handle: "bakery", name: "Bakery", category: "Food", avatar_media_id: null, followers_count: 3 }],
      },
    });
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: {} });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: {} });
    const el = await mount(RailPageSuggestions);
    q(el, "rail-page-dismiss")!.click();
    await flush();
    expect(post).toHaveBeenCalledWith("/social/suggestions/p1/dismiss/", { target_type: "page" });
    q(el, "rail-page-undo")!.click();
    await flush();
    expect(del).toHaveBeenCalledWith("/social/suggestions/p1/dismiss/", { params: { target_type: "page" } });
    expect(qa(el, "rail-page")).toHaveLength(1);
  });
});

describe("Friend button", () => {
  it("cancels a sent request through reject/, never through unfriend", async () => {
    mockGet({ "/social/favorites/": { favorites: [] } });
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: {} });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: {} });
    const el = await mount(FriendButton, "/x", { userId: "u3", state: "pending_out", requestId: "r-1", name: "Sam" });
    (q(el, "friend-button")!.querySelector("button") as HTMLButtonElement).click();
    await flush();
    byText(el, "Cancel request")!.click();
    await flush();
    expect(post).toHaveBeenCalledWith("/friends/requests/r-1/reject/");
    expect(del).not.toHaveBeenCalled();
    expect(q(el, "friend-button")?.dataset.state).toBe("none");
  });

  it("asks before unfriending from the Friends menu", async () => {
    mockGet({ "/social/favorites/": { favorites: [] } });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: {} });
    const el = await mount(FriendButton, "/x", { userId: "u3", state: "friends", name: "Sam" });
    (q(el, "friend-button")!.querySelector("button") as HTMLButtonElement).click();
    await flush();
    byText(el, "Unfriend")!.click();
    await flush();
    expect(del).not.toHaveBeenCalled();
    const dialog = document.querySelector('[role="dialog"], [role="alertdialog"]') as HTMLElement;
    [...dialog.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Unfriend")!.click();
    await flush();
    expect(del).toHaveBeenCalledWith("/friends/u3/");
  });
});
