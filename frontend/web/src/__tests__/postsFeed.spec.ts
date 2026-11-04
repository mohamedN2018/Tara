import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, type Component, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

import FeedPreferences from "@/components/feed/FeedPreferences.vue";
import HideFeedbackCard from "@/components/post/HideFeedbackCard.vue";
import MyPendingPosts from "@/components/post/MyPendingPosts.vue";
import VideosRail from "@/components/post/VideosRail.vue";
import SearchHome from "@/components/search/SearchHome.vue";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import { downloadMedia } from "@/lib/downloadMedia";
import { entityRoute, tagRoute } from "@/lib/searchRoutes";
import { useAuthStore } from "@/stores/auth";
import type { Post } from "@/types";
import SavedView from "@/views/SavedView.vue";

// Track T4: posts, feed, saved and search surfaces.
vi.mock("@/components/layout/AppShell.vue", () => ({
  default: defineComponent({ setup: (_, { slots }) => () => h("div", slots.default?.()) }),
}));
// PostCard has its own specs; here it only needs to show which post it is.
vi.mock("@/components/post/PostCard.vue", () => ({
  default: defineComponent({
    props: { post: { type: Object, required: true } },
    emits: ["unsaved", "removed"],
    setup: (props) => () => h("article", { "data-testid": "post-card", "data-id": (props.post as Post).id }),
  }),
}));

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;
let router: Router;

async function flush() {
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
}

async function mount(component: Component, props: Record<string, unknown> = {}) {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/home", name: "home", component: Blank },
      { path: "/search", name: "search", component: Blank },
      { path: "/posts/:id", name: "post", component: Blank },
      { path: "/u/id/:id", name: "profile-by-id", component: Blank },
      { path: "/marketplace/:id", name: "listing", component: Blank },
      { path: "/events/:id", name: "event", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push("/home");
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp(component, props);
  app.use(pinia).use(router).use(i18n);
  app.mount(host);
  await flush();
  return host;
}

let pinia: ReturnType<typeof createPinia>;
const page = <T>(data: T[], next: string | null = null) => ({ data: { data, page: { next_cursor: next, has_more: !!next } } });
const post = (id: string, extra: Partial<Post> = {}): Post =>
  ({
    id,
    author_id: `author-${id}`,
    author_type: "user",
    type: "text",
    body: `body ${id}`,
    audience: "public",
    media_ids: [],
    reaction_count: 0,
    comment_count: 0,
    share_count: 0,
    created_at: "2026-11-03T10:00:00Z",
    ...extra,
  }) as Post;
const byText = (el: ParentNode, text: string) =>
  [...el.querySelectorAll<HTMLElement>("button, a")].find((b) => b.textContent?.trim() === text);

beforeEach(() => {
  pinia = createPinia();
  setActivePinia(pinia);
  localStorage.clear();
  i18n.global.locale.value = "en";
  useAuthStore().account = { id: "me-1", email: "me@example.com" } as never;
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.restoreAllMocks();
});

describe("search routes", () => {
  it("opens listings and events on their own pages, tags as a search", () => {
    expect(entityRoute("listing", "l1", "Bike")).toEqual({ name: "listing", params: { id: "l1" } });
    expect(entityRoute("gathering", "e1", "Board games")).toEqual({ name: "event", params: { id: "e1" } });
    expect(entityRoute("user", "u1", "Sara")).toEqual({ name: "profile-by-id", params: { id: "u1" } });
    expect(entityRoute("hashtag", "h", "nile")).toEqual({ name: "search", query: { q: "#nile" } });
    expect(tagRoute("#cairo")).toEqual({ name: "search", query: { q: "#cairo" } });
  });
});

describe("media download", () => {
  it("asks media for a signed URL and opens it", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: { data: { download_url: "https://s3.example/x.jpg?sig=1" } } });
    const open = vi.fn();
    await downloadMedia("m-1", open);
    expect(get).toHaveBeenCalledWith("/media/m-1/download-url/");
    expect(open).toHaveBeenCalledWith("https://s3.example/x.jpg?sig=1");
  });
});

