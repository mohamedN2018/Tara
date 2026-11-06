import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type Component, createApp, defineComponent, h, type App } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import CommentInput from "@/components/post/CommentInput.vue";
import SponsoredCard from "@/components/post/SponsoredCard.vue";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import { insertAt } from "@/lib/emojis";
import { hiddenAds } from "@/lib/hiddenAds";
import { realtime } from "@/lib/ws";
import { feedService, type FeedPeek, type FeedResponse, type HydratedFeedPage } from "@/services/feed";
import { postService } from "@/services/post";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";
import type { Post } from "@/types";
import HomeView from "@/views/HomeView.vue";

// The shell and the composer have their own specs; Home is tested on its own.
vi.mock("@/components/layout/AppShell.vue", () => ({
  default: defineComponent({ setup: (_, { slots }) => () => h("div", slots.default?.()) }),
}));
vi.mock("@/components/post/CreatePostCard.vue", () => ({ default: defineComponent({ render: () => null }) }));
vi.mock("@/components/auth/CompleteProfileCard.vue", () => ({ default: defineComponent({ render: () => null }) }));

const post = (id: string, author = `author-${id}`): Post => ({
  id,
  author_id: author,
  author_type: "user",
  type: "text",
  body: `body ${id}`,
  audience: "public",
  media_ids: [],
  reaction_count: 0,
  comment_count: 0,
  share_count: 0,
  created_at: "2026-11-03T10:00:00Z",
});
const hydrated = (posts: Post[], modeApplied = true): HydratedFeedPage => ({
  posts,
  reasons: {},
  sponsored: [],
  nextCursor: null,
  hasMore: false,
  modeApplied,
});

const Blank = defineComponent({ render: () => null });
// A first page (08 §7.4, §7.6; R3 06 §4.2): its entry hint (`load` for the page load's
// first, `nav` after) and the tab's sid, drawn from its snapshots first.
const FIRST = expect.objectContaining({ entry: expect.stringMatching(/^(load|nav)$/), snapshots: true });
const NAV = expect.objectContaining({ entry: "nav", snapshots: true });
let app: App | null = null;
let host: HTMLElement | null = null;

async function flush() {
  for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0));
}

async function mount(component: Component, props: Record<string, unknown> = {}, path = "/home") {
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
  app = createApp(component, props);
  app.use(createPiniaOnce()).use(router).use(i18n);
  app.mount(host);
  await flush();
  return host;
}

let pinia: ReturnType<typeof createPinia>;
const createPiniaOnce = () => pinia;

beforeEach(() => {
  pinia = createPinia();
  setActivePinia(pinia);
  localStorage.clear();
  sessionStorage.clear();
  hiddenAds.value = new Set();
  i18n.global.locale.value = "en";
  const auth = useAuthStore();
  auth.account = { id: "me-1", email: "me@example.com" } as never;
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.spyOn(api, "get").mockResolvedValue({ data: { data: [], page: { next_cursor: null, has_more: false } } });
  vi.spyOn(api, "post").mockResolvedValue({ data: { data: [] } });
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.unstubAllGlobals();
});

const order = (el: HTMLElement) =>
  [...el.querySelectorAll<HTMLElement>("[data-feed-item]")].map((n) => {
    const id = n.dataset.feedItem!;
    return n.querySelector('[data-testid="hide-feedback"]') ? `hidden:${id}` : id;
  });
const button = (el: ParentNode, name: string) =>
  [...el.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.getAttribute("aria-label") === name || b.textContent?.trim() === name,
  );
const visible = (el: HTMLElement | null) => !!el && el.style.display !== "none";

