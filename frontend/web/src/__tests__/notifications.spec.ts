import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { inlineActions, notificationText, urlFor } from "@/components/notifications/kinds";
import { i18n } from "@/i18n";
import { enablePush, pushActiveFor, releasePush, resumePush } from "@/lib/pwa";
import { inQuietHours, playPing, setSoundEnabled } from "@/lib/sound";
import { notificationService } from "@/services/notification";
import { useNotificationStore } from "@/stores/notifications";
import type { Notification } from "@/types";

function row(over: Partial<Notification> = {}): Notification {
  return {
    id: "n1",
    kind: "post.reaction",
    actor_id: "a1",
    actor_count: 1,
    subject_ref: "post:p1",
    body: "reacted to your post",
    read_at: null,
    created_at: "2026-11-01T10:00:00Z",
    last_event_at: "2026-11-01T10:00:00Z",
    url: "/posts/p1",
    ...over,
  };
}

const g = i18n.global;
const text = (n: Notification, locale: "en" | "ar" = "en") => {
  g.locale.value = locale;
  return notificationText(n, g.t as never, g.te, "Sara");
};

describe("notification text and actions", () => {
  afterEach(() => {
    g.locale.value = "en";
  });

  it("names one actor", () => {
    expect(text(row())).toBe("Sara reacted to your post");
  });

  it("groups other people with plurals in both languages", () => {
    expect(text(row({ actor_count: 2 }))).toBe("Sara and 1 other reacted to your post");
    expect(text(row({ actor_count: 4 }))).toBe("Sara and 3 others reacted to your post");
    expect(text(row({ actor_count: 2 }), "ar")).toBe("تفاعل Sara وشخص آخر مع منشورك");
    expect(text(row({ actor_count: 3 }), "ar")).toBe("تفاعل Sara وشخصان آخران مع منشورك");
    expect(text(row({ actor_count: 6 }), "ar")).toBe("تفاعل Sara و5 أشخاص آخرين مع منشورك");
    expect(text(row({ actor_count: 25 }), "ar")).toBe("تفاعل Sara و24 شخصًا آخر مع منشورك");
  });

  it("words attachment-only messages and shows a message preview", () => {
    expect(text(row({ kind: "message", body: "" }))).toBe("Sara sent you an attachment");
    expect(text(row({ kind: "message", body: "hi" }))).toBe("Sara: hi");
  });

  it("reads the listing status from structured data", () => {
    expect(text(row({ kind: "listing.status", actor_id: null, data: { status: "sold" } }))).toContain("Your listing is now");
  });

  it("offers inline actions only while unresolved", () => {
    expect(inlineActions(row({ kind: "friend.request", data: { request_id: "r1" } }))).toEqual(["accept", "decline"]);
    expect(inlineActions(row({ kind: "friend.request", data: { request_id: "r1" }, resolution: "accepted" }))).toEqual([]);
    expect(inlineActions(row({ kind: "follow" }))).toEqual(["follow_back"]);
    expect(inlineActions(row({ kind: "follow", actor_count: 3 }))).toEqual([]);
  });

  it("only follows same-origin deep links", () => {
    expect(urlFor(row({ url: "/posts/p1?comment=c1" }))).toBe("/posts/p1?comment=c1");
    expect(urlFor(row({ url: "//evil.example/x" }))).toBe("/posts/p1");
    expect(urlFor(row({ url: "https://evil.example" , subject_ref: "conversation:k" }))).toBe("/messages/k");
    expect(urlFor(row({ url: undefined, subject_ref: "", kind: "friend.request" }))).toBe("/u/id/a1");
  });
});

