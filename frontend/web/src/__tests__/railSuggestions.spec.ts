import { createPinia, getActivePinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, type Component, createApp, defineComponent } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import RailPageSuggestions from "@/components/layout/RailPageSuggestions.vue";
import RailPeopleSuggestions from "@/components/layout/RailPeopleSuggestions.vue";
import RightSidebar from "@/components/layout/RightSidebar.vue";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import { relationshipsService } from "@/services/relationships";

// Wave 2D: the right column's "People you may know" and "Suggested pages".

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;

const person = (id: string, mutual: number, reason = "mutual_friends") => ({ account_id: id, mutual_count: mutual, reason });
const pageRow = (id: string, followers: number) => ({
  page_id: id,
  handle: `page_${id}`,
  name: `Page ${id}`,
  category: "Food",
  avatar_media_id: null,
  followers_count: followers,
});

function mockGets(people: unknown[], pages: unknown[] = []) {
  return vi.spyOn(api, "get").mockImplementation(async (url: string) => {
    if (url === "/social/suggestions/") return { data: { data: { results: people } } };
    if (url === "/social/suggestions/pages/") return { data: { data: { results: pages } } };
    if (url === "/friends/") return { data: { data: { friends: [] } } };
    return { data: { data: [], page: { next_cursor: null, prev_cursor: null, has_more: false } } };
  });
}

async function flush() {
  for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0));
}

async function mount(component: Component) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/home", name: "home", component: Blank },
      { path: "/u/id/:id", name: "profile-by-id", component: Blank },
      { path: "/pages/:handle", name: "page", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push("/home");
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp(component);
  app.use(getActivePinia()!).use(router).use(i18n);
  app.mount(host);
  await flush();
  return host;
}

const q = (el: HTMLElement, id: string) => el.querySelector<HTMLElement>(`[data-testid="${id}"]`);
const qa = (el: HTMLElement, id: string) => [...el.querySelectorAll<HTMLElement>(`[data-testid="${id}"]`)];

beforeEach(() => {
  setActivePinia(createPinia());
  localStorage.clear();
  i18n.global.locale.value = "en";
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.restoreAllMocks();
});

describe("People you may know", () => {
  it("shows three suggestions with their mutual count, never who the mutual friends are", async () => {
    const get = mockGets([person("u1", 2), person("u2", 1), person("u3", 0, "follows_you"), person("u4", 1)]);
    vi.spyOn(api, "post").mockResolvedValue({ data: { data: [] } });
    const el = await mount(RailPeopleSuggestions);
    expect(get).toHaveBeenCalledWith("/social/suggestions/", { params: { limit: 6 } });
    expect(q(el, "rail-people")?.querySelector("h2")?.textContent).toBe("People you may know");
    const rows = qa(el, "rail-person");
    expect(rows.map((r) => r.dataset.accountId)).toEqual(["u1", "u2", "u3"]);
    expect(qa(el, "rail-person-mutual").map((r) => r.textContent?.trim())).toEqual([
      "2 mutual friends",
      "1 mutual friend",
      "Follows you",
    ]);
  });

  it("sends a friend request through graph and shows it as sent", async () => {
    mockGets([person("u1", 1)]);
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: {} } });
    const el = await mount(RailPeopleSuggestions);
    q(el, "rail-person-add")!.click();
    await flush();
    expect(post).toHaveBeenCalledWith("/friends/requests/", { to_user_id: "u1" });
    expect(q(el, "rail-person-add")).toBeNull();
    expect(q(el, "rail-person-sent")?.textContent).toContain("Request sent");
  });

  it("treats an already pending request (409) as sent", async () => {
    mockGets([person("u1", 1)]);
    vi.spyOn(api, "post").mockImplementation(async (url: string) => {
      if (url === "/friends/requests/") throw Object.assign(new Error("conflict"), { response: { status: 409 } });
      return { data: { data: [] } };
    });
    const el = await mount(RailPeopleSuggestions);
    q(el, "rail-person-add")!.click();
    await flush();
    expect(q(el, "rail-person-sent")).not.toBeNull();
  });

  it("dismisses a suggestion on the server and lets the next one move up", async () => {
    mockGets([person("u1", 3), person("u2", 2), person("u3", 1), person("u4", 1)]);
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: [] } });
    const el = await mount(RailPeopleSuggestions);
    const dismiss = qa(el, "rail-person-dismiss")[0];
    expect(dismiss.getAttribute("aria-label")).toMatch(/^Remove .+ from suggestions$/);
    dismiss.click();
    await flush();
    expect(post).toHaveBeenCalledWith("/social/suggestions/u1/dismiss/", { target_type: "user" });
    expect(qa(el, "rail-person").map((r) => r.dataset.accountId)).toEqual(["u2", "u3", "u4"]);
  });

  it("renders nothing when graph has no suggestions or fails", async () => {
    mockGets([]);
    let el = await mount(RailPeopleSuggestions);
    expect(q(el, "rail-people")).toBeNull();
    app?.unmount();
    host?.remove();
    vi.restoreAllMocks();
    vi.spyOn(api, "get").mockRejectedValue(new Error("down"));
    el = await mount(RailPeopleSuggestions);
    expect(q(el, "rail-people")).toBeNull();
  });

  it("uses the Arabic plural forms", async () => {
    i18n.global.locale.value = "ar";
    mockGets([person("u1", 2), person("u2", 11), person("u3", 1)]);
    vi.spyOn(api, "post").mockResolvedValue({ data: { data: [] } });
    const el = await mount(RailPeopleSuggestions);
    expect(q(el, "rail-people")?.querySelector("h2")?.textContent).toBe("أشخاص قد تعرفهم");
    expect(qa(el, "rail-person-mutual").map((r) => r.textContent?.trim())).toEqual([
      "صديقان مشتركان",
      "11 صديقًا مشتركًا",
      "صديق مشترك واحد",
    ]);
  });
});

