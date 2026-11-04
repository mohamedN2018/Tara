// T5 (Messenger and notifications, Wave 2): Messenger dropdown, folders, row menu, seen-by, dock, message reports,
// and the notification filters and row menu.
import { createPinia, getActivePinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, type Component, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

import ConversationList from "@/components/chat/ConversationList.vue";
import MessagesPanel from "@/components/chat/MessagesPanel.vue";
import MessengerDropdown from "@/components/chat/MessengerDropdown.vue";
import NewMessageModal from "@/components/chat/NewMessageModal.vue";
import { menuSections } from "@/components/layout/menuCatalog";
import { FILTER_CATEGORIES, inlineActions, urlFor } from "@/components/notifications/kinds";
import NotificationItem from "@/components/notifications/NotificationItem.vue";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import { lastMessagePreview, seenByAt } from "@/lib/chat";
import { chatService } from "@/services/chat";
import { graphService } from "@/services/graph";
import { notificationService } from "@/services/notification";
import { useAuthStore } from "@/stores/auth";
import { MAX_EXPANDED, useChatDockStore } from "@/stores/chatDock";
import { matchesFilter, useNotificationStore } from "@/stores/notifications";
import type { Conversation, CursorPage, Notification } from "@/types";

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;

async function flush() {
  for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0));
}

async function mount(component: Component, props: Record<string, unknown> = {}): Promise<{ el: HTMLElement; router: Router }> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/home", component: Blank },
      { path: "/messages/:id?", name: "messages", component: Blank },
      { path: "/u/id/:id", name: "profile-by-id", component: Blank },
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

function conv(id: string, over: Partial<Conversation> = {}): Conversation {
  return {
    id,
    type: "dm",
    title: "",
    last_message_at: "2026-11-04T10:00:00Z",
    members: ["me", `p-${id}`],
    member_states: [],
    muted_until: null,
    pinned_messages: [],
    unread_count: 0,
    archived: false,
    request_status: "none",
    last_message: null,
    ...over,
  };
}
const page = <T>(data: T[], next: string | null = null): CursorPage<T> => ({
  data,
  page: { next_cursor: next, prev_cursor: null, has_more: !!next },
});

beforeEach(() => {
  setActivePinia(createPinia());
  i18n.global.locale.value = "en";
  const auth = useAuthStore();
  auth.account = { id: "me" } as never;
});
afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

const t = i18n.global.t as unknown as (k: string, n?: Record<string, unknown>) => string;

describe("inbox helpers", () => {
  it("previews the last message from my side, a group member, or the other person", () => {
    const label = (id: string) => (id === "sam" ? "Sam" : id);
    const last = { id: "m", sender_id: "me", type: "text", body: "hi", deleted: false, created_at: "" };
    expect(lastMessagePreview({ type: "dm", last_message: last }, "me", label, t)).toBe("You: hi");
    expect(lastMessagePreview({ type: "group", last_message: { ...last, sender_id: "sam" } }, "me", label, t)).toBe("Sam: hi");
    expect(lastMessagePreview({ type: "dm", last_message: { ...last, sender_id: "sam" } }, "me", label, t)).toBe("hi");
    expect(lastMessagePreview({ type: "dm", last_message: { ...last, deleted: true, sender_id: "sam" } }, "me", label, t)).toBe(
      "This message was deleted",
    );
    expect(lastMessagePreview({ type: "dm", last_message: null }, "me", label, t)).toBe("");
  });

  it("puts each member's seen avatar under the newest message they read, never mine or their own", () => {
    const msgs = [
      { id: "a", seq: 1, sender_id: "me" },
      { id: "b", seq: 2, sender_id: "sam" },
      { id: "c", seq: 3, sender_id: "me" },
    ];
    const seen = seenByAt(
      msgs,
      [
        { account_id: "me", last_read_message_id: "c", last_read_seq: 3 },
        { account_id: "lea", last_read_message_id: "c", last_read_seq: 3 },
        { account_id: "ali", last_read_message_id: "a", last_read_seq: 1 },
        { account_id: "sam", last_read_message_id: "b", last_read_seq: 2 },
        { account_id: "new", last_read_message_id: null, last_read_seq: 0 },
      ],
      "me",
    );
    expect(seen).toEqual({ c: ["lea"], a: ["ali"] });
  });
});

