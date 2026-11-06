import { createPinia, type Pinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import Toaster from "@/components/common/Toaster.vue";
import PostCard from "@/components/post/PostCard.vue";
import { i18n, setLocale } from "@/i18n";
import { api } from "@/lib/api";
import { noteServed, resetSignals } from "@/lib/signals";
import { resetRelationshipPrefs } from "@/lib/useRelationshipPrefs";
import type { FeedReason, ItemTopic } from "@/services/feed";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import type { Post } from "@/types";

// Tara Intelligence R4 (04 WP 7.3, 07 WP 7.5-B2): the post menu's feedback actions,
// each with the 06 §10 confirmation and an Undo that deletes that exact row.

const Blank = defineComponent({ render: () => null });
const POST_ID = "00000000-0000-4000-8000-000000000101";
const AUTHOR = "00000000-0000-4000-8000-000000000202";
let app: App | null = null;
let host: HTMLElement | null = null;
let events: { gone: string[]; back: string[] };
let pinia: Pinia;

async function flush() {
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
}

const post = (): Post =>
  ({
    id: POST_ID,
    author_id: AUTHOR,
    author_type: "user",
    type: "text",
    body: "hello",
    audience: "public",
    media_ids: [],
    reaction_count: 0,
    comment_count: 0,
    share_count: 0,
    created_at: "2026-11-03T10:00:00Z",
  }) as Post;

const TOPICS: ItemTopic[] = [
  { slug: "cooking", label_ar: "طبخ", label_en: "Cooking" },
  { slug: "tech", label_ar: "تكنولوجيا", label_en: "Technology" },
];

async function mount(feedReason: FeedReason | null, feedTopics: ItemTopic[] = TOPICS) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/u/id/:id", name: "profile-by-id", component: Blank },
      { path: "/posts/:id", name: "post", component: Blank },
      { path: "/home", name: "home", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push("/home");
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({
    render: () => [
      h(PostCard, {
        post: post(),
        feedReason,
        feedTopics,
        authorName: "Mona",
        onFeedbackGone: (p: Post) => events.gone.push(p.id),
        onFeedbackBack: (p: Post) => events.back.push(p.id),
      }),
      h(Toaster),
    ],
  });
  app.use(pinia).use(router).use(i18n);
  app.mount(host);
  await flush();
  return host;
}

const q = (el: ParentNode, id: string) => el.querySelector<HTMLElement>(`[data-testid="${id}"]`);
async function openMenu(el: HTMLElement) {
  q(el, "post-menu")!.click();
  await flush();
}

beforeEach(() => {
  pinia = createPinia();
  setActivePinia(pinia);
  localStorage.clear();
  resetRelationshipPrefs();
  resetSignals();
  setLocale("en");
  events = { gone: [], back: [] };
  useAuthStore().account = { id: "00000000-0000-4000-8000-000000000999", email: "me@example.com" } as never;
  useDirectoryStore();
  vi.spyOn(api, "get").mockResolvedValue({ data: { data: [], page: { next_cursor: null, has_more: false } } });
  vi.spyOn(api, "post").mockResolvedValue({ data: { data: [] } });
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  document.body.innerHTML = "";
  app = null;
  host = null;
  vi.restoreAllMocks();
  setLocale("en");
});

describe("post menu feedback (R4)", () => {
  it("offers Interested, Not interested, More, Less and Mute topic on a feed item", async () => {
    const el = await mount("friend");
    await openMenu(el);
    for (const id of ["menu-interested", "menu-not-interested", "menu-more-like", "menu-less-like"]) expect(q(el, id)).not.toBeNull();
    const topics = q(el, "menu-mute-topics")!;
    expect([...topics.querySelectorAll("button")].map((b) => b.textContent?.trim())).toEqual(["Mute “Cooking”", "Mute “Technology”"]);
    // Alongside the existing items, which stay.
    expect(q(el, "menu-why")).not.toBeNull();
    // A post from the viewer's circle: "Don't recommend" is for suggestions only.
    expect(q(el, "menu-hide-creator")).toBeNull();
  });

  it("hides Mute topic when the server named no topics, and everything off the feed", async () => {
    let el = await mount("follow", []);
    await openMenu(el);
    expect(q(el, "menu-mute-topics")).toBeNull();
    expect(q(el, "menu-interested")).not.toBeNull();
    app?.unmount();
    host?.remove();
    el = await mount(null);
    await openMenu(el);
    expect(q(el, "menu-feedback")).toBeNull();
  });

  it("never offers feedback on the viewer's own post", async () => {
    useAuthStore().account = { id: AUTHOR, email: "a@example.com" } as never;
    const el = await mount("self");
    await openMenu(el);
    expect(q(el, "menu-feedback")).toBeNull();
  });

  it("sends the action with the serve token, shows the 06 copy, and Undo deletes that row", async () => {
    noteServed(`post:${POST_ID}`, { st: "st-9", surface: "home" });
    const post_ = vi.spyOn(api, "post").mockResolvedValue({ data: { data: { id: "fb-1", action: "interested" } } });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: null });
    const el = await mount("friend");
    await openMenu(el);
    q(el, "menu-interested")!.click();
    await flush();
    expect(post_).toHaveBeenCalledWith("/feed/feedback/", { item_type: "post", item_id: POST_ID, action: "interested", surface: "home", st: "st-9" });
    expect(document.body.textContent).toContain("We'll show you more posts like this.");
    q(document.body, "feedback-undo")!.click();
    await flush();
    expect(del).toHaveBeenCalledWith("/feed/feedback/fb-1/");
    expect(events.gone).toEqual([]);
  });

  it("Not interested removes the card at once and Undo brings it back", async () => {
    vi.spyOn(api, "post").mockResolvedValue({ data: { data: { id: "fb-2", action: "not_interested" } } });
    vi.spyOn(api, "delete").mockResolvedValue({ data: null });
    const el = await mount("rec_popular");
    await openMenu(el);
    q(el, "menu-not-interested")!.click();
    await flush();
    expect(events.gone).toEqual([POST_ID]);
    expect(document.body.textContent).toContain("We'll show fewer posts like this.");
    q(document.body, "feedback-undo")!.click();
    await flush();
    expect(events.back).toEqual([POST_ID]);
  });

  it("restores the card when the server refuses", async () => {
    vi.spyOn(api, "post").mockRejectedValue({ response: { status: 400, data: { error: { code: "validation_error" } } } });
    const el = await mount("rec_fresh");
    await openMenu(el);
    q(el, "menu-not-interested")!.click();
    await flush();
    expect(events.gone).toEqual([POST_ID]);
    expect(events.back).toEqual([POST_ID]);
  });

  it("mutes one topic with its slug and the topic copy", async () => {
    const post_ = vi.spyOn(api, "post").mockResolvedValue({ data: { data: { id: "fb-3", action: "mute_topic" } } });
    const el = await mount("friend");
    await openMenu(el);
    q(el, "menu-mute-topic-tech")!.click();
    await flush();
    const call = post_.mock.calls.find((c) => c[0] === "/feed/feedback/")!;
    expect(call[1]).toMatchObject({ action: "mute_topic", topic: "tech" });
    expect(document.body.textContent).toContain("We won't recommend Technology; your connections' posts about it will rank lower.");
  });

  it("offers Don't recommend on a suggestion, with the copy that keeps follows", async () => {
    vi.spyOn(api, "post").mockResolvedValue({ data: { data: { id: "fb-4", action: "hide_creator" } } });
    const el = await mount("rec_adjacent_topic");
    await openMenu(el);
    const item = q(el, "menu-hide-creator")!;
    expect(item.textContent).toContain("Don't recommend Mona");
    item.click();
    await flush();
    expect(events.gone).toEqual([POST_ID]);
    expect(document.body.textContent).toContain("We won't recommend Mona. If you follow them, you'll still see their posts.");
  });

  it("speaks Arabic, right to left, with the 06 §10 copy", async () => {
    setLocale("ar");
    vi.spyOn(api, "post").mockResolvedValue({ data: { data: { id: "fb-5", action: "not_interested" } } });
    const el = await mount("rec_popular");
    expect(document.documentElement.dir).toBe("rtl");
    await openMenu(el);
    expect(q(el, "menu-not-interested")!.textContent).toContain("مش مهتم");
    expect(q(el, "menu-mute-topic-cooking")!.textContent).toContain("«طبخ»");
    expect(q(el, "menu-mute-topic-cooking")!.className).toContain("text-start");
    q(el, "menu-not-interested")!.click();
    await flush();
    expect(document.body.textContent).toContain("هنقلل البوستات اللي زي دي");
    expect(q(document.body, "feedback-undo")!.textContent?.trim()).toBe("تراجع");
  });
});