describe("hiding a post from Home", () => {
  it("swaps the card in place, sends reasons, and Undo restores it at the same position", async () => {
    vi.spyOn(feedService, "page").mockResolvedValue(hydrated([post("a"), post("b"), post("c")]));
    const hide = vi.spyOn(feedService, "hide").mockResolvedValue();
    const unhide = vi.spyOn(feedService, "unhide").mockResolvedValue();
    const el = await mount(HomeView);
    expect(order(el)).toEqual(["a", "b", "c"]);

    const second = el.querySelector<HTMLElement>('[data-feed-item="b"]')!;
    second.querySelector<HTMLButtonElement>('[data-testid="hide-post"]')!.click();
    await flush();
    expect(hide).toHaveBeenCalledWith("b", "not_interested");
    expect(order(el)).toEqual(["a", "hidden:b", "c"]);
    expect(visible(second.querySelector("article"))).toBe(false);
    expect(second.textContent).toContain("Post hidden");

    button(second, "Spam or scam")!.click();
    await flush();
    expect(hide).toHaveBeenLastCalledWith("b", "spam");
    expect(button(second, "Spam or scam")!.getAttribute("aria-pressed")).toBe("true");

    button(second, "Undo")!.click();
    await flush();
    expect(unhide).toHaveBeenCalledWith("b");
    expect(order(el)).toEqual(["a", "b", "c"]);
    expect(visible(second.querySelector("article"))).toBe(true);
  });

  it("offers Hide post in the menu too, and never on the viewer's own post", async () => {
    vi.spyOn(feedService, "page").mockResolvedValue(hydrated([post("mine", "me-1"), post("x")]));
    const hide = vi.spyOn(feedService, "hide").mockResolvedValue();
    const el = await mount(HomeView);
    expect(el.querySelector('[data-feed-item="mine"] [data-testid="hide-post"]')).toBeNull();

    const other = el.querySelector<HTMLElement>('[data-feed-item="x"]')!;
    button(other, "More")!.click();
    await flush();
    button(other, "Hide post")!.click();
    await flush();
    expect(hide).toHaveBeenCalledWith("x", "not_interested");
    expect(order(el)).toEqual(["mine", "hidden:x"]);
  });

  it("puts the card back when the server refuses the hide", async () => {
    vi.spyOn(feedService, "page").mockResolvedValue(hydrated([post("a")]));
    vi.spyOn(feedService, "hide").mockRejectedValue(new Error("404"));
    const el = await mount(HomeView);
    el.querySelector<HTMLButtonElement>('[data-testid="hide-post"]')!.click();
    await flush();
    expect(order(el)).toEqual(["a"]);
  });

  it("snoozes the author: their other cards leave the list until Undo", async () => {
    vi.spyOn(feedService, "page").mockResolvedValue(hydrated([post("a", "sam"), post("b"), post("c", "sam")]));
    vi.spyOn(feedService, "hide").mockResolvedValue();
    const snooze = vi.spyOn(feedService, "snooze").mockResolvedValue();
    const unsnooze = vi.spyOn(feedService, "unsnooze").mockResolvedValue();
    vi.spyOn(feedService, "unhide").mockResolvedValue();
    const el = await mount(HomeView);
    const first = el.querySelector<HTMLElement>('[data-feed-item="a"]')!;
    first.querySelector<HTMLButtonElement>('[data-testid="hide-post"]')!.click();
    await flush();
    [...first.querySelectorAll("button")].find((b) => b.textContent?.includes("for 30 days"))!.click();
    await flush();
    expect(snooze).toHaveBeenCalledWith("sam");
    expect(visible(el.querySelector('[data-feed-item="c"]'))).toBe(false);
    expect(visible(first)).toBe(true);

    button(first, "Undo")!.click(); // the hide's Undo also lifts the snooze
    await flush();
    expect(unsnooze).toHaveBeenCalledWith("sam");
    expect(visible(el.querySelector('[data-feed-item="c"]'))).toBe(true);
  });

  it("keeps the card and the snooze when Undo cannot lift the snooze", async () => {
    vi.spyOn(feedService, "page").mockResolvedValue(hydrated([post("a", "sam"), post("c", "sam")]));
    vi.spyOn(feedService, "hide").mockResolvedValue();
    vi.spyOn(feedService, "snooze").mockResolvedValue();
    const unhide = vi.spyOn(feedService, "unhide").mockResolvedValue();
    const unsnooze = vi.spyOn(feedService, "unsnooze").mockRejectedValueOnce(new Error("503")).mockResolvedValue();
    const el = await mount(HomeView);
    const first = el.querySelector<HTMLElement>('[data-feed-item="a"]')!;
    first.querySelector<HTMLButtonElement>('[data-testid="hide-post"]')!.click();
    await flush();
    [...first.querySelectorAll("button")].find((b) => b.textContent?.includes("for 30 days"))!.click();
    await flush();

    button(first, "Undo")!.click();
    await flush();
    expect(unhide).toHaveBeenCalledWith("a");
    expect(unsnooze).toHaveBeenCalledTimes(1);
    // The server still snoozes sam: the card (with its Undo) stays, sam's posts stay out
    // (unmounted, 08 §7.7).
    expect(order(el)).toEqual(["hidden:a"]);
    expect(visible(el.querySelector('[data-feed-item="c"]'))).toBe(false);
    expect(useToastStore().items.map((i) => i.icon)).toEqual(["error"]);
    expect(button(first, "Undo")!.disabled).toBe(false);

    button(first, "Undo")!.click(); // a retry goes through
    await flush();
    expect(unsnooze).toHaveBeenCalledTimes(2);
    expect(order(el)).toEqual(["a", "c"]);
    expect(visible(el.querySelector('[data-feed-item="c"]'))).toBe(true);
  });
});

