import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import PostCard from "@/components/post/PostCard.vue";
import { i18n, setLocale } from "@/i18n";
import { api } from "@/lib/api";
import { resetRelationshipPrefs } from "@/lib/useRelationshipPrefs";
import { type FeedReason, isSuggestedReason } from "@/services/feed";
import { useAuthStore } from "@/stores/auth";
import type { Post } from "@/types";

// Tara Intelligence 4b.6 (web): a post from the popular or fresh pools carries
// a small "Suggested for you" label; posts from the viewer's circle never do.

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;

async function flush() {
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
}

const post = (): Post =>
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
  }) as Post;

async function mount(feedReason: FeedReason | null) {
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
  app = createApp({ render: () => h(PostCard, { post: post(), feedReason }) });
  app.use(createPinia()).use(router).use(i18n);
  app.mount(host);
  await flush();
  return host;
}

const label = (el: ParentNode) => el.querySelector<HTMLElement>('[data-testid="post-suggested"]');

beforeEach(() => {
  setActivePinia(createPinia());
  localStorage.clear();
  resetRelationshipPrefs();
  setLocale("en");
  useAuthStore().account = { id: "me-1", email: "me@example.com" } as never;
  vi.spyOn(api, "get").mockResolvedValue({ data: { data: [], page: { next_cursor: null, has_more: false } } });
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.restoreAllMocks();
  setLocale("en");
});

describe("Suggested label on a post card (4b.6)", () => {
  it("knows which reasons are suggestions", () => {
    expect(isSuggestedReason("rec_popular")).toBe(true);
    expect(isSuggestedReason("rec_fresh")).toBe(true);
    for (const r of ["self", "friend", "follow", null, undefined] as const) expect(isSuggestedReason(r)).toBe(false);
  });

  it.each(["rec_popular", "rec_fresh"] as const)("shows 'Suggested for you' for %s", async (reason) => {
    const el = await mount(reason);
    expect(label(el)?.textContent?.trim()).toBe("Suggested for you");
    // Above the author line, inside the card.
    const article = el.querySelector("article")!;
    expect(article.firstElementChild).toBe(label(el));
  });

  it.each(["self", "friend", "follow", null] as const)("shows nothing for %s", async (reason) => {
    const el = await mount(reason);
    expect(label(el)).toBeNull();
    expect(el.textContent).not.toContain("Suggested");
  });

  it("speaks Arabic, right to left, with logical spacing", async () => {
    setLocale("ar");
    const el = await mount("rec_fresh");
    expect(document.documentElement.dir).toBe("rtl");
    const node = label(el)!;
    expect(node.textContent?.trim()).toBe("مقترح ليك");
    expect(node.className).toContain("text-start");
    expect(node.className).not.toMatch(/\b(ml|mr|pl|pr|left|right)-/);
    expect(node.className).toContain("text-brand-700");
  });
});