describe("Suggested pages", () => {
  it("lists pages with their followers and follows one through graph", async () => {
    const get = mockGets([], [pageRow("p1", 3), pageRow("p2", 0)]);
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: [] } });
    const el = await mount(RailPageSuggestions);
    expect(get).toHaveBeenCalledWith("/social/suggestions/pages/", { params: { limit: 3 } });
    const rows = qa(el, "rail-page");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("Page p1");
    expect(rows[0].textContent).toContain("3 followers");
    expect(rows[0].querySelector("a")?.getAttribute("href")).toBe("/pages/page_p1");
    expect(qa(el, "rail-page-follow")[0].getAttribute("aria-label")).toBe("Follow Page p1");

    qa(el, "rail-page-follow")[0].click();
    await flush();
    expect(post).toHaveBeenCalledWith("/follows/p1/", { target_type: "page" });
    expect(rows[0].textContent).toContain("Following");
    expect(rows[0].textContent).toContain("4 followers");
    expect(qa(el, "rail-page-follow")).toHaveLength(1);
  });

  it("renders nothing without suggestions", async () => {
    mockGets([], []);
    const el = await mount(RailPageSuggestions);
    expect(q(el, "rail-pages")).toBeNull();
  });
});

describe("right column with the widgets", () => {
  it("places the suggestions after friend requests and before contacts", async () => {
    mockGets([person("u1", 1)], [pageRow("p1", 1)]);
    vi.spyOn(api, "post").mockResolvedValue({ data: { data: [] } });
    const el = await mount(RightSidebar);
    const order = [...el.querySelectorAll("section")].map((s) => s.dataset.testid);
    expect(order).toEqual(["rail-people", "rail-pages", "rail-contacts"]);
  });
});

describe("relationships service", () => {
  it("reads the owner-only preference lists by their keys", async () => {
    vi.spyOn(api, "get").mockImplementation(async (url: string) => {
      if (url === "/social/mutes/") return { data: { data: { muted: ["a"] } } };
      if (url === "/social/favorites/") return { data: { data: { favorites: ["b"] } } };
      return { data: { data: { restricted: ["c"] } } };
    });
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: {} });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: {} });
    expect(await relationshipsService.list("mutes")).toEqual(["a"]);
    expect(await relationshipsService.list("favorites")).toEqual(["b"]);
    expect(await relationshipsService.list("restricted")).toEqual(["c"]);
    await relationshipsService.add("mutes", "x");
    await relationshipsService.remove("favorites", "y");
    expect(post).toHaveBeenCalledWith("/social/mutes/x/");
    expect(del).toHaveBeenCalledWith("/social/favorites/y/");
  });
});