describe("new posts pill", () => {
  const feedItem = (id: string, author = `author-${id}`) => ({
    id: `fi-${id}`,
    post_id: id,
    author_id: author,
    reason: "friend",
    snapshot: {},
    post_created_at: "2026-11-03T10:00:00Z",
  });
  const peekOf = (...items: ReturnType<typeof feedItem>[]): FeedPeek => ({ data: items, mode: "recent", peek: true, new_count: items.length });
  function captureFrames() {
    const handlers = new Map<string, Array<(f: Record<string, unknown>) => void>>();
    vi.spyOn(realtime, "on").mockImplementation((type, handler) => {
      handlers.set(type, [...(handlers.get(type) ?? []), handler as never]);
      return () => undefined;
    });
    return async (type: string, frame: Record<string, unknown> = {}) => {
      handlers.get(type)?.forEach((h) => h({ event: type, ...frame }));
      await flush();
    };
  }
  const pill = (el: HTMLElement) => el.querySelector<HTMLButtonElement>('[data-testid="new-posts-pill"] button') ?? undefined;

  it("offers only pushed posts the current mode's feed contains", async () => {
    localStorage.setItem("tara.feedMode", "favorites");
    const play = captureFrames();
    vi.spyOn(feedService, "page").mockResolvedValue({ ...hydrated([post("a")]), asOf: "2026-11-05T10:00:00+00:00" });
    // The favorites feed has the favorite's post, not the other friend's.
    const home = vi.spyOn(feedService, "home");
    const peek = vi.spyOn(feedService, "peek").mockResolvedValue(peekOf(feedItem("fav"), feedItem("a")));
    vi.spyOn(postService, "batch").mockImplementation(async (ids) => ids.map((id) => post(id)));
    const el = await mount(HomeView);

    await play("feed.item.added", { post_id: "other" });
    // A peek, never a first page: the ranking session and the ads stay as they are (WP 4.7).
    expect(peek).toHaveBeenLastCalledWith("favorites", "2026-11-05T10:00:00+00:00");
    expect(home).not.toHaveBeenCalled();
    expect(pill(el)).toBeUndefined();

    await play("feed.item.added", { post_id: "fav" });
    expect(pill(el)?.textContent).toContain("1 new post");
    vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    pill(el)!.click();
    await flush();
    expect(order(el)).toEqual(["fav", "a"]);
  });

  it("catches up with the current mode after a reconnect", async () => {
    localStorage.setItem("tara.feedMode", "following");
    const play = captureFrames();
    vi.spyOn(feedService, "page").mockResolvedValue({ ...hydrated([post("a")]), asOf: "2026-11-05T10:00:00+00:00" });
    const peek = vi.spyOn(feedService, "peek").mockResolvedValue(peekOf(feedItem("n1"), feedItem("a")));
    vi.spyOn(postService, "batch").mockImplementation(async (ids) => ids.map((id) => post(id)));
    const el = await mount(HomeView);
    await play("_reconnected");
    expect(peek).toHaveBeenCalledWith("following", "2026-11-05T10:00:00+00:00");
    expect(pill(el)?.textContent).toContain("1 new post");
  });

  it("drops posts found for the old mode when the mode changes", async () => {
    const play = captureFrames();
    vi.spyOn(feedService, "page").mockResolvedValue(hydrated([post("a")]));
    vi.spyOn(feedService, "peek").mockResolvedValue(peekOf(feedItem("n1")));
    vi.spyOn(feedService, "setDefaultMode").mockResolvedValue({ default_mode: "favorites", version: 1 });
    vi.spyOn(postService, "batch").mockImplementation(async (ids) => ids.map((id) => post(id)));
    const el = await mount(HomeView);
    await play("feed.item.added", { post_id: "n1" });
    expect(pill(el)).toBeDefined();
    button(el.querySelector<HTMLElement>('[data-testid="feed-modes"]')!, "Favorites")!.click();
    await flush();
    expect(pill(el)).toBeUndefined();
  });

  it("skips an author snoozed here", async () => {
    const play = captureFrames();
    vi.spyOn(feedService, "page").mockResolvedValue(hydrated([post("a", "sam")]));
    vi.spyOn(feedService, "hide").mockResolvedValue();
    vi.spyOn(feedService, "snooze").mockResolvedValue();
    vi.spyOn(feedService, "peek").mockResolvedValue(peekOf(feedItem("n1", "sam")));
    vi.spyOn(postService, "batch").mockImplementation(async (ids) => ids.map((id) => post(id, "sam")));
    const el = await mount(HomeView);
    const first = el.querySelector<HTMLElement>('[data-feed-item="a"]')!;
    first.querySelector<HTMLButtonElement>('[data-testid="hide-post"]')!.click();
    await flush();
    [...first.querySelectorAll("button")].find((b) => b.textContent?.includes("for 30 days"))!.click();
    await flush();
    await play("feed.item.added", { post_id: "n1" });
    expect(pill(el)).toBeUndefined();
  });
});