describe("HideFeedbackCard: report and unfollow", () => {
  it("offers unfollow only for followed authors and sends a report reason", async () => {
    const onReport = vi.fn();
    const onUnfollow = vi.fn();
    const el = await mount(HideFeedbackCard, {
      postId: "p1",
      authorName: "Sara",
      canUnfollow: true,
      onReport,
      onUnfollow,
    });
    el.querySelector<HTMLButtonElement>('[data-testid="hide-unfollow"]')!.click();
    expect(onUnfollow).toHaveBeenCalledOnce();

    el.querySelector<HTMLButtonElement>('[data-testid="hide-report"]')!.click();
    await flush();
    const box = el.querySelector<HTMLTextAreaElement>("textarea")!;
    box.value = "spam link";
    box.dispatchEvent(new Event("input"));
    await flush();
    el.querySelector("form")!.dispatchEvent(new Event("submit"));
    expect(onReport).toHaveBeenCalledWith("spam link");
  });

  it("hides unfollow when the post did not come from a follow", async () => {
    const el = await mount(HideFeedbackCard, { postId: "p1", authorName: "Sara" });
    expect(el.querySelector('[data-testid="hide-unfollow"]')).toBeNull();
    expect(el.querySelector('[data-testid="hide-report"]')).not.toBeNull();
  });
});

describe("Saved collections", () => {
  const collections = [
    { id: "c0", name: "Saved", is_default: true, item_count: 2, created_at: "" },
    { id: "c1", name: "Recipes", is_default: false, item_count: 1, created_at: "" },
  ];

  it("lists collections, filters by one, and creates, renames and deletes", async () => {
    const get = vi.spyOn(api, "get").mockImplementation(async (url: string, cfg?: { params?: Record<string, unknown> }) => {
      if (url === "/saved/collections/") return { data: { data: collections } };
      if (url === "/saved/") {
        const items = cfg?.params?.collection_id === "c1"
          ? [{ id: "s2", item_type: "post", item_id: "p2", collection_id: "c1", created_at: "" }]
          : [
              { id: "s1", item_type: "post", item_id: "p1", collection_id: "c0", created_at: "" },
              { id: "s2", item_type: "post", item_id: "p2", collection_id: "c1", created_at: "" },
            ];
        return page(items);
      }
      return page([]);
    });
    vi.spyOn(api, "post").mockImplementation(async (url: string, body?: unknown) => {
      if (url === "/posts/batch/") {
        const ids = (body as { ids: string[] }).ids;
        return { data: { data: ids.map((id) => post(id)) } };
      }
      if (url === "/saved/collections/") return { data: { data: { id: "c2", name: "Trips", is_default: false, item_count: 0, created_at: "" } } };
      return { data: { data: {} } };
    });
    const patch = vi.spyOn(api, "patch").mockResolvedValue({ data: { data: { id: "c1", name: "Food", is_default: false, item_count: 1, created_at: "" } } });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: {} });

    const el = await mount(SavedView);
    expect(el.querySelectorAll('[data-testid="saved-collection"]')).toHaveLength(1);
    expect(el.textContent).toContain("Recipes");

    // One collection: the list asks for it.
    el.querySelector<HTMLButtonElement>('[data-testid="saved-collection"]')!.click();
    await flush();
    expect(get).toHaveBeenCalledWith("/saved/", { params: { item_type: "post", cursor: undefined, collection_id: "c1" } });
    expect(el.querySelector('[data-testid="saved-title"]')!.textContent).toContain("Recipes");

    // Rename it.
    el.querySelector<HTMLButtonElement>('[data-testid="collection-options"]')!.click();
    await flush();
    el.querySelector<HTMLButtonElement>('[data-testid="collection-rename"]')!.click();
    await flush();
    const input = document.querySelector<HTMLInputElement>('[data-testid="saved-name"]')!;
    input.value = "Food";
    input.dispatchEvent(new Event("input"));
    await flush();
    document.querySelector<HTMLFormElement>('[data-testid="saved-dialog"] form')!.dispatchEvent(new Event("submit"));
    await flush();
    expect(patch).toHaveBeenCalledWith("/saved/collections/c1/", { name: "Food" });
    expect(el.textContent).toContain("Food");

    // Delete it: back to all saved items.
    el.querySelector<HTMLButtonElement>('[data-testid="collection-options"]')!.click();
    await flush();
    el.querySelector<HTMLButtonElement>('[data-testid="collection-delete"]')!.click();
    await flush();
    document.querySelector<HTMLButtonElement>('[data-testid="saved-delete-confirm"]')!.click();
    await flush();
    expect(del).toHaveBeenCalledWith("/saved/collections/c1/");
    expect(el.querySelector('[data-testid="saved-title"]')!.textContent).toContain("All saved items");

    // Create one.
    el.querySelector<HTMLButtonElement>('[data-testid="saved-create"]')!.click();
    await flush();
    const name = document.querySelector<HTMLInputElement>('[data-testid="saved-name"]')!;
    name.value = "Trips";
    name.dispatchEvent(new Event("input"));
    await flush();
    document.querySelector<HTMLFormElement>('[data-testid="saved-dialog"] form')!.dispatchEvent(new Event("submit"));
    await flush();
    expect(api.post).toHaveBeenCalledWith("/saved/collections/", { name: "Trips" });
  });
});