describe("chat service folders and reports", () => {
  it("asks the server for a folder, a type or unread threads", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: page([]) });
    await chatService.folderPage({ folder: "requests" });
    await chatService.folderPage({ type: "marketplace", unread: true, cursor: "c1" });
    await chatService.folderPage({ folder: "inbox" });
    expect(get.mock.calls[0][1]).toEqual({ params: { cursor: undefined, folder: "requests", type: undefined, unread: undefined } });
    expect(get.mock.calls[1][1]).toEqual({ params: { cursor: "c1", folder: undefined, type: "marketplace", unread: 1 } });
    expect(get.mock.calls[2][1]).toEqual({ params: { cursor: undefined, folder: undefined, type: undefined, unread: undefined } });
  });

  it("answers requests and reports messages", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: conv("x") } });
    await chatService.answerRequest("x", "decline");
    await chatService.reportMessage("m1", "spam");
    expect(post).toHaveBeenCalledWith("/conversations/x/request/", { action: "decline" });
    expect(post).toHaveBeenCalledWith("/messages/m1/report/", { reason: "spam" });
  });
});

describe("Messenger dropdown", () => {
  it("lists chats with previews, filters unread on the server and pages with Load more", async () => {
    vi.spyOn(chatService, "unread").mockResolvedValue({ messages: 0, conversations: 0, requests: 2 });
    const rows = Array.from({ length: 9 }, (_, i) =>
      conv(`c${i}`, { last_message: { id: "m", sender_id: "me", type: "text", body: `hello ${i}`, deleted: false, created_at: "" } }),
    );
    const folderPage = vi.spyOn(chatService, "folderPage").mockImplementation(async (q = {}) => {
      if (q.unread) return page([rows[0]]);
      if (q.cursor) return page([conv("c9")]);
      return page(rows, "next");
    });
    const { el } = await mount(MessengerDropdown);
    (el.querySelector('[data-testid="messenger-button"]') as HTMLButtonElement).click();
    await flush();
    expect(el.querySelectorAll('[data-testid="messenger-dropdown-row"]').length).toBe(8);
    expect(el.querySelector('[data-testid="conversation-preview"]')?.textContent).toContain("You: hello 0");
    expect(el.querySelector('[data-testid="messenger-requests-banner"]')?.textContent).toContain("2 message requests");

    (el.querySelector('[data-testid="messenger-dropdown-more"]') as HTMLButtonElement).click();
    await flush();
    expect(el.querySelectorAll('[data-testid="messenger-dropdown-row"]').length).toBe(9);
    (el.querySelector('[data-testid="messenger-dropdown-more"]') as HTMLButtonElement).click();
    await flush();
    expect(el.querySelectorAll('[data-testid="messenger-dropdown-row"]').length).toBe(10);

    (el.querySelector('[data-testid="messenger-filter-unread"]') as HTMLButtonElement).click();
    await flush();
    expect(folderPage).toHaveBeenLastCalledWith({ unread: true });
    expect(el.querySelectorAll('[data-testid="messenger-dropdown-row"]').length).toBe(1);

    // Options: the folders as real links.
    (el.querySelector('[data-testid="messenger-options"]') as HTMLButtonElement).click();
    await flush();
    const archived = el.querySelector('[data-testid="messenger-folder-archived"]') as HTMLAnchorElement;
    expect(archived.getAttribute("href")).toBe("/messages?folder=archived");
  });

  it("shows a plain inbox link for phones", async () => {
    vi.spyOn(chatService, "folderPage").mockResolvedValue(page([]));
    const { el } = await mount(MessengerDropdown);
    expect(el.querySelector('[data-testid="messenger-mobile"]')?.getAttribute("href")).toBe("/messages");
  });

  it("the panel reloads when the unread filter changes", async () => {
    const folderPage = vi.spyOn(chatService, "folderPage").mockResolvedValue(page([]));
    await mount(MessagesPanel, { unread: true });
    expect(folderPage).toHaveBeenCalledWith({ unread: true });
  });
});

