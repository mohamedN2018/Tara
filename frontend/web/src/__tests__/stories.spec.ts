// Track T9: stories service calls, the viewer's reading-direction controls and
// the Home rail.
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import StoriesRail from "@/components/stories/StoriesRail.vue";
import StoryViewer from "@/components/stories/StoryViewer.vue";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import { type Story, type StoryGroup, storiesService } from "@/services/stories";
import { useAuthStore } from "@/stores/auth";

const ME = "00000000-0000-4000-8000-000000000001";
const FRIEND = "00000000-0000-4000-8000-000000000002";

function story(id: string, author: string, extra: Partial<Story> = {}): Story {
  return {
    id,
    author_id: author,
    kind: "text",
    media_id: null,
    text: `text ${id}`,
    background: "violet",
    audience: "friends",
    created_at: new Date(Date.now() - 60_000).toISOString(),
    expires_at: new Date(Date.now() + 3_600_000).toISOString(),
    is_mine: author === ME,
    is_active: true,
    seen: false,
    my_reaction: null,
    view_count: author === ME ? 3 : null,
    reaction_count: author === ME ? 1 : null,
    ...extra,
  };
}

const flush = async () => {
  for (let i = 0; i < 6; i += 1) await nextTick();
  await new Promise((r) => setTimeout(r, 0));
  await nextTick();
};

let app: App | null = null;
function mount(component: object, props: Record<string, unknown> = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:p(.*)*", component: { template: "<div/>" } }] });
  const el = document.createElement("div");
  document.body.appendChild(el);
  app = createApp(component, props).use(i18n).use(router).use(pinia);
  app.mount(el);
  return el;
}

beforeEach(() => {
  i18n.global.locale.value = "en";
  document.documentElement.dir = "ltr";
});
afterEach(() => {
  app?.unmount();
  app = null;
  document.body.innerHTML = "";
  document.body.style.overflow = "";
  vi.restoreAllMocks();
});

describe("stories service", () => {
  it("reads the tray and one author's stories", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: { data: [] } });
    await storiesService.tray();
    await storiesService.ofAuthor(FRIEND);
    expect(get).toHaveBeenNthCalledWith(1, "/stories/tray/");
    expect(get).toHaveBeenNthCalledWith(2, "/stories/", { params: { author_id: FRIEND } });
  });

  it("creates a story with an idempotency key", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: story("s1", ME) } });
    await storiesService.create({ kind: "text", audience: "close_friends", text: "hi", background: "dusk" });
    const [url, body, config] = post.mock.calls[0];
    expect(url).toBe("/stories/");
    expect(body).toEqual({ kind: "text", audience: "close_friends", text: "hi", background: "dusk" });
    expect((config as { headers: Record<string, string> }).headers["Idempotency-Key"]).toBeTruthy();
  });

  it("reports with an enum reason and manages close friends", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: { added: [FRIEND] } } });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: {} });
    await storiesService.report("s1", "spam");
    expect(await storiesService.addCloseFriends([FRIEND])).toEqual([FRIEND]);
    await storiesService.removeCloseFriend(FRIEND);
    expect(post).toHaveBeenNthCalledWith(1, "/stories/s1/report/", { reason: "spam" });
    expect(post).toHaveBeenNthCalledWith(2, "/stories/close-friends/", { account_ids: [FRIEND] });
    expect(del).toHaveBeenCalledWith(`/stories/close-friends/${FRIEND}/`);
  });
});

describe("story viewer", () => {
  const groups = (): StoryGroup[] => [
    { author_id: FRIEND, has_unseen: true, latest_at: new Date().toISOString(), stories: [story("a1", FRIEND), story("a2", FRIEND)] },
  ];

  it("marks another person's story seen and shows reactions, not the viewer list", async () => {
    const seen = vi.spyOn(storiesService, "markSeen").mockImplementation(async (id) => story(id, FRIEND, { seen: true }));
    mount(StoryViewer, { groups: groups() });
    await flush();
    expect(current()).toBe("a1");
    expect(seen).toHaveBeenCalledWith("a1");
    expect(document.body.querySelectorAll('[data-testid="story-progress"] > span')).toHaveLength(2);
    expect(document.body.querySelector('[data-testid="story-reactions"]')).not.toBeNull();
    expect(document.body.querySelector('[data-testid="story-viewers"]')).toBeNull();
  });

  it("the arrow keys follow the reading direction", async () => {
    vi.spyOn(storiesService, "markSeen").mockImplementation(async (id) => story(id, FRIEND, { seen: true }));
    mount(StoryViewer, { groups: groups() });
    await flush();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight" }));
    await flush();
    expect(current()).toBe("a2");
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft" }));
    await flush();
    expect(current()).toBe("a1");
  });

  it("in Arabic, ArrowLeft goes forward", async () => {
    i18n.global.locale.value = "ar";
    document.documentElement.dir = "rtl";
    vi.spyOn(storiesService, "markSeen").mockImplementation(async (id) => story(id, FRIEND, { seen: true }));
    mount(StoryViewer, { groups: groups() });
    await flush();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft" }));
    await flush();
    expect(current()).toBe("a2");
    // The fill grows from the inline start, so it runs right to left in RTL.
    const fill = document.body.querySelector('[data-testid="story-progress-fill"]');
    expect(fill?.className).toContain("start-0");
  });

  it("the author sees the viewer count and no reaction bar, and is never marked seen", async () => {
    const seen = vi.spyOn(storiesService, "markSeen");
    mount(StoryViewer, {
      groups: [{ author_id: ME, has_unseen: false, latest_at: new Date().toISOString(), stories: [story("m1", ME, { seen: true })] }],
    });
    await flush();
    expect(seen).not.toHaveBeenCalled();
    expect(document.body.querySelector('[data-testid="story-viewers"]')?.textContent).toContain("3 viewers");
    expect(document.body.querySelector('[data-testid="story-reactions"]')).toBeNull();
  });

  it("Escape closes", async () => {
    vi.spyOn(storiesService, "markSeen").mockImplementation(async (id) => story(id, FRIEND, { seen: true }));
    const onClose = vi.fn();
    mount(StoryViewer, { groups: groups(), onClose });
    await flush();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(onClose).toHaveBeenCalled();
  });
});

