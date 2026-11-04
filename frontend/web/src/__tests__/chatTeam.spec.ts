// Fix track D: "who can message you", Page and Tara Support conversations (the
// Message button, Contact support, the team inboxes) and the bidi-safe rows.
import { createPinia, getActivePinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, type Component, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

import MessagePreview from "@/components/chat/MessagePreview.vue";
import MessagePrivacySetting from "@/components/chat/MessagePrivacySetting.vue";
import PageMessageButton from "@/components/chat/PageMessageButton.vue";
import TeamInbox from "@/components/chat/TeamInbox.vue";
import NotificationItem from "@/components/notifications/NotificationItem.vue";
import { notificationText } from "@/components/notifications/kinds";
import { i18n } from "@/i18n";
import { bodySegments, isTeamThread, SUPPORT_SENDER_ID, teamSenderName, teamThreadTitle } from "@/lib/chat";
import { targetLink } from "@/services/admin";
import { chatService, type TeamConversation } from "@/services/chat";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import type { Conversation, CursorPage, Notification } from "@/types";

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;

async function flush() {
  for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0));
}

async function mount(component: Component, props: Record<string, unknown> = {}): Promise<{ el: HTMLElement; router: Router }> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/home", component: Blank },
      { path: "/messages/:id?", name: "messages", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push("/home");
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({ render: () => h(component, props) });
  app.use(getActivePinia()!).use(router).use(i18n);
  app.mount(host);
  await flush();
  return { el: host, router };
}

const page = <T>(data: T[], next: string | null = null): CursorPage<T> => ({
  data,
  page: { next_cursor: next, prev_cursor: null, has_more: !!next },
});
const t = i18n.global.t as unknown as (k: string, n?: Record<string, unknown>) => string;

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
});