describe("feed modes", () => {
  it("stay hidden while the server ignores `mode`", async () => {
    const page = vi.spyOn(feedService, "page").mockResolvedValue(hydrated([post("a")], false));
    const el = await mount(HomeView);
    // No `?mode=` and nothing stored: the server picks (its remembered mode, else Latest).
    expect(page).toHaveBeenCalledWith(undefined, undefined, undefined, FIRST);
    expect(el.querySelector('[data-testid="feed-modes"]')).toBeNull();
  });

  it("switch the feed and remember the choice", async () => {
    const page = vi
      .spyOn(feedService, "page")
      .mockResolvedValueOnce({ ...hydrated([post("a")]), mode: "recent" })
      .mockResolvedValueOnce(hydrated([post("z")]));
    const remember = vi.spyOn(feedService, "setDefaultMode").mockResolvedValue({ default_mode: "for_you", version: 1 });
    const el = await mount(HomeView);
    const modes = el.querySelector<HTMLElement>('[data-testid="feed-modes"]')!;
    expect([...modes.querySelectorAll("button[aria-pressed]")].map((b) => b.textContent?.trim())).toEqual([
      "For you",
      "Latest",
      "Favorites",
      "Following",
      "Friends",
    ]);
    expect(button(modes, "Latest")!.getAttribute("aria-pressed")).toBe("true");

    button(modes, "For you")!.click();
    await flush();
    expect(page).toHaveBeenLastCalledWith(undefined, "for_you", undefined, NAV);
    expect(order(el)).toEqual(["z"]);
    expect(button(modes, "For you")!.getAttribute("aria-pressed")).toBe("true");
    expect(button(modes, "Latest")!.getAttribute("aria-pressed")).toBe("false");
    expect(localStorage.getItem("tara.feedMode")).toBe("for_you");
    // Remembered for the account, so a new browser opens on it (WP 4.6).
    expect(remember).toHaveBeenCalledWith("for_you");
  });

  it("open on the mode the server remembers, sending this browser's copy only as a hint", async () => {
    localStorage.setItem("tara.feedMode", "favorites");
    const page = vi.spyOn(feedService, "page").mockResolvedValue({ ...hydrated([post("a")]), mode: "friends" });
    const el = await mount(HomeView);
    expect(page).toHaveBeenCalledWith(undefined, undefined, "favorites", FIRST);
    const modes = el.querySelector<HTMLElement>('[data-testid="feed-modes"]')!;
    expect(button(modes, "Friends")!.getAttribute("aria-pressed")).toBe("true");
    expect(localStorage.getItem("tara.feedMode")).toBe("friends");
  });

  it("a `?mode=` link wins over the remembered mode", async () => {
    const page = vi.spyOn(feedService, "page").mockResolvedValue({ ...hydrated([post("a")]), mode: "following" });
    await mount(HomeView, {}, "/home?mode=following");
    expect(page).toHaveBeenCalledWith(undefined, "following", undefined, FIRST);
  });

  it("feedService remembers the mode and asks the server's choice with a hint", async () => {
    const patch = vi.spyOn(api, "patch").mockResolvedValue({ data: { data: { default_mode: "friends", version: 2 } } });
    expect(await feedService.setDefaultMode("friends")).toEqual({ default_mode: "friends", version: 2 });
    expect(patch).toHaveBeenCalledWith("/feed/preferences/", { default_mode: "friends" });
    const get = vi.spyOn(api, "get").mockResolvedValueOnce({
      data: { data: [], sponsored: null, page: { next_cursor: null, has_more: false }, mode: "friends", meta: { ad_slots: [4], as_of: "t0" } },
    });
    const page = await feedService.page(undefined, undefined, "recent");
    expect(get).toHaveBeenLastCalledWith("/feed/", { params: { cursor: undefined, mode_hint: "recent" } });
    expect([page.mode, page.modeApplied, page.adSlots, page.asOf]).toEqual(["friends", true, [4], "t0"]);
  });

  it("feedService peeks without a cursor and with the first page's time", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValueOnce({ data: { data: [], mode: "recent", peek: true, new_count: 0 } });
    await feedService.peek("recent", "t0");
    expect(get).toHaveBeenLastCalledWith("/feed/", { params: { mode: "recent", peek: 1, since: "t0" } });
  });

  it("feedService sends the mode and trusts it only when echoed", async () => {
    const envelope = (mode?: string): { data: FeedResponse } => ({
      data: { data: [], sponsored: null, page: { next_cursor: null, has_more: false }, ...(mode ? { mode } : {}) },
    });
    const get = vi.spyOn(api, "get").mockResolvedValueOnce(envelope("favorites")).mockResolvedValueOnce(envelope());
    expect((await feedService.page(undefined, "favorites")).modeApplied).toBe(true);
    expect(get).toHaveBeenLastCalledWith("/feed/", { params: { cursor: undefined, mode: "favorites" } });
    expect((await feedService.page(undefined, "favorites")).modeApplied).toBe(false);
  });
});