describe("story viewer: replies and the side panel", () => {
  const OTHER = "00000000-0000-4000-8000-000000000003";
  const two = (): StoryGroup[] => [
    { author_id: FRIEND, has_unseen: true, latest_at: new Date().toISOString(), stories: [story("a1", FRIEND)] },
    { author_id: OTHER, has_unseen: true, latest_at: new Date().toISOString(), stories: [story("b1", OTHER), story("b2", OTHER)] },
  ];

  it("a reply is sent to the author as a direct message with a link back", async () => {
    vi.spyOn(storiesService, "markSeen").mockImplementation(async (id) => story(id, FRIEND, { seen: true }));
    const reply = vi.spyOn(storiesService, "reply").mockResolvedValue("c1");
    mount(StoryViewer, { groups: two() });
    await flush();
    const input = document.body.querySelector<HTMLInputElement>('[data-testid="story-reply-input"]')!;
    input.value = "  nice one  ";
    input.dispatchEvent(new Event("input"));
    // Typing is text, not navigation.
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    await flush();
    expect(current()).toBe("a1");
    document.body.querySelector<HTMLFormElement>('[data-testid="story-reply"]')!.dispatchEvent(new Event("submit"));
    await flush();
    expect(reply).toHaveBeenCalledTimes(1);
    const [target, text, line] = reply.mock.calls[0];
    expect(target.author_id).toBe(FRIEND);
    expect(text).toBe("nice one");
    expect(line).toMatch(/Replying to your story: .*\/stories\/a1$/);
    expect(input.value).toBe("");
  });

  it("the reply service opens the DM and sends the text with the link line", async () => {
    const post = vi
      .spyOn(api, "post")
      .mockResolvedValueOnce({ data: { data: { id: "conv1" } } })
      .mockResolvedValueOnce({ data: { data: { id: "m1" } } });
    expect(await storiesService.reply({ author_id: FRIEND }, " hi ", "link line")).toBe("conv1");
    expect(post).toHaveBeenNthCalledWith(1, "/conversations/", { type: "dm", other_id: FRIEND });
    expect(post.mock.calls[1][0]).toBe("/conversations/conv1/messages/");
    expect((post.mock.calls[1][1] as { body: string }).body).toBe("hi\nlink line");
  });

  it("my own story has no reply box", async () => {
    mount(StoryViewer, {
      groups: [{ author_id: ME, has_unseen: false, latest_at: new Date().toISOString(), stories: [story("m1", ME, { seen: true })] }],
    });
    await flush();
    expect(document.body.querySelector('[data-testid="story-reply"]')).toBeNull();
  });

  it("the side panel lists every author with their new count and jumps between them", async () => {
    vi.spyOn(storiesService, "markSeen").mockImplementation(async (id) => story(id, FRIEND, { seen: true }));
    const onCreate = vi.fn();
    mount(StoryViewer, { groups: two(), canCreate: true, onCreate });
    await flush();
    const rows = document.body.querySelectorAll<HTMLButtonElement>('[data-testid="story-panel-author"]');
    expect(rows).toHaveLength(2);
    expect(rows[0].getAttribute("aria-current")).toBe("true");
    expect(rows[1].textContent).toContain("2 new");
    rows[1].click();
    await flush();
    expect(current()).toBe("b1");
    document.body.querySelector<HTMLButtonElement>('[data-testid="story-panel-create"]')!.click();
    expect(onCreate).toHaveBeenCalled();
  });

  it("without canCreate the panel offers no create row", async () => {
    vi.spyOn(storiesService, "markSeen").mockImplementation(async (id) => story(id, FRIEND, { seen: true }));
    mount(StoryViewer, { groups: two() });
    await flush();
    expect(document.body.querySelector('[data-testid="story-panel-create"]')).toBeNull();
  });
});

describe("stories rail", () => {
  it("shows the create card, my story and friends' stories from the tray", async () => {
    vi.spyOn(storiesService, "tray").mockResolvedValue([
      { author_id: ME, has_unseen: false, latest_at: new Date().toISOString(), stories: [story("m1", ME, { seen: true })] },
      { author_id: FRIEND, has_unseen: true, latest_at: new Date().toISOString(), stories: [story("f1", FRIEND)] },
    ]);
    vi.spyOn(storiesService, "markSeen").mockImplementation(async (id) => story(id, FRIEND, { seen: true }));
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: [] } });
    const el = mount(StoriesRail);
    useAuthStore().account = { id: ME, email: "me@example.com" } as never;
    await flush();
    expect(el.querySelector('[data-testid="story-create"]')?.textContent).toContain("Create story");
    const cards = el.querySelectorAll('[data-testid="story-tray-card"]');
    expect(cards).toHaveLength(2);
    expect(cards[0].textContent).toContain("Your story");
    (cards[1] as HTMLButtonElement).click();
    await flush();
    expect(document.body.querySelector('[data-testid="story-viewer"]')).not.toBeNull();
    expect(current()).toBe("f1");
  });
});

function current() {
  return document.body.querySelector("[data-story]")?.getAttribute("data-story");
}
