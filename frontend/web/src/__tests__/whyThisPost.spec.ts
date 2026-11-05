import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApp, defineComponent, type App } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import WhyThisPost from "@/components/post/WhyThisPost.vue";
import { i18n, setLocale } from "@/i18n";
import { api } from "@/lib/api";
import { noteServed, resetSignals } from "@/lib/signals";
import type { WhyExplanation } from "@/services/feed";

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;

async function flush() {
  for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0));
}

async function open(props: Record<string, unknown>) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:rest(.*)*", component: Blank }] });
  await router.push("/home");
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp(WhyThisPost, props);
  app.use(createPinia()).use(router).use(i18n);
  app.mount(host);
  await flush();
  return document.querySelector<HTMLElement>('[data-testid="why-post"]')!;
}
const lines = (dialog: HTMLElement) =>
  [...dialog.querySelectorAll('[data-testid="why-factors"] li')].map((li) => li.textContent?.trim());

const explanation = (factors: WhyExplanation["factors"], mode: string | null = "for_you"): { data: { data: WhyExplanation } } => ({
  data: { data: { item: "post:p1", mode, surface: "home", cfg_version: "home@1", factors } },
});

beforeEach(() => {
  setActivePinia(createPinia());
  resetSignals();
  setLocale("en");
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.restoreAllMocks();
  setLocale("en");
});

describe("Why am I seeing this post? (WP 4.8)", () => {
  it("asks the server with the item's serve token and lists its factors", async () => {
    noteServed("post:00000000-0000-4000-8000-000000000001", { st: "st-1", surface: "home" });
    const get = vi.spyOn(api, "get").mockResolvedValue(
      explanation([
        { code: "follow", author_id: "a1" },
        { code: "favorite", author_id: "a1" },
        { code: "interacted_author", author_id: "a1" },
      ]),
    );
    const dialog = await open({ reason: "follow", name: "Mona", postId: "00000000-0000-4000-8000-000000000001", authorId: "a1" });
    expect(get).toHaveBeenCalledWith("/feed/why/post/00000000-0000-4000-8000-000000000001/", { params: { st: "st-1" } });
    expect(lines(dialog)).toEqual(["You follow Mona.", "You added Mona to Favorites.", "You often interact with Mona."]);
    expect(dialog.textContent).toContain("Your feed is sorted by: For you.");
  });

  it("keeps the feed's own reason when the server answers 404", async () => {
    vi.spyOn(api, "get").mockRejectedValue({ response: { status: 404 } });
    const dialog = await open({ reason: "friend", name: "Ali", postId: "p1", authorId: "a1", mode: "recent" });
    expect(lines(dialog)).toEqual(["You're friends with Ali."]);
    expect(dialog.textContent).toContain("Latest");
  });

  it("shows a sensitive topic only as a topic you follow, and skips unknown codes", async () => {
    vi.spyOn(api, "get").mockResolvedValue(
      explanation([{ code: "group_member" }, { code: "rec_topic_sensitive" }, { code: "experiment_x" }]),
    );
    const dialog = await open({ reason: "follow", name: "G", postId: "p1" });
    expect(lines(dialog)).toEqual(["It's from a group you're in.", "It's about a topic you follow."]);
  });

  it("explains a suggestion from the popular or fresh pools (4b.6)", async () => {
    vi.spyOn(api, "get").mockResolvedValue(explanation([{ code: "rec_popular" }, { code: "rec_fresh" }]));
    const dialog = await open({ reason: "rec_popular", name: "Mona", postId: "p1", authorId: "a1" });
    expect(lines(dialog)).toEqual(["A public post people are engaging with", "A new public post"]);
  });

  it("falls back to the suggestion's own reason, never 'you follow', when the server is silent", async () => {
    vi.spyOn(api, "get").mockRejectedValue({ response: { status: 404 } });
    let dialog = await open({ reason: "rec_fresh", name: "Mona", postId: "p1" });
    expect(lines(dialog)).toEqual(["A new public post"]);
    expect(dialog.textContent).not.toContain("Mona");
    app?.unmount();
    host?.remove();
    setLocale("ar");
    dialog = await open({ reason: "rec_popular", name: "منى", postId: "p1" });
    expect(document.documentElement.dir).toBe("rtl");
    expect(lines(dialog)).toEqual(["منشور عام الناس بتتفاعل معاه"]);
  });

  it("speaks Arabic, right to left", async () => {
    setLocale("ar");
    vi.spyOn(api, "get").mockResolvedValue(
      explanation([{ code: "friend", author_id: "a1" }, { code: "demoted_feedback" }, { code: "public_pool", format: "reel" }], "friends"),
    );
    const dialog = await open({ reason: "friend", name: "منى", postId: "p1", authorId: "a1" });
    expect(document.documentElement.dir).toBe("rtl");
    expect(lines(dialog)).toEqual(["أنت صديق لـ منى.", "ظهر أقل بسبب ملاحظاتك.", "منشور عام من خارج الحسابات التي تتابعها."]);
    expect(dialog.textContent).toContain("الأصدقاء");
    expect(dialog.querySelector("h2")?.textContent).toBe("لماذا ترى هذا المنشور");
    for (const span of dialog.querySelectorAll('[data-testid="why-factors"] span')) expect(span.getAttribute("dir")).toBe("auto");
  });
});
