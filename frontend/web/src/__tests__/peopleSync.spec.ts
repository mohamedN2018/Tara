import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, type Component, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import { activeNavName, navItems } from "@/components/layout/navItems";
import PostCard from "@/components/post/PostCard.vue";
import FriendButton from "@/components/social/FriendButton.vue";
import PeopleYouMayKnowStrip from "@/components/social/PeopleYouMayKnowStrip.vue";
import PersonActionsMenu from "@/components/social/PersonActionsMenu.vue";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import { resetRelationshipPrefs } from "@/lib/useRelationshipPrefs";
import { useAuthStore } from "@/stores/auth";
import type { Post } from "@/types";

// Fix B: one people-lists store behind every "..." menu, Block from a post,
// Unfollow in the Friends menu, the in-feed suggestions strip and the
// single-active left rail.

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;

async function flush() {
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
}

async function mount(render: () => ReturnType<typeof h>) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/u/id/:id", name: "profile-by-id", component: Blank },
      { path: "/posts/:id", name: "post", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push("/home");
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({ render });
  app.use(pinia).use(router).use(i18n);
  app.mount(host);
  await flush();
  return host;
}

let pinia: ReturnType<typeof createPinia>;
const q = (el: ParentNode, id: string) => el.querySelector<HTMLElement>(`[data-testid="${id}"]`);
const byText = (el: ParentNode, text: string) =>
  [...el.querySelectorAll<HTMLElement>("button, a")].find((b) => b.textContent?.trim().includes(text));
const post = (extra: Partial<Post> = {}): Post =>
  ({
    id: "p1",
    author_id: "u9",
    author_type: "user",
    type: "text",
    body: "hello",
    audience: "public",
    media_ids: [],
    reaction_count: 0,
    comment_count: 0,
    share_count: 0,
    created_at: "2026-11-03T10:00:00Z",
    ...extra,
  }) as Post;

function mockLists(lists: { favorites?: string[]; muted?: string[]; restricted?: string[]; blocked?: string[] } = {}) {
  return vi.spyOn(api, "get").mockImplementation(async (url: string) => {
    if (url === "/social/favorites/") return { data: { data: { favorites: lists.favorites ?? [] } } };
    if (url === "/social/mutes/") return { data: { data: { muted: lists.muted ?? [] } } };
    if (url === "/social/restricted/") return { data: { data: { restricted: lists.restricted ?? [] } } };
    if (url === "/blocks/") return { data: { data: { blocked: lists.blocked ?? [] } } };
    if (url === "/social/suggestions/") {
      return { data: { data: { results: [{ account_id: "s1", mutual_count: 2, reason: "mutual" }, { account_id: "s2", mutual_count: 0, reason: "follows_you" }] } } };
    }
    return { data: { data: [], page: { next_cursor: null, has_more: false } } };
  });
}