describe("New message", () => {
  it("opens a DM with one friend and a named group with several", async () => {
    vi.spyOn(graphService, "friends").mockResolvedValue(["f1", "f2"]);
    const dm = vi.spyOn(chatService, "openDm").mockResolvedValue(conv("d"));
    const group = vi.spyOn(chatService, "createGroup").mockResolvedValue(conv("g", { type: "group" }));
    const done = vi.fn();
    await mount(NewMessageModal, { onDone: done });
    const friends = () => document.querySelectorAll<HTMLButtonElement>('[data-testid="new-message-friend"]');
    const start = () => document.querySelector('[data-testid="new-message-start"]') as HTMLButtonElement;
    expect(friends().length).toBe(2);
    expect(start().disabled).toBe(true);
    friends()[0].click();
    await flush();
    start().click();
    await flush();
    expect(dm).toHaveBeenCalledWith("f1");
    expect(done).toHaveBeenCalledTimes(1);

    friends()[1].click();
    await flush();
    expect(start().disabled).toBe(true); // a group needs a name
    const name = document.getElementById("new-message-group") as HTMLInputElement;
    name.value = "Trip";
    name.dispatchEvent(new Event("input"));
    await flush();
    start().click();
    await flush();
    expect(group).toHaveBeenCalledWith("Trip", ["f1", "f2"]);
  });
});