describe("feed feedback endpoints", () => {
  it("match the 2A contract", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ status: 201, data: {} });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ status: 204 });
    await feedService.hide("p1", "dislike_creator");
    expect(postSpy).toHaveBeenCalledWith("/feed/hide/", { post_id: "p1", reason: "dislike_creator" });
    await feedService.unhide("p1");
    expect(del).toHaveBeenCalledWith("/feed/hide/p1/");
    await feedService.snooze("u1");
    expect(postSpy).toHaveBeenCalledWith("/feed/snooze/", { author_id: "u1" });
    await feedService.unsnooze("u1");
    expect(del).toHaveBeenCalledWith("/feed/snooze/u1/");
  });
});

describe("comment emoji picker", () => {
  it("inserts at the caret, replacing a selection", () => {
    expect(insertAt("abcd", "😀", 2)).toEqual({ value: "ab😀cd", caret: 4 });
    expect(insertAt("abcd", "🔥", 1, 3)).toEqual({ value: "a🔥d", caret: 3 });
    expect(insertAt("ab", "✨", 99)).toEqual({ value: "ab✨", caret: 3 });
  });

  it("puts the picked emoji where the cursor is in the comment box", async () => {
    const el = await mount(CommentInput);
    const input = el.querySelector("input")!;
    input.value = "hello world";
    input.dispatchEvent(new Event("input"));
    await flush();
    input.focus();
    input.setSelectionRange(5, 5);
    button(el, "Insert emoji")!.click();
    await flush();
    el.querySelector<HTMLButtonElement>('[data-testid="emoji-picker"] button[aria-label="🔥"]')!.click();
    await flush();
    expect(input.value).toBe("hello🔥 world");
    expect(input.selectionStart).toBe(5 + "🔥".length);
    expect(el.querySelector('[data-testid="emoji-picker"]')).toBeNull();
  });
});