describe("live notification store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("fetches an announced row once and moves a grown aggregate to the top", async () => {
    const store = useNotificationStore();
    store.items = [row({ id: "old", last_event_at: "2026-11-01T09:00:00Z" }), row({ id: "agg", last_event_at: "2026-11-01T08:00:00Z" })];
    const get = vi
      .spyOn(notificationService, "get")
      .mockResolvedValue(row({ id: "agg", actor_count: 3, last_event_at: "2026-11-01T11:00:00Z" }));
    await Promise.all([store.fetchOne("agg"), store.fetchOne("agg")]);
    expect(get).toHaveBeenCalledTimes(1);
    expect(store.items.map((n) => n.id)).toEqual(["agg", "old"]);
    expect(store.items[0].actor_count).toBe(3);
  });

  it("marks read optimistically and rolls back on failure", async () => {
    const store = useNotificationStore();
    store.items = [row()];
    store.unread = 1;
    vi.spyOn(notificationService, "markRead").mockRejectedValue(new Error("down"));
    await expect(store.markRead("n1")).rejects.toThrow();
    expect(store.items[0].read_at).toBeNull();
    expect(store.unread).toBe(1);
  });

  it("dismisses and restores the row if the server refuses", async () => {
    const store = useNotificationStore();
    store.items = [row()];
    store.unread = 1;
    const remove = vi.spyOn(notificationService, "remove").mockResolvedValueOnce();
    await store.remove("n1");
    expect(store.items).toEqual([]);
    expect(store.unread).toBe(0);

    store.items = [row()];
    store.unread = 1;
    remove.mockRejectedValueOnce(new Error("down"));
    await expect(store.remove("n1")).rejects.toThrow();
    expect(store.items.map((n) => n.id)).toEqual(["n1"]);
    expect(store.unread).toBe(1);
  });

  it("stores an inline action's outcome from the server", async () => {
    const store = useNotificationStore();
    store.items = [row({ kind: "friend.request", data: { request_id: "r1" } })];
    store.unread = 1;
    vi.spyOn(notificationService, "resolve").mockResolvedValue(
      row({ kind: "friend.request", resolution: "accepted", read_at: "2026-11-01T12:00:00Z" }),
    );
    await store.resolve("n1", "accepted");
    expect(store.items[0].resolution).toBe("accepted");
    expect(store.unread).toBe(0);
  });

  it("applies reads, dismissals and rows from other tabs", () => {
    vi.spyOn(notificationService, "unreadCount").mockResolvedValue(0);
    const store = useNotificationStore();
    store.items = [row({ id: "a" }), row({ id: "b" })];
    store.onSync({ type: "read", ids: ["a"], at: "2026-11-02T00:00:00Z" });
    expect(store.items.find((n) => n.id === "a")?.read_at).toBe("2026-11-02T00:00:00Z");
    store.onSync({ type: "deleted", ids: ["b"] });
    expect(store.items.map((n) => n.id)).toEqual(["a"]);
    store.onSync({ type: "upsert", item: row({ id: "c", last_event_at: "2026-11-03T00:00:00Z" }) });
    expect(store.items[0].id).toBe("c");
    store.onSync({ type: "read-all", at: "2026-11-04T00:00:00Z" });
    expect(store.items.every((n) => n.read_at)).toBe(true);
  });

  it("keeps rows that arrived live while the first page loaded", async () => {
    const store = useNotificationStore();
    store.items = [row({ id: "live", last_event_at: "2026-11-05T00:00:00Z" })];
    vi.spyOn(notificationService, "list").mockResolvedValue({
      data: [row({ id: "p1" })],
      page: { next_cursor: null, prev_cursor: null, has_more: false },
    });
    await store.load();
    expect(store.items.map((n) => n.id)).toEqual(["live", "p1"]);
  });
});

describe("sound ping", () => {
  afterEach(() => setSoundEnabled(false));

  it.each([
    ["2026-01-01T23:00:00Z", { start: "22:00", end: "07:00" }, true],
    ["2026-01-01T03:00:00Z", { start: "22:00", end: "07:00" }, true],
    ["2026-01-01T07:00:00Z", { start: "22:00", end: "07:00" }, false],
    ["2026-01-01T13:00:00Z", { start: "09:00", end: "17:00" }, true],
    ["2026-01-01T17:00:00Z", { start: "09:00", end: "17:00" }, false],
  ])("quiet hours at %s in %j: %s", (at, window, expected) => {
    expect(inQuietHours({ ...window, timezone: "UTC" }, new Date(at))).toBe(expected);
  });

  it("uses the saved timezone", () => {
    // 21:30 UTC is 23:30 in Cairo (UTC+2 in January).
    expect(inQuietHours({ start: "23:00", end: "06:00", timezone: "Africa/Cairo" }, new Date("2026-01-01T21:30:00Z"))).toBe(true);
  });

  it("is off by default and silent during quiet hours", () => {
    expect(playPing()).toBe(false);
    setSoundEnabled(true);
    expect(playPing({ start: "00:00", end: "23:59", timezone: "UTC" })).toBe(false);
  });
});

// ---- push subscription lifecycle ------------------------------------------------------

interface FakeSubscription {
  endpoint: string;
  unsubscribe: ReturnType<typeof vi.fn>;
  toJSON: () => { endpoint: string; keys: { p256dh: string; auth: string } };
}