describe("conversation row menu", () => {
  it("offers mute for a while, archive, clear, block and report on a DM", async () => {
    const onAction = vi.fn();
    const { el } = await mount(ConversationList, { conversations: [conv("a")], selfId: "me", onAction });
    (el.querySelector('[data-testid="conversation-row-menu"]') as HTMLButtonElement).click();
    await flush();
    const items = [...el.querySelectorAll('[data-testid="conversation-row-actions"] [role="menuitem"]')].map((b) => b.textContent?.trim());
    expect(items).toEqual(expect.arrayContaining(["Mute notifications", "Archive", "Clear chat for me"]));
    (el.querySelector('[data-testid="row-block"]') as HTMLButtonElement).click();
    expect(onAction).toHaveBeenCalledWith("a", "block", undefined);

    (el.querySelector('[data-testid="conversation-row-menu"]') as HTMLButtonElement).click();
    await flush();
    const mute = [...el.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find((b) => b.textContent?.includes("Mute"))!;
    mute.click();
    await flush();
    [...el.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find((b) => b.textContent?.includes("For 1 week"))!.click();
    expect(onAction).toHaveBeenCalledWith("a", "mute", 10080);
  });

  it("a message request row offers accept and delete instead", async () => {
    const onAction = vi.fn();
    const { el } = await mount(ConversationList, {
      conversations: [conv("r", { request_status: "pending" })],
      selfId: "me",
      onAction,
    });
    (el.querySelector('[data-testid="conversation-row-menu"]') as HTMLButtonElement).click();
    await flush();
    const labels = [...el.querySelectorAll('[role="menuitem"]')].map((b) => b.textContent?.trim());
    expect(labels.slice(0, 2)).toEqual(["Accept", "Delete"]);
    expect(labels).not.toContain("Archive");
  });
});

describe("chat dock", () => {
  it("keeps the newest windows open and folds older ones into heads", () => {
    const dock = useChatDockStore();
    dock.open("a");
    dock.open("b");
    dock.open("c");
    expect(dock.windows.filter((w) => !w.minimised).map((w) => w.id)).toEqual(["c", "b"]);
    expect(dock.windows.filter((w) => !w.minimised)).toHaveLength(MAX_EXPANDED);
    dock.open("a");
    expect(dock.windows[0]).toMatchObject({ id: "a", minimised: false });
    dock.describe("a", "Sam", "p1");
    dock.minimise("a");
    dock.open("a");
    expect(dock.windows[0]).toMatchObject({ id: "a", title: "Sam", peerId: "p1", minimised: false });
    dock.close("a");
    expect(dock.windows.map((w) => w.id)).not.toContain("a");
  });
});

describe("menu catalogue", () => {
  it("shows the inbox folders as built query routes", () => {
    const items = menuSections([], "personal").flatMap((s) => s.items);
    const byId = Object.fromEntries(items.map((i) => [i.id, i]));
    expect(byId.archived?.to).toEqual({ path: "/messages", query: { folder: "archived" } });
    expect(byId.messageRequests?.to).toEqual({ path: "/messages", query: { folder: "requests" } });
    expect(byId.marketplaceChats?.to).toEqual({ path: "/messages", query: { folder: "marketplace" } });
  });
});

function notif(over: Partial<Notification> = {}): Notification {
  return {
    id: "n1",
    kind: "post.reaction",
    category: "social",
    actor_id: "a1",
    actor_count: 1,
    subject_ref: "post:p1",
    body: "",
    read_at: null,
    created_at: "2026-11-01T10:00:00Z",
    last_event_at: "2026-11-01T10:00:00Z",
    url: "/posts/p1",
    ...over,
  };
}

describe("notifications", () => {
  it("offers Join / Decline on a group invitation and links pages by id", () => {
    expect(inlineActions(notif({ kind: "group.invite", data: { group_id: "g1" } }))).toEqual(["join", "decline_invite"]);
    expect(inlineActions(notif({ kind: "group.invite", data: { group_id: "g1" }, resolution: "joined" }))).toEqual([]);
    expect(urlFor(notif({ url: "", subject_ref: "page:p9" }))).toBe("/pages/id/p9");
    expect(urlFor(notif({ url: "", subject_ref: "page:p9", data: { page_handle: "cafe" } }))).toBe("/pages/cafe");
    expect(FILTER_CATEGORIES).toContain("account");
  });

  it("filters on the server into a second list, keeping the dropdown's list whole", async () => {
    const list = vi.spyOn(notificationService, "list").mockImplementation(async (opts) => {
      const o = typeof opts === "object" ? opts : {};
      if (o.category === "groups") return page([notif({ id: "g", category: "groups", kind: "group.invite" })]);
      return page([notif({ id: "a" }), notif({ id: "b", read_at: "2026-11-01T11:00:00Z" })]);
    });
    const store = useNotificationStore();
    await store.load();
    await store.setFilter({ unread: false, category: "groups" });
    expect(list).toHaveBeenLastCalledWith({ unread: false, category: "groups" });
    expect(store.filtered.map((n) => n.id)).toEqual(["g"]);
    expect(store.items.map((n) => n.id)).toEqual(["a", "b"]);
    // A live row joins the filtered list only when it matches.
    store.upsert(notif({ id: "live", category: "social", last_event_at: "2026-11-02T10:00:00Z" }));
    expect(store.filtered.map((n) => n.id)).toEqual(["g"]);
    expect(matchesFilter(notif({ read_at: "x" }), { unread: true, category: "" })).toBe(false);
    await store.setFilter({ unread: false, category: "" });
    expect(store.filtering).toBe(false);
    expect(store.filtered).toEqual([]);
  });

  it("the row menu marks read, removes, and turns off notifications like this with Undo", async () => {
    const onRead = vi.fn();
    const onDismiss = vi.fn();
    const onTurnOff = vi.fn((_n: Notification, done: (ok: boolean) => void) => done(true));
    const onUndoTurnOff = vi.fn((_n: Notification, done: (ok: boolean) => void) => done(true));
    const { el } = await mount(NotificationItem, { notification: notif(), onRead, onDismiss, onTurnOff, onUndoTurnOff });
    const open = () => (el.querySelector('[data-testid="notification-menu"]') as HTMLButtonElement).click();
    open();
    await flush();
    (el.querySelector('[data-testid="notification-mark-read"]') as HTMLButtonElement).click();
    expect(onRead).toHaveBeenCalledWith("n1");
    open();
    await flush();
    (el.querySelector('[data-testid="notification-turn-off"]') as HTMLButtonElement).click();
    await flush();
    expect(onTurnOff).toHaveBeenCalled();
    expect(el.querySelector('[data-testid="notification-turned-off"]')).not.toBeNull();
    (el.querySelector('[data-testid="notification-undo"]') as HTMLButtonElement).click();
    await flush();
    expect(onUndoTurnOff).toHaveBeenCalled();
    expect(el.querySelector('[data-testid="notification-turned-off"]')).toBeNull();
    open();
    await flush();
    (el.querySelector('[data-testid="notification-dismiss"]') as HTMLButtonElement).click();
    expect(onDismiss).toHaveBeenCalledWith("n1");
  });

  it("turning off sends the kind's switches, and Undo clears them", async () => {
    const patch = vi.spyOn(notificationService, "updatePreferences").mockResolvedValue({ prefs: {}, quiet_hours: {}, message_previews: true });
    const { useNotificationActions } = await import("@/components/notifications/useNotificationActions");
    let actions: ReturnType<typeof useNotificationActions> | null = null;
    await mount(defineComponent({ setup: () => ((actions = useNotificationActions()), () => null) }));
    await actions!.turnOff(notif({ kind: "follow" }));
    await actions!.undoTurnOff(notif({ kind: "follow" }));
    expect(patch).toHaveBeenNthCalledWith(1, { prefs: { follow: { in_app: false, push: false } } });
    expect(patch).toHaveBeenNthCalledWith(2, { prefs: { follow: { in_app: null, push: null } } });
  });
});
