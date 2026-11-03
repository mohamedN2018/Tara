import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import {
  advancePointer,
  attachmentKind,
  badgeText,
  canDeleteForEveryone,
  canEdit,
  conversationTitle,
  deliveryStatus,
  formatBytes,
  tooLarge,
  withoutMessage,
} from "@/lib/chat";
import { realtime } from "@/lib/ws";
import { chatService } from "@/services/chat";
import { useChatUnreadStore } from "@/stores/chatUnread";
import { usePresenceStore } from "@/stores/presence";
import type { ConversationMemberState, Message } from "@/types";

const ME = "me";

function msg(over: Partial<Message> = {}): Message {
  return {
    id: "m1",
    conversation_id: "c",
    sender_id: ME,
    type: "text",
    body: "hi",
    seq: 5,
    attachments: [],
    reactions: [],
    created_at: new Date().toISOString(),
    ...over,
  };
}
function state(account: string, read = 0, delivered = 0): ConversationMemberState {
  return { account_id: account, role: "member", last_read_message_id: null, last_read_seq: read, last_delivered_seq: delivered };
}

/** Capture realtime handlers so a test can play frames into a store. */
function captureFrames() {
  const handlers = new Map<string, Array<(f: Record<string, unknown>) => void>>();
  vi.spyOn(realtime, "on").mockImplementation((type, handler) => {
    handlers.set(type, [...(handlers.get(type) ?? []), handler as never]);
    return () => undefined;
  });
  const sent: Record<string, unknown>[] = [];
  vi.spyOn(realtime, "send").mockImplementation((frame) => void sent.push(frame));
  const play = (type: string, frame: Record<string, unknown>) =>
    handlers.get(type)?.forEach((h) => h({ event: type, ...frame }));
  return { play, sent };
}

describe("delivery ticks", () => {
  it("goes sent -> delivered -> read from the peer's pointers", () => {
    const m = msg();
    expect(deliveryStatus(m, [state(ME, 5, 5), state("peer", 0, 4)], ME)).toBe("sent");
    expect(deliveryStatus(m, [state(ME, 5, 5), state("peer", 0, 5)], ME)).toBe("delivered");
    expect(deliveryStatus(m, [state(ME, 5, 5), state("peer", 7, 7)], ME)).toBe("read");
  });

  it("needs every other member in a group", () => {
    const m = msg();
    const states = [state(ME, 5, 5), state("a", 9, 9), state("b", 0, 5)];
    expect(deliveryStatus(m, states, ME)).toBe("delivered");
  });

  it("shows nothing on other people's messages or tombstones, and 'sent' without a seq", () => {
    expect(deliveryStatus(msg({ sender_id: "peer" }), [state("peer")], ME)).toBeNull();
    expect(deliveryStatus(msg({ deleted: true }), [state("peer", 9, 9)], ME)).toBeNull();
    expect(deliveryStatus(msg({ seq: null }), [state("peer", 9, 9)], ME)).toBe("sent");
  });

  it("never moves a pointer backwards, and reading implies delivery", () => {
    const s = state("peer", 4, 4);
    advancePointer(s, "last_read_seq", 2);
    expect(s.last_read_seq).toBe(4);
    advancePointer(s, "last_read_seq", 6);
    expect([s.last_read_seq, s.last_delivered_seq]).toEqual([6, 6]);
    advancePointer(s, "last_delivered_seq", null);
    expect(s.last_delivered_seq).toBe(6);
  });
});

describe("message lifecycle rules", () => {
  it("allows edits by the sender for 15 minutes, never on forwards or tombstones", () => {
    const now = Date.now();
    const at = (minutesAgo: number) => new Date(now - minutesAgo * 60_000).toISOString();
    expect(canEdit(msg({ created_at: at(14) }), ME, now)).toBe(true);
    expect(canEdit(msg({ created_at: at(16) }), ME, now)).toBe(false);
    expect(canEdit(msg({ sender_id: "peer" }), ME, now)).toBe(false);
    expect(canEdit(msg({ forwarded: true }), ME, now)).toBe(false);
    expect(canEdit(msg({ deleted: true }), ME, now)).toBe(false);
    expect(canDeleteForEveryone(msg({ created_at: at(59) }), ME, now)).toBe(true);
    expect(canDeleteForEveryone(msg({ created_at: at(61) }), ME, now)).toBe(false);
    expect(canDeleteForEveryone(msg({ sender_id: "peer" }), ME, now)).toBe(false);
  });

  it("drops a removed message", () => {
    expect(withoutMessage([msg({ id: "a" }), msg({ id: "b" })], "a").map((m) => m.id)).toEqual(["b"]);
  });
});

describe("conversationTitle", () => {
  const label = (id: string) => ({ a: "Ann", b: "Bob", me: "Me" })[id] ?? id;
  it("joins the other members in the UI language's list style", () => {
    const c = { title: null, members: ["me", "a", "b"] };
    expect(conversationTitle(c, "me", label, "en", "Group")).toBe("Ann, Bob");
    // Arabic list punctuation, never the English comma.
    const ar = conversationTitle(c, "me", label, "ar", "مجموعة");
    expect(ar).toMatch(/^Ann.+Bob$/);
    expect(ar).not.toContain(", ");
  });
  it("prefers the group's own title, and falls back when alone", () => {
    expect(conversationTitle({ title: "Trip", members: ["me", "a"] }, "me", label, "en", "Group")).toBe("Trip");
    expect(conversationTitle({ title: "", members: ["me"] }, "me", label, "en", "Group")).toBe("Group");
  });
});