describe("team threads", () => {
  it("names the other side as the Page or Tara Support, never a person", () => {
    const support = { type: "support", title: "" };
    const pageThread = { type: "page", title: "Nile Bakery", page_id: "pg1" };
    expect(isTeamThread(support)).toBe(true);
    expect(isTeamThread({ type: "dm" })).toBe(false);
    expect(teamThreadTitle(support, t)).toBe("Tara Support");
    expect(teamThreadTitle(pageThread, t)).toBe("Nile Bakery");
    expect(teamSenderName(support, SUPPORT_SENDER_ID, t)).toBe("Tara Support");
    expect(teamSenderName(pageThread, "pg1", t)).toBe("Nile Bakery");
    expect(teamSenderName(pageThread, "me", t)).toBeNull();
  });

  it("Message on a Page opens the page conversation; the team gets the page inbox", async () => {
    const open = vi.spyOn(chatService, "openPage").mockResolvedValue({ id: "c-page" } as never);
    vi.spyOn(chatService, "teamUnread").mockResolvedValue(0);
    const { el, router } = await mount(PageMessageButton, { page: { id: "pg1", status: "published", my_role: null } });
    (el.querySelector("[data-testid=page-message]") as HTMLButtonElement).click();
    await flush();
    expect(open).toHaveBeenCalledWith("pg1");
    expect(router.currentRoute.value.fullPath).toBe("/messages/c-page");
    app?.unmount();
    document.body.innerHTML = "";

    const team = await mount(PageMessageButton, { page: { id: "pg1", status: "published", my_role: "editor" } });
    expect(team.el.querySelector("[data-testid=page-message]")).toBeNull();
    expect(team.el.querySelector("[data-testid=page-inbox-link]")?.getAttribute("href")).toBe("/pages/id/pg1/inbox");
    app?.unmount();
    document.body.innerHTML = "";

    // A draft page, or a team role that does not answer messages: nothing.
    const draft = await mount(PageMessageButton, { page: { id: "pg1", status: "draft", my_role: null } });
    expect(draft.el.querySelector("button, a")).toBeNull();
  });

  it("the team inbox lists threads, opens one, marks it read and replies as the team", async () => {
    const row: TeamConversation = {
      id: "c1",
      type: "support",
      title: "",
      page_id: null,
      account_id: "member-1",
      left: false,
      last_message_at: "2026-11-04T10:00:00Z",
      last_seq: 1,
      team_unread: 1,
      last_message: { id: "m1", sender_id: "member-1", type: "text", body: "My account is locked", deleted: false, created_at: "2026-11-04T10:00:00Z" },
      created_at: "2026-11-04T10:00:00Z",
    };
    useDirectoryStore().remember("member-1", "Mona Adel", null);
    const inbox = vi.spyOn(chatService, "teamInbox").mockResolvedValue(page([row]));
    const msgs = vi.spyOn(chatService, "teamMessages").mockResolvedValue(
      page([{ id: "m1", conversation_id: "c1", sender_id: "member-1", type: "text", body: "My account is locked", attachments: [], reactions: [], created_at: "2026-11-04T10:00:00Z" }]),
    );
    const read = vi.spyOn(chatService, "teamRead").mockResolvedValue();
    const reply = vi.spyOn(chatService, "teamReply").mockResolvedValue({
      id: "m2",
      conversation_id: "c1",
      sender_id: SUPPORT_SENDER_ID,
      author_id: "me",
      type: "text",
      body: "Unlocked now",
      attachments: [],
      reactions: [],
      created_at: "2026-11-04T10:05:00Z",
    });
    const { el } = await mount(TeamInbox, { teamName: "Tara Support" });
    expect(inbox).toHaveBeenCalledWith(undefined);
    expect(el.querySelector("[data-testid=team-unread]")).not.toBeNull();
    (el.querySelector("[data-testid=team-row]") as HTMLButtonElement).click();
    await flush();
    expect(msgs).toHaveBeenCalledWith("c1");
    expect(read).toHaveBeenCalledWith("c1");
    expect(el.querySelector("[data-testid=team-unread]")).toBeNull();
    expect(el.querySelector("[data-testid=team-thread-member]")?.textContent).toContain("Mona Adel");

    const box = el.querySelector("[data-testid=team-reply]") as HTMLTextAreaElement;
    box.value = "Unlocked now";
    box.dispatchEvent(new Event("input"));
    await flush();
    (el.querySelector("form") as HTMLFormElement).dispatchEvent(new Event("submit"));
    await flush();
    expect(reply).toHaveBeenCalledWith("c1", "Unlocked now");
    const last = [...el.querySelectorAll("[data-testid=team-message]")].at(-1)!;
    expect(last.textContent).toContain("Unlocked now");
    expect(last.textContent).toContain("Tara Support");
  });
});

describe("who can message you", () => {
  it("reads the setting and saves a new choice", async () => {
    vi.spyOn(chatService, "messageSettings").mockResolvedValue("everyone");
    const save = vi.spyOn(chatService, "setMessageSettings").mockResolvedValue("friends");
    const { el } = await mount(MessagePrivacySetting);
    const everyone = el.querySelector("[data-testid=message-from-everyone] input") as HTMLInputElement;
    expect(everyone.checked).toBe(true);
    const friends = el.querySelector("[data-testid=message-from-friends] input") as HTMLInputElement;
    friends.checked = true;
    friends.dispatchEvent(new Event("change"));
    await flush();
    expect(save).toHaveBeenCalledWith("friends");
  });

  it("says so when the setting cannot be loaded", async () => {
    vi.spyOn(chatService, "messageSettings").mockRejectedValue(new Error("down"));
    const { el } = await mount(MessagePrivacySetting);
    expect(el.querySelector("fieldset")).toBeNull();
    expect(el.textContent).toContain("can't be loaded");
  });
});