describe("sponsored card", () => {
  const ad = { creative_id: "cr1", headline: "Fresh bread", token: "tok", sponsored: true };

  it("hides the ad for the session, and Undo brings it back", async () => {
    const el = await mount(SponsoredCard, { ad });
    button(el, "Hide ad")!.click();
    await flush();
    expect(el.querySelector('[data-testid="sponsored"]')).toBeNull();
    expect(el.textContent).toContain("Ad hidden");
    expect(JSON.parse(sessionStorage.getItem("tara.hiddenAds")!)).toEqual(["cr1"]);

    button(el, "Undo")!.click();
    await flush();
    expect(el.querySelector('[data-testid="sponsored"]')?.textContent).toContain("Fresh bread");
    expect(JSON.parse(sessionStorage.getItem("tara.hiddenAds")!)).toEqual([]);
  });
});

describe("ad slots from the server's config (WP 4.9)", () => {
  const ad = (id: string) => ({ creative_id: id, headline: `Ad ${id}`, token: `tok-${id}`, sponsored: true });
  const ids = (n: number) => Array.from({ length: n }, (_, i) => `p${i}`);
  // The list as rendered: post ids, and `ad:<id>` where a sponsored card sits.
  const layout = (el: HTMLElement) =>
    [...el.querySelectorAll<HTMLElement>("[data-feed-item], [data-testid='sponsored']")].map((n) =>
      n.dataset.feedItem ?? `ad:${n.textContent?.includes("Ad a1") ? "a1" : n.textContent?.includes("Ad a2") ? "a2" : "?"}`,
    );
  const organic = (el: HTMLElement) => order(el);
  async function rendered(page: Partial<HydratedFeedPage>) {
    vi.spyOn(feedService, "page").mockResolvedValue({ ...hydrated(ids(20).map((i) => post(i))), ...page });
    return mount(HomeView);
  }

  it("puts the one default ad after the fifth post, as before", async () => {
    const el = await rendered({ sponsored: [ad("a1")], adSlots: [4] });
    const seen = layout(el);
    expect(seen.indexOf("ad:a1")).toBe(5);
    expect(seen.filter((s) => s.startsWith("ad:"))).toEqual(["ad:a1"]);
  });

  it("falls back to slot 4 when the server sends no slots", async () => {
    const el = await rendered({ sponsored: [ad("a1")] });
    expect(layout(el).indexOf("ad:a1")).toBe(5);
  });

  it("shows a second ad only where a second slot is configured", async () => {
    const el = await rendered({ sponsored: [ad("a1"), ad("a2")], adSlots: [4, 14] });
    const seen = layout(el);
    expect(seen.indexOf("ad:a1")).toBe(5);
    expect(seen.indexOf("ad:a2")).toBe(16);
  });

  it("never shows an ad beyond the ads served, nor moves an organic post", async () => {
    const withAds = await rendered({ sponsored: [ad("a1")], adSlots: [4, 14] });
    const on = organic(withAds);
    expect(layout(withAds).filter((s) => s.startsWith("ad:"))).toEqual(["ad:a1"]);
    app?.unmount();
    host?.remove();
    const without = await rendered({ sponsored: [], adSlots: [4, 14] });
    expect(organic(without)).toEqual(on);
    expect(layout(without).some((s) => s.startsWith("ad:"))).toBe(false);
  });
});

