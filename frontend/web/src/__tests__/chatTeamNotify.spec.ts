// Fix track D, round 3: isolated message excerpts in notifications, the
// listing on marketplace rows, the page team's notification and inbox badges,
// and no chat dock in the admin console.
import { createPinia, getActivePinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, type Component, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

import AdminNav from "@/components/admin/AdminNav.vue";
import ChatDock from "@/components/chat/ChatDock.vue";
import ConversationList from "@/components/chat/ConversationList.vue";
import PageMessageButton from "@/components/chat/PageMessageButton.vue";
import NotificationItem from "@/components/notifications/NotificationItem.vue";
import { isolateParts, notificationExcerpt, notificationText, urlFor } from "@/components/notifications/kinds";
import { i18n } from "@/i18n";
import { chatService } from "@/services/chat";
import { mediaService } from "@/services/media";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import type { Conversation, Notification } from "@/types";

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;

async function flush() {
  for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0));
}

async function mount(component: Component, props: Record<string, unknown> = {}, at = "/home"): Promise<{ el: HTMLElement; router: Router }> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/home", component: Blank },
      { path: "/messages/:id?", name: "messages", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push(at);
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({ render: () => h(component, props) });
  app.use(getActivePinia()!).use(router).use(i18n);
  app.mount(host);
  await flush();
  return { el: host, router };
}

const t = i18n.global.t as unknown as (k: string, n?: Record<string, unknown>, p?: number) => string;
const te = (k: string) => i18n.global.te(k);

function message(over: Partial<Notification> = {}): Notification {
  return {
    id: "n1",
    kind: "message",
    category: "messages",
    actor_id: "sam",
    actor_count: 1,
    subject_ref: "conversation:c1",
    body: "seen?",
    read_at: null,
    created_at: "2026-11-01T10:00:00Z",
    last_event_at: "2026-11-01T10:00:00Z",
    url: "/messages/c1",
    data: { conversation_id: "c1" },
    ...over,
  } as unknown as Notification;
}

beforeEach(() => {
  setActivePinia(createPinia());
  i18n.global.locale.value = "en";
  useAuthStore().account = { id: "me" } as never;
});
afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.restoreAllMocks();
  document.body.innerHTML = "";
  i18n.global.locale.value = "en";
});

describe("message excerpts in notifications", () => {
  it("splits a sentence into the name, the excerpt and the rest", () => {
    expect(isolateParts("ليلى: seen?", "ليلى", "seen?")).toEqual([
      { text: "ليلى", isolate: "name" },
      { text: ": " },
      { text: "seen?", isolate: "excerpt" },
    ]);
    // An excerpt that repeats the name is still found after it.
    expect(isolateParts("Sam: Sam", "Sam", "Sam")).toEqual([
      { text: "Sam", isolate: "name" },
      { text: ": " },
      { text: "Sam", isolate: "excerpt" },
    ]);
    expect(isolateParts("no match", "", "")).toEqual([{ text: "no match" }]);
  });

  it("quotes the text of one message only", () => {
    expect(notificationExcerpt(message())).toBe("seen?");
    expect(notificationExcerpt(message({ data: { message_count: 3 } }))).toBe("");
    expect(notificationExcerpt(message({ kind: "post.comment" }))).toBe("");
  });

  it("isolates an English message in the Arabic UI, so 'seen?' never reads '?seen'", async () => {
    i18n.global.locale.value = "ar";
    useDirectoryStore().remember("sam", "ليلى", null);
    const { el } = await mount(NotificationItem, { notification: message() });
    const p = el.querySelector("[data-testid=notification-text]")!;
    expect(p.hasAttribute("dir")).toBe(false);
    const isolates = [...p.querySelectorAll("bdi")];
    expect(isolates.map((b) => b.textContent)).toEqual(["ليلى", "seen?"]);
    const excerpt = p.querySelector("[data-testid=notification-excerpt]")!;
    expect(excerpt.getAttribute("dir")).toBe("auto");
    expect(p.textContent).toBe("ليلى: seen?");
  });
});