describe("bidi-safe rows", () => {
  it("keeps a group preview's name and text in separate isolates", async () => {
    useDirectoryStore().remember("sam", "ليلى", null);
    const c = {
      id: "g",
      type: "group",
      title: "Team",
      members: ["me", "sam"],
      last_message: { id: "m", sender_id: "sam", type: "text", body: "seen?", deleted: false, created_at: "" },
    } as unknown as Conversation;
    const { el } = await mount(MessagePreview, { conversation: c, selfId: "me" });
    expect(el.querySelector("[data-testid=preview-who]")?.tagName).toBe("BDI");
    expect(el.querySelector("[data-testid=preview-who]")?.textContent).toBe("ليلى");
    expect(el.querySelector("[data-testid=preview-text]")?.getAttribute("dir")).toBe("auto");
    expect(el.querySelector("[data-testid=conversation-preview]")?.hasAttribute("dir")).toBe(false);
  });

  it("turns only same-origin story/listing/post links into short in-app links", () => {
    const id = "01a1a742-5c44-74d3-b2f7-379ca6deeb9a";
    expect(bodySegments(`Replying to your story: https://tara.example/stories/${id}`, "https://tara.example")).toEqual([
      { text: "Replying to your story: " },
      { to: `/stories/${id}`, kind: "story" },
    ]);
    expect(bodySegments(`see https://other.example/posts/${id} ok`, "https://tara.example")).toEqual([
      { text: `see https://other.example/posts/${id} ok` },
    ]);
    expect(bodySegments("https://tara.example/settings", "https://tara.example")).toEqual([{ text: "https://tara.example/settings" }]);
  });

  it("leaves a story link out of a message notification's sentence", () => {
    const n = {
      id: "n2",
      kind: "message",
      category: "messages",
      actor_id: "sam",
      actor_count: 1,
      body: "Replying to your story: https://tara.example/stories/01a1a742-5c44-74d3-b2f7-379ca6deeb9a",
      data: {},
    } as unknown as Notification;
    const text = notificationText(n, t as never, (k: string) => i18n.global.te(k), "Sam");
    expect(text).toContain("Replying to your story:");
    expect(text).not.toContain("01a1a742");
  });

  it("leaves a listing link out of the one-line preview", async () => {
    const c = {
      id: "mk",
      type: "marketplace",
      title: "",
      members: ["me", "sam"],
      last_message: {
        id: "m",
        sender_id: "sam",
        type: "text",
        body: "Is this still available? https://tara.example/marketplace/01a1a73d-a540-7018-a873-4be170d993b6",
        deleted: false,
        created_at: "",
      },
    } as unknown as Conversation;
    const { el } = await mount(MessagePreview, { conversation: c, selfId: "me" });
    expect(el.querySelector("[data-testid=preview-text]")?.textContent).toBe("Is this still available?");
  });

  it("names a Page's reply after the Page, in a <bdi>, without dir=auto on the sentence", async () => {
    const n: Notification = {
      id: "n1",
      kind: "message",
      category: "messages",
      actor_id: null,
      actor_count: 1,
      subject_ref: "conversation:c1",
      body: "Hello",
      read_at: null,
      created_at: "2026-11-01T10:00:00Z",
      last_event_at: "2026-11-01T10:00:00Z",
      url: "/messages/c1",
      data: { sender_kind: "page", sender_name: "مخبز النيل", conversation_id: "c1" },
    } as unknown as Notification;
    const { el } = await mount(NotificationItem, { notification: n });
    const p = el.querySelector("[data-testid=notification-text]")!;
    expect(p.hasAttribute("dir")).toBe(false);
    expect(p.querySelector("bdi")?.textContent).toBe("مخبز النيل");
  });
});

describe("moderation links", () => {
  it("opens a reported profile on the public profile, which every moderator can see", () => {
    expect(targetLink("user", "u1")).toBe("/u/id/u1");
    expect(targetLink("page", "p1")).toBe("/pages/id/p1");
    expect(targetLink("message", "m1")).toBeNull();
  });
});
