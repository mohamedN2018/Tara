import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import { feedService, type HydratedFeedPage } from "@/services/feed";
import { useAuthStore } from "@/stores/auth";
import type { Post } from "@/types";
import HomeView from "@/views/HomeView.vue";

// The Reels rail on Home shows exactly once: between posts when the feed has
// some, and under the empty state when it has none (it renders nothing itself
// without real reels; that is ReelsRail's own spec).

vi.mock("@/components/layout/AppShell.vue", () => ({
  default: defineComponent({ setup: (_, { slots }) => () => h("div", slots.default?.()) }),
}));
vi.mock("@/components/post/CreatePostCard.vue", () => ({ default: defineComponent({ render: () => null }) }));
vi.mock("@/components/auth/CompleteProfileCard.vue", () => ({ default: defineComponent({ render: () => null }) }));
vi.mock("@/components/reels/ReelsRail.vue", () => ({
  default: defineComponent({ render: () => h("section", { "data-testid": "reels-rail-stub" }) }),
}));

const post = (id: string): Post => ({
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
});
const hydrated = (posts: Post[]): HydratedFeedPage => ({
  posts,
  reasons: {},
  sponsored: [],
  nextCursor: null,
  hasMore: false,
  modeApplied: true,
});

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;

async function flush() {
  for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0));
}

async function mountHome() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/home", name: "home", component: Blank },
      { path: "/u/id/:id", name: "profile-by-id", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push("/home");
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp(HomeView);
  app.use(pinia).use(router).use(i18n);
  app.mount(host);
  await flush();
  return host;
}

let pinia: ReturnType<typeof createPinia>;

beforeEach(() => {
  pinia = createPinia();
  setActivePinia(pinia);
  localStorage.clear();
  sessionStorage.clear();
  i18n.global.locale.value = "en";
  useAuthStore().account = { id: "me-1", email: "me@example.com" } as never;
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
  vi.restoreAllMocks();
});

describe("Home reels rail", () => {
  it("shows once under the empty state when the feed has no posts", async () => {
    vi.spyOn(feedService, "page").mockResolvedValue(hydrated([]));
    const el = await mountHome();
    expect(el.textContent).toContain(i18n.global.t("feed.empty"));
    expect(el.querySelectorAll('[data-testid="reels-rail-stub"]')).toHaveLength(1);
  });

  it("shows once between posts when the feed has some", async () => {
    vi.spyOn(feedService, "page").mockResolvedValue(hydrated([post("a"), post("b")]));
    const el = await mountHome();
    expect(el.querySelectorAll('[data-testid="reels-rail-stub"]')).toHaveLength(1);
  });

  it("does not show while the feed failed to load", async () => {
    vi.spyOn(feedService, "page").mockRejectedValue(new Error("down"));
    const el = await mountHome();
    expect(el.querySelectorAll('[data-testid="reels-rail-stub"]')).toHaveLength(0);
  });
});