describe("inline comments on a card", () => {
  const comment = (id: string) => ({
    id,
    post_id: "p",
    author_id: `c-${id}`,
    parent_id: null,
    body: `said ${id}`,
    created_at: "2026-11-03T10:00:00Z",
  });

  it("preview at most two top comments, with View more comments and a visible box", async () => {
    const withTop = { ...post("p"), comment_count: 5, top_comments: [comment("1"), comment("2"), comment("3")] };
    vi.spyOn(feedService, "page").mockResolvedValue(hydrated([withTop as Post]));
    const el = await mount(HomeView);
    const preview = el.querySelector<HTMLElement>('[data-testid="comment-preview"]')!;
    expect(preview.querySelectorAll("[data-comment-id]")).toHaveLength(2);
    expect(preview.textContent).toContain("View more comments");
    expect(preview.querySelector('input[aria-label="Write a comment…"]')).not.toBeNull();
  });

  it("keep the preview in step with edits and deletes made in the full list", async () => {
    const mine = (id: string) => ({ ...comment(id), author_id: "me-1" });
    const withTop = { ...post("p"), comment_count: 3, top_comments: [mine("1"), mine("2")] };
    vi.spyOn(feedService, "page").mockResolvedValue(hydrated([withTop as Post]));
    vi.spyOn(api, "get").mockImplementation(async (url: string) =>
      url === "/posts/p/comments/"
        ? { data: { data: [mine("1"), mine("2"), mine("3")], page: { next_cursor: null, has_more: false } } }
        : { data: { data: [], page: { next_cursor: null, has_more: false } } },
    );
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: { data: { comment_count: 2 } } });
    vi.spyOn(api, "patch").mockResolvedValue({ data: { data: { ...mine("2"), body: "changed 2" } } });
    const el = await mount(HomeView);
    const card = el.querySelector<HTMLElement>('[data-feed-item="p"]')!;
    button(card, "View more comments")!.click();
    await flush();
    expect(card.querySelector('[data-testid="comment-preview"]')).toBeNull();

    const inList = (id: string) => card.querySelector<HTMLElement>(`[data-comment-id="${id}"]`)!;
    button(inList("1"), "Comment options")!.click();
    await flush();
    button(inList("1"), "Delete")!.click();
    await flush();
    expect(del).toHaveBeenCalledWith("/comments/1/");
    button(inList("2"), "Comment options")!.click();
    await flush();
    button(inList("2"), "Edit")!.click();
    await flush();
    const box = inList("2").querySelector("textarea")!;
    box.value = "changed 2";
    box.dispatchEvent(new Event("input"));
    await flush();
    button(inList("2"), "Save")!.click();
    await flush();

    button(card, "Comment")!.click(); // collapse the full list
    await flush();
    const preview = card.querySelector<HTMLElement>('[data-testid="comment-preview"]')!;
    expect([...preview.querySelectorAll<HTMLElement>("[data-comment-id]")].map((n) => n.dataset.commentId)).toEqual(["2"]);
    expect(preview.textContent).toContain("changed 2");
    expect(preview.textContent).not.toContain("said 1");
  });

  it("drop a preview comment that is already gone on the server", async () => {
    const withTop = { ...post("p"), comment_count: 2, top_comments: [{ ...comment("1"), author_id: "me-1" }, comment("2")] };
    vi.spyOn(feedService, "page").mockResolvedValue(hydrated([withTop as Post]));
    vi.spyOn(api, "delete").mockRejectedValue({ response: { status: 404, data: {} } });
    const el = await mount(HomeView);
    const preview = el.querySelector<HTMLElement>('[data-testid="comment-preview"]')!;
    const first = preview.querySelector<HTMLElement>('[data-comment-id="1"]')!;
    button(first, "Comment options")!.click();
    await flush();
    button(first, "Delete")!.click();
    await flush();
    expect([...preview.querySelectorAll<HTMLElement>("[data-comment-id]")].map((n) => n.dataset.commentId)).toEqual(["2"]);
    expect(useToastStore().items).toEqual([]);
  });

  it("show only the comment box when the server sends no top_comments", async () => {
    vi.spyOn(feedService, "page").mockResolvedValue(hydrated([post("p")]));
    const el = await mount(HomeView);
    const preview = el.querySelector<HTMLElement>('[data-testid="comment-preview"]')!;
    expect(preview.querySelectorAll("[data-comment-id]")).toHaveLength(0);
    expect(preview.textContent).not.toContain("View more comments");
    expect(preview.querySelector("input")).not.toBeNull();
  });

  it("adds a comment written in the box to the card", async () => {
    vi.spyOn(feedService, "page").mockResolvedValue(hydrated([post("p")]));
    const add = vi.spyOn(api, "post").mockResolvedValue({ data: { data: comment("new") } });
    const el = await mount(HomeView);
    const input = el.querySelector<HTMLInputElement>('[data-testid="comment-preview"] input')!;
    input.value = "hi there";
    input.dispatchEvent(new Event("input"));
    await flush();
    el.querySelector<HTMLFormElement>('[data-testid="comment-preview"] form')!.requestSubmit();
    await flush();
    expect(add).toHaveBeenCalledWith("/posts/p/comments/", { body: "hi there" });
    expect(el.querySelector('[data-comment-id="new"]')?.textContent).toContain("said new");
  });
});