function fakeSubscription(endpoint: string): FakeSubscription {
  return {
    endpoint,
    unsubscribe: vi.fn().mockResolvedValue(true),
    toJSON: () => ({ endpoint, keys: { p256dh: "k", auth: "a" } }),
  };
}

function installPush(initial: FakeSubscription | null, permission: NotificationPermission = "granted") {
  let current: FakeSubscription | null = initial;
  const pushManager = {
    getSubscription: vi.fn(async () => current),
    subscribe: vi.fn(async () => {
      current = fakeSubscription("https://fcm.googleapis.com/fcm/send/new");
      return current;
    }),
  };
  const registration = { pushManager };
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: {
      getRegistration: vi.fn(async () => registration),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    },
  });
  (window as unknown as { PushManager: unknown }).PushManager = function PushManager() {};
  (window as unknown as { Notification: unknown }).Notification = Object.assign(function Notification() {}, {
    permission,
    requestPermission: vi.fn(async () => permission),
  });
  return { pushManager, current: () => current };
}

describe("push lifecycle", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.spyOn(notificationService, "pushConfig").mockResolvedValue({ enabled: true, public_key: "AAAA" });
  });
  afterEach(() => {
    delete (navigator as unknown as { serviceWorker?: unknown }).serviceWorker;
    delete (window as unknown as { PushManager?: unknown }).PushManager;
    delete (window as unknown as { Notification?: unknown }).Notification;
  });

  it("enabling records the owner, so the subscription counts as on only for them", async () => {
    installPush(null);
    vi.spyOn(notificationService, "registerWebPush").mockResolvedValue();
    expect(await enablePush("alice")).toBe("on");
    expect(await pushActiveFor("alice")).toBe(true);
    expect(await pushActiveFor("bob")).toBe(false);
  });

  it("logout unsubscribes locally even when the server cannot be told", async () => {
    const sub = fakeSubscription("https://fcm.googleapis.com/fcm/send/a");
    installPush(sub);
    localStorage.setItem("tara.push.owner", "alice");
    vi.spyOn(notificationService, "unregisterWebPush").mockRejectedValue(new Error("401"));
    await releasePush({ remote: true });
    expect(sub.unsubscribe).toHaveBeenCalled();
    expect(localStorage.getItem("tara.push.owner")).toBeNull();
  });

  it("login drops another account's subscription and never hands it over", async () => {
    const sub = fakeSubscription("https://fcm.googleapis.com/fcm/send/a");
    const push = installPush(sub);
    localStorage.setItem("tara.push.owner", "alice");
    const register = vi.spyOn(notificationService, "registerWebPush").mockResolvedValue();
    expect(await resumePush("bob")).toBe(false); // bob never turned push on here
    expect(sub.unsubscribe).toHaveBeenCalled();
    expect(register).not.toHaveBeenCalled();
    expect(push.pushManager.subscribe).not.toHaveBeenCalled();
  });

  it("login re-binds the account's own subscription", async () => {
    const sub = fakeSubscription("https://fcm.googleapis.com/fcm/send/a");
    installPush(sub);
    localStorage.setItem("tara.push.owner", "alice");
    const register = vi.spyOn(notificationService, "registerWebPush").mockResolvedValue();
    expect(await resumePush("alice")).toBe(true);
    expect(sub.unsubscribe).not.toHaveBeenCalled();
    expect(register).toHaveBeenCalledWith({ endpoint: sub.endpoint, keys: { p256dh: "k", auth: "a" } });
  });

  it("an account that had push on here gets it back after logout, without a prompt", async () => {
    const push = installPush(null);
    localStorage.setItem("tara.push.wanted", JSON.stringify(["alice"]));
    vi.spyOn(notificationService, "registerWebPush").mockResolvedValue();
    expect(await resumePush("alice")).toBe(true);
    expect(push.pushManager.subscribe).toHaveBeenCalled();
    expect(Notification.requestPermission).not.toHaveBeenCalled();
    expect(localStorage.getItem("tara.push.owner")).toBe("alice");
  });

  it("never prompts on resume when permission was not granted", async () => {
    const push = installPush(null, "default");
    localStorage.setItem("tara.push.wanted", JSON.stringify(["alice"]));
    expect(await resumePush("alice")).toBe(false);
    expect(push.pushManager.subscribe).not.toHaveBeenCalled();
    expect(Notification.requestPermission).not.toHaveBeenCalled();
  });
});