describe("a message to a Page", () => {
  const pageMessage = message({
    kind: "message.page",
    category: "pages",
    body: "Do you deliver?",
    url: "/pages/id/pg1/inbox?conversation=c1",
    data: { conversation_id: "c1", page_id: "pg1", page_name: "مخبز النيل" },
  });

  it("names the sender and the Page, and opens the page inbox on that thread", () => {
    expect(notificationText(pageMessage, t, te, "Sam")).toBe("Sam to مخبز النيل: Do you deliver?");
    expect(notificationText({ ...pageMessage, body: "" }, t, te, "Sam")).toBe("Sam sent مخبز النيل a message");
    expect(notificationText({ ...pageMessage, data: { ...pageMessage.data, message_count: 2 } }, t, te, "Sam")).toBe(
      "Sam sent مخبز النيل 2 messages",
    );
    expect(urlFor(pageMessage)).toBe("/pages/id/pg1/inbox?conversation=c1");
  });

  it("shows the team's unread count on the Page inbox link", async () => {
    const unread = vi.spyOn(chatService, "teamUnread").mockResolvedValue(3);
    const { el } = await mount(PageMessageButton, { page: { id: "pg1", status: "published", my_role: "owner" } });
    expect(unread).toHaveBeenCalledWith("pg1");
    expect(el.querySelector("[data-testid=page-inbox-unread]")?.textContent?.trim()).toBe("3");
  });

  it("asks for no count when the viewer is not on the team", async () => {
    const unread = vi.spyOn(chatService, "teamUnread").mockResolvedValue(3);
    await mount(PageMessageButton, { page: { id: "pg1", status: "published", my_role: null } });
    expect(unread).not.toHaveBeenCalled();
  });

  it("shows the support inbox's count to staff in the console menu", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "canAny").mockImplementation((caps: readonly string[]) => caps.includes("moderation.case.view"));
    vi.spyOn(chatService, "teamUnread").mockResolvedValue(2);
    const { el } = await mount(AdminNav, { vertical: true }, "/admin");
    expect(el.querySelector("[data-testid=admin-support-unread]")?.textContent?.trim()).toBe("2");
  });
});

describe("marketplace rows", () => {
  it("show the listing's title and photo, so threads with one person can be told apart", async () => {
    vi.spyOn(mediaService, "resolveUrl").mockResolvedValue("https://cdn.example/desk.jpg");
    useDirectoryStore().remember("sam", "Sam Adel", null);
    const row = (id: string, title: string): Conversation =>
      ({
        id,
        type: "marketplace",
        title: "",
        members: ["me", "sam"],
        member_states: [],
        pinned_messages: [],
        listing_id: `l-${id}`,
        listing_title: title,
        listing_cover_media_id: `m-${id}`,
        last_message: null,
      }) as unknown as Conversation;
    const { el } = await mount(ConversationList, { conversations: [row("a", "Oak desk"), row("b", "Red bike")], selfId: "me" });
    const titles = [...el.querySelectorAll("[data-testid=conversation-listing]")].map((s) => s.textContent);
    expect(titles).toEqual(["Oak desk", "Red bike"]);
    expect(el.querySelectorAll("[data-testid=listing-avatar]").length).toBe(2);
    expect(el.querySelector("[data-testid=listing-avatar-cover]")?.getAttribute("src")).toBe("https://cdn.example/desk.jpg");
  });

  it("keep the old look for a thread with no listing snapshot", async () => {
    const legacy = {
      id: "z",
      type: "marketplace",
      title: "",
      members: ["me", "sam"],
      member_states: [],
      pinned_messages: [],
      listing_id: "l-z",
      last_message: null,
    } as unknown as Conversation;
    const { el } = await mount(ConversationList, { conversations: [legacy], selfId: "me" });
    expect(el.querySelector("[data-testid=conversation-listing]")).toBeNull();
    expect(el.querySelector("[data-testid=listing-avatar]")).toBeNull();
  });
});

describe("the chat dock", () => {
  it("stays out of the admin console", async () => {
    const home = await mount(ChatDock, {}, "/home");
    expect(home.el.querySelector("[data-testid=chat-dock]")).not.toBeNull();
    app?.unmount();
    document.body.innerHTML = "";
    for (const path of ["/admin", "/admin/support", "/admin/moderation"]) {
      const admin = await mount(ChatDock, {}, path);
      expect(admin.el.querySelector("[data-testid=chat-dock]")).toBeNull();
      app?.unmount();
      document.body.innerHTML = "";
    }
    app = null;
  });
});