beforeEach(() => {
  pinia = createPinia();
  setActivePinia(pinia);
  localStorage.clear();
  resetRelationshipPrefs();
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

describe("left rail active entry", () => {
  it("lights Home or Feeds, never both", () => {
    expect(activeNavName(navItems, "/home", {})).toBe("home");
    expect(activeNavName(navItems, "/home", { mode: "for_you" })).toBe("feeds");
    expect(activeNavName(navItems, "/home", { mode: "recent" })).toBe("feeds");
    expect(activeNavName(navItems, "/friends", { tab: "requests" })).toBe("friends");
    expect(activeNavName(navItems, "/groups/abc", {})).toBeNull();
  });
});

describe("one shared people-lists store", () => {
  it("a favorite set from a post menu shows at once in the profile menu", async () => {
    mockLists();
    const apiPost = vi.spyOn(api, "post").mockResolvedValue({ data: {} });
    const Both: Component = {
      render: () => h("div", [h(PostCard, { post: post() }), h(PersonActionsMenu, { userId: "u9", name: "Sam" })]),
    };
    const el = await mount(() => h(Both));
    q(el, "post-menu")!.click();
    await flush();
    q(el, "menu-favorite")!.click();
    await flush();
    expect(apiPost).toHaveBeenCalledWith("/social/favorites/u9/");
    q(el, "person-actions")!.click();
    await flush();
    expect(byText(q(el, "person-actions-menu")!, "Remove from Favorites")).toBeTruthy();
  });

  it("blocks the author from the post menu after confirming", async () => {
    mockLists();
    const apiPost = vi.spyOn(api, "post").mockResolvedValue({ data: {} });
    const gone = vi.fn();
    const el = await mount(() => h(PostCard, { post: post(), onAuthorGone: gone }));
    q(el, "post-menu")!.click();
    await flush();
    q(el, "menu-block")!.click();
    await flush();
    expect(apiPost).not.toHaveBeenCalledWith("/blocks/u9/");
    const dialog = document.querySelector('[data-testid="confirm-action"]') as HTMLElement;
    [...dialog.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Block")!.click();
    await flush();
    expect(apiPost).toHaveBeenCalledWith("/blocks/u9/");
    expect(gone).toHaveBeenCalledTimes(1);
  });

  it("hides Block on your own post", async () => {
    mockLists();
    const el = await mount(() => h(PostCard, { post: post({ author_id: "me-1" }) }));
    q(el, "post-menu")!.click();
    await flush();
    expect(q(el, "menu-block")).toBeNull();
  });

  it("shows Favorite and Mute only once their lists load, with the right state", async () => {
    // The lists answer later: the items must not show 'Add'/'Mute' meanwhile.
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const lists = mockLists({ favorites: ["u9"] });
    const answer = lists.getMockImplementation()!;
    lists.mockImplementation(async (url: string, ...rest: unknown[]) => {
      if (url === "/social/favorites/" || url === "/social/mutes/") await gate;
      return answer(url, ...(rest as []));
    });
    const apiPost = vi.spyOn(api, "post").mockResolvedValue({ data: {} });
    const apiDelete = vi.spyOn(api, "delete").mockResolvedValue({ data: {} });
    const el = await mount(() => h(PostCard, { post: post() }));
    q(el, "post-menu")!.click();
    await flush();
    expect(q(el, "menu-favorite")).toBeNull();
    expect(q(el, "menu-mute")).toBeNull();
    expect(q(el, "menu-block")).not.toBeNull(); // its own list already answered
    release();
    await flush();
    expect(q(el, "menu-favorite")!.textContent).toContain("Remove");
    expect(q(el, "menu-mute")!.textContent).not.toContain("Unmute");
    q(el, "menu-favorite")!.click();
    await flush();
    expect(apiDelete).toHaveBeenCalledWith("/social/favorites/u9/");
    expect(apiPost).not.toHaveBeenCalledWith("/social/favorites/u9/");
  });
});

describe("Friends menu: Unfollow", () => {
  it("unfollows a friend without unfriending", async () => {
    mockLists();
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: {} });
    const changed = vi.fn();
    const el = await mount(() =>
      h(FriendButton, { userId: "u3", state: "friends", name: "Sam", following: true, "onFollowChange": changed }),
    );
    (q(el, "friend-button")!.querySelector("button") as HTMLButtonElement).click();
    await flush();
    q(el, "friend-menu-follow")!.click();
    await flush();
    expect(del).toHaveBeenCalledWith("/follows/u3/");
    expect(del).not.toHaveBeenCalledWith("/friends/u3/");
    expect(changed).toHaveBeenCalledWith(false);
  });

  it("offers no follow item when the caller doesn't pass the state", async () => {
    mockLists();
    const el = await mount(() => h(FriendButton, { userId: "u3", state: "friends", name: "Sam" }));
    (q(el, "friend-button")!.querySelector("button") as HTMLButtonElement).click();
    await flush();
    expect(q(el, "friend-menu-follow")).toBeNull();
  });
});

describe("People you may know strip", () => {
  it("shows real suggestions, removes one with Undo", async () => {
    mockLists();
    vi.spyOn(api, "post").mockResolvedValue({ data: {} });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: {} });
    const el = await mount(() => h(PeopleYouMayKnowStrip));
    expect(el.querySelectorAll('[data-testid="pymk-card"]')).toHaveLength(2);
    q(el, "pymk-card-dismiss")!.click();
    await flush();
    expect(el.querySelectorAll('[data-testid="pymk-card"]')).toHaveLength(1);
    q(el, "pymk-strip-undo")!.click();
    await flush();
    expect(del).toHaveBeenCalledWith("/social/suggestions/s1/dismiss/", expect.anything());
    expect(el.querySelectorAll('[data-testid="pymk-card"]')).toHaveLength(2);
  });

  it("renders nothing when graph has no suggestions", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: { results: [] } } });
    const el = await mount(() => h(PeopleYouMayKnowStrip));
    expect(q(el, "pymk-strip")).toBeNull();
  });
});