describe("Feed preferences: snoozed people", () => {
  it("lists active snoozes and unsnoozes one", async () => {
    vi.spyOn(api, "get").mockImplementation(async (url: string) => {
      if (url === "/feed/snoozes/") return page([{ author_id: "a1", until: "2026-12-01T00:00:00Z", snoozed_at: "2026-11-01T00:00:00Z" }]);
      return { data: { data: [] } };
    });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: {} });
    const el = await mount(FeedPreferences);
    expect(el.querySelectorAll('[data-testid="snoozed-row"]')).toHaveLength(1);
    byText(el, "Unsnooze")!.click();
    await flush();
    expect(del).toHaveBeenCalledWith("/feed/snooze/a1/");
    expect(el.querySelector('[data-testid="snoozed-empty"]')).not.toBeNull();
  });
});

describe("Videos rail", () => {
  it("renders nothing without video posts", async () => {
    vi.spyOn(api, "get").mockResolvedValue(page([]));
    const el = await mount(VideosRail);
    expect(el.querySelector('[data-testid="videos-rail"]')).toBeNull();
  });

  it("shows real video posts with a link to each", async () => {
    vi.spyOn(api, "get").mockImplementation(async (url: string) => {
      if (url === "/posts/") return page([post("v1", { type: "video", media_ids: ["m1"] })]);
      return { data: { data: { poster_url: null } } };
    });
    const el = await mount(VideosRail);
    expect(api.get).toHaveBeenCalledWith("/posts/", { params: { type: "video", cursor: undefined, author_id: undefined } });
    const links = el.querySelectorAll('[data-testid="videos-rail"] li a');
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute("href")).toBe("/posts/v1");
  });
});

describe("Search home: recent and trending", () => {
  it("removes one recent search, clears all, and switches the trending window", async () => {
    const get = vi.spyOn(api, "get").mockImplementation(async (url: string) => {
      if (url === "/search/recent/")
        return {
          data: {
            data: [
              { id: "r1", kind: "query", query: "nile", doc_type: null, doc_id: null, title: "nile", avatar_media_id: null, created_at: "" },
              { id: "r2", kind: "entity", query: "", doc_type: "listing", doc_id: "l1", title: "Bike", avatar_media_id: null, created_at: "" },
            ],
          },
        };
      if (url === "/search/trending/") return { data: { data: [{ tag: "cairo", authors: 3, posts: 5 }] } };
      return { data: { data: [] } };
    });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: {} });
    const el = await mount(SearchHome);
    expect(el.querySelectorAll('[data-testid="search-recent-row"]')).toHaveLength(2);
    expect(el.textContent).toContain("#cairo");

    el.querySelector<HTMLButtonElement>('[aria-label^="Remove"]')!.click();
    await flush();
    expect(del).toHaveBeenCalledWith("/search/recent/r1/");

    // A recent listing opens the listing, not a text search.
    el.querySelector<HTMLButtonElement>('[data-testid="search-recent-row"] button')!.click();
    await flush();
    expect(router.currentRoute.value.fullPath).toBe("/marketplace/l1");

    el.querySelector<HTMLButtonElement>('[data-testid="search-recent-clear"]')!.click();
    await flush();
    expect(del).toHaveBeenCalledWith("/search/recent/");

    byText(el, "Today")!.click();
    await flush();
    expect(get).toHaveBeenCalledWith("/search/trending/", { params: { window: "day" } });
  });
});

describe("My pending group posts", () => {
  it("shows the member's own waiting posts behind a banner", async () => {
    vi.spyOn(api, "get").mockResolvedValue(page([post("g1", { approval_state: "pending" } as Partial<Post>)]));
    const el = await mount(MyPendingPosts, { group: { id: "grp-1" } });
    expect(api.get).toHaveBeenCalledWith("/posts/groups/grp-1/", { params: { view: "pending" } });
    expect(el.textContent).toContain("You have 1 post pending approval");
    el.querySelector<HTMLButtonElement>('[data-testid="my-pending-toggle"]')!.click();
    await flush();
    expect(el.querySelectorAll('[data-testid="post-card"]')).toHaveLength(1);
  });

  it("renders nothing when nothing waits", async () => {
    vi.spyOn(api, "get").mockResolvedValue(page([]));
    const el = await mount(MyPendingPosts, { group: { id: "grp-1" } });
    expect(el.querySelector('[data-testid="my-pending-posts"]')).toBeNull();
  });
});