describe("attachments", () => {
  it("accepts photos, mp4/webm video and PDF only", () => {
    expect(attachmentKind({ type: "image/heic" })).toBe("image");
    // Chrome on Windows reports no type for an iPhone photo.
    expect(attachmentKind({ type: "", name: "IMG_0001.HEIC" })).toBe("image");
    expect(attachmentKind({ type: "", name: "notes.txt" })).toBeNull();
    expect(attachmentKind({ type: "video/mp4" })).toBe("video");
    expect(attachmentKind({ type: "video/quicktime" })).toBeNull();
    expect(attachmentKind({ type: "application/pdf" })).toBe("file");
    expect(attachmentKind({ type: "application/x-msdownload" })).toBeNull();
    expect(tooLarge("video", 65 * 1024 * 1024)).toBe(true);
    expect(tooLarge("file", 1024)).toBe(false);
  });

  it("formats sizes and badges", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(null)).toBe("");
    expect(badgeText(7)).toBe("7");
    expect(badgeText(120)).toBe("99+");
  });
});

describe("chat service", () => {
  it("asks for the archived folder and scoped deletes", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: { data: [], page: {} } });
    await chatService.conversationsPage(undefined, true);
    expect(get).toHaveBeenCalledWith("/conversations/", { params: { cursor: undefined, archived: 1 } });
    const del = vi.spyOn(api, "delete").mockResolvedValue({});
    await chatService.deleteMessage("m1", "everyone");
    expect(del).toHaveBeenCalledWith("/messages/m1/", { params: { scope: "everyone" } });
  });

  it("caches attachment URLs minted by chat", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({
      data: { data: { media_id: "x", url: "https://s/x", thumb_url: null } },
    });
    const first = await chatService.attachmentUrl("m-cache", "x");
    const second = await chatService.attachmentUrl("m-cache", "x");
    expect(get).toHaveBeenCalledTimes(1);
    expect(get).toHaveBeenCalledWith("/messages/m-cache/attachments/x/");
    expect(second?.url).toBe(first?.url);
  });

  it("uploads chat media as private", async () => {
    const { mediaService } = await import("@/services/media");
    const upload = vi.spyOn(mediaService, "upload").mockResolvedValue({ id: "a" } as never);
    await chatService.upload(new File(["x"], "a.pdf", { type: "application/pdf" }), "file");
    expect(upload).toHaveBeenCalledWith(expect.any(File), "file", "private");
  });
});

describe("presence store", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setActivePinia(createPinia());
  });
  afterEach(() => vi.useRealTimers());

  it("asks the gateway about the people on screen, in one batch", async () => {
    const { sent } = captureFrames();
    const presence = usePresenceStore();
    presence.bind();
    presence.isOnline("a");
    presence.isOnline("b");
    presence.isOnline("a");
    await vi.advanceTimersByTimeAsync(100);
    expect(sent).toEqual([{ action: "presence.query", account_ids: ["a", "b"] }]);
  });

  it("applies snapshots and live transitions; last seen only while offline", async () => {
    const { play } = captureFrames();
    const presence = usePresenceStore();
    presence.bind();
    play("presence.state", { states: [{ account_id: "a", online: true, last_seen: null }] });
    expect(presence.isOnline("a")).toBe(true);
    expect(presence.lastSeen("a")).toBeNull();
    play("presence.changed", { account_id: "a", online: false, last_seen: "2026-11-03T10:00:00Z" });
    expect(presence.isOnline("a")).toBe(false);
    expect(presence.lastSeen("a")).toBe("2026-11-03T10:00:00Z");
    expect(presence.isOnline("stranger")).toBe(false);
  });

  it("asks again after a reconnect", async () => {
    const { play, sent } = captureFrames();
    const presence = usePresenceStore();
    presence.bind();
    presence.isOnline("a");
    await vi.advanceTimersByTimeAsync(100);
    play("_reconnected", {});
    expect(sent.at(-1)).toEqual({ action: "presence.query", account_ids: ["a"] });
  });
});

describe("unread badge store", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setActivePinia(createPinia());
  });
  afterEach(() => vi.useRealTimers());

  it("marks delivery for other people's messages and refreshes the count", async () => {
    const { play } = captureFrames();
    const delivered = vi.spyOn(chatService, "markDelivered").mockResolvedValue();
    vi.spyOn(chatService, "unread").mockResolvedValue({ messages: 3, conversations: 2 });
    const store = useChatUnreadStore();
    store.bind(() => ME);
    await vi.advanceTimersByTimeAsync(500);
    expect(delivered).toHaveBeenCalledTimes(1);
    expect(store.conversations).toBe(2);

    play("chat.message.created", { sender: ME });
    await vi.advanceTimersByTimeAsync(500);
    expect(delivered).toHaveBeenCalledTimes(1); // my own message: nothing to deliver

    play("chat.message.created", { sender: "peer" });
    play("chat.message.created", { sender: "peer" });
    await vi.advanceTimersByTimeAsync(500);
    expect(delivered).toHaveBeenCalledTimes(2); // a burst is one call
  });
});
