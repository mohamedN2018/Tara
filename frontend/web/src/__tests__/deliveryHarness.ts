// Shared set-up for the feed delivery specs (WP 4c-B3): mount Home with its
// shell stubbed, a controllable IntersectionObserver, and API answers built
// from real response shapes (`/feed/`, `/posts/batch/`).
import { createPinia, setActivePinia } from "pinia";
import { vi } from "vitest";
import { type App, type Component, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import { resetDelivery } from "@/lib/delivery";
import { useAuthStore } from "@/stores/auth";
import type { Post } from "@/types";

export const ID = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

export const livePost = (id: string, extra: Partial<Post> = {}): Post => ({
  id,
  author_id: ID(900),
  author_type: "user",
  type: "text",
  body: `live ${id}`,
  audience: "public",
  media_ids: [],
  reaction_count: 3,
  comment_count: 0,
  share_count: 0,
  created_at: "2026-11-05T10:00:00Z",
  ...extra,
});

/** A `/feed/` item; `content: false` is what the server sends for a non-public post (ids only). */
export const feedItem = (id: string, content = true, extra: Record<string, unknown> = {}) => ({
  id: `fi-${id}`,
  post_id: id,
  author_id: ID(900),
  reason: "friend",
  post_created_at: "2026-11-05T10:00:00Z",
  snapshot: content
    ? { post_id: id, author_id: ID(900), author_type: "user", type: "text", audience: "public", excerpt: `snap ${id}`, media_ids: [], created_at: "2026-11-05T10:00:00Z", ...extra }
    : { post_id: id, author_id: ID(900), author_type: "user", type: "text", audience: "friends", created_at: "2026-11-05T10:00:00Z" },
});

export const feedPage = (items: unknown[], next: string | null, extra: Record<string, unknown> = {}) => ({
  data: { data: items, page: { next_cursor: next, prev_cursor: null, has_more: !!next }, mode: "recent", meta: {}, sponsored: null, ...extra },
});

/** IntersectionObserver whose instances the test can drive. */
export class FakeIO {
  static all: FakeIO[] = [];
  targets = new Set<Element>();
  constructor(
    public cb: IntersectionObserverCallback,
    public options: IntersectionObserverInit = {},
  ) {
    FakeIO.all.push(this);
  }
  observe(el: Element) {
    this.targets.add(el);
  }
  unobserve(el: Element) {
    this.targets.delete(el);
  }
  disconnect() {
    this.targets.clear();
  }
  takeRecords() {
    return [];
  }
  /** Report `el` (or every target) as intersecting or not. */
  fire(isIntersecting: boolean, el?: Element, extra: Partial<IntersectionObserverEntry> = {}) {
    const targets = el ? [el] : [...this.targets];
    const entries = targets.map(
      (target) =>
        ({
          target,
          isIntersecting,
          intersectionRatio: isIntersecting ? 1 : 0,
          boundingClientRect: { top: 0, bottom: 100, height: 100 } as DOMRectReadOnly,
          intersectionRect: { height: isIntersecting ? 100 : 0 } as DOMRectReadOnly,
          rootBounds: { height: 800 } as DOMRectReadOnly,
          time: 0,
          ...extra,
        }) as unknown as IntersectionObserverEntry,
    );
    if (entries.length) this.cb(entries, this as unknown as IntersectionObserver);
  }
}

/** The observer watching the feed's sentinel (rootMargin in px from `prefetch_root_margin_vp`). */
export const sentinelObserver = () => FakeIO.all.find((o) => [...o.targets].some((t) => (t as HTMLElement).dataset?.testid === "feed-sentinel"));

export async function flush(rounds = 10) {
  for (let i = 0; i < rounds; i++) await new Promise((r) => setTimeout(r, 0));
}

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;
let pinia = createPinia();

export function setup(locale: "ar" | "en" = "en") {
  pinia = createPinia();
  setActivePinia(pinia);
  localStorage.clear();
  sessionStorage.clear();
  resetDelivery();
  FakeIO.all = [];
  i18n.global.locale.value = locale;
  document.documentElement.dir = locale === "ar" ? "rtl" : "ltr";
  const auth = useAuthStore();
  auth.account = { id: ID(1), email: "me@example.com" } as never;
  vi.stubGlobal("IntersectionObserver", FakeIO);
}

export async function mount(component: Component, path = "/home") {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/home", name: "home", component: Blank },
      { path: "/u/id/:id", name: "profile-by-id", component: Blank },
      { path: "/pages/id/:id", name: "page-by-id", component: Blank },
      { path: "/posts/:id", name: "post", component: Blank },
      { path: "/reels/:id", name: "reel", component: Blank },
      { path: "/reels", name: "reels", component: Blank },
      { path: "/search", name: "search", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push(path);
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp(component);
  app.use(pinia).use(router).use(i18n);
  app.mount(host);
  await flush();
  return host;
}

export function teardown() {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.unstubAllGlobals();
}

/** Route api.get / api.post by URL. */
export function routeApi(handlers: {
  feed?: (params: Record<string, unknown>) => Promise<unknown> | unknown;
  batch?: (ids: string[]) => Promise<Post[]> | Post[];
}) {
  const get = vi.spyOn(api, "get").mockImplementation(async (url: string, config?: { params?: Record<string, unknown> }) => {
    if (url === "/feed/" && handlers.feed) return (await handlers.feed(config?.params ?? {})) as never;
    return { data: { data: [], page: { next_cursor: null, has_more: false } } } as never;
  });
  const post = vi.spyOn(api, "post").mockImplementation(async (url: string, body?: unknown) => {
    if (url === "/posts/batch/" && handlers.batch) return { data: { data: await handlers.batch((body as { ids: string[] }).ids) } } as never;
    return { data: { data: [] } } as never;
  });
  return { get, post };
}

/** The shell stub for vi.mock (Home is tested without its shell). */
export const shellStub = () => ({ default: defineComponent({ setup: (_, { slots }) => () => h("div", slots.default?.()) }) });
export const blankStub = () => ({ default: defineComponent({ render: () => null }) });
