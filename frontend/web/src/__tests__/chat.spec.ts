import { describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import {
  applyReaction,
  isSeen,
  isSeenByOthers,
  mergeMessages,
  oldestFirst,
  reactionSummary,
} from "@/lib/chat";
import { pickContainer } from "@/lib/useVoiceRecorder";
import { chatService } from "@/services/chat";
import type { Message } from "@/types";

function msg(id: string, minute: number, sender = "peer"): Message {
  return {
    id,
    conversation_id: "c",
    sender_id: sender,
    type: "text",
    body: id,
    attachments: [],
    reactions: [],
    created_at: `2026-11-03T10:${String(minute).padStart(2, "0")}:00Z`,
  };
}
const ids = (list: Message[]) => list.map((m) => m.id);

describe("ordering", () => {
  it("sorts oldest first without mutating the input", () => {
    const newestFirst = [msg("c", 3), msg("b", 2), msg("a", 1)];
    expect(ids(oldestFirst(newestFirst))).toEqual(["a", "b", "c"]);
    expect(ids(newestFirst)).toEqual(["c", "b", "a"]);
  });

  it("breaks timestamp ties deterministically", () => {
    expect(ids(oldestFirst([msg("b", 1), msg("a", 1)]))).toEqual(["a", "b"]);
  });

  it("the service reverses the API's newest-first page and keeps the cursor", async () => {
    vi.spyOn(api, "get").mockResolvedValue({
      data: {
        data: [msg("m3", 3), msg("m2", 2), msg("m1", 1)],
        page: { next_cursor: "older", prev_cursor: null, has_more: true },
      },
    });
    const page = await chatService.messages("c");
    expect(ids(page.data)).toEqual(["m1", "m2", "m3"]);
    expect(page.page.next_cursor).toBe("older");
    expect(page.data.at(-1)?.id).toBe("m3"); // what markRead and scroll rely on
  });
});

describe("mergeMessages", () => {
  it("prepends older pages and appends newer ones", () => {
    const loaded = [msg("m3", 3), msg("m4", 4)];
    const older = [msg("m1", 1), msg("m2", 2)];
    expect(ids(mergeMessages(loaded, older))).toEqual(["m1", "m2", "m3", "m4"]);
    expect(ids(mergeMessages(loaded, [msg("m5", 5)]))).toEqual(["m3", "m4", "m5"]);
  });

  it("never duplicates a message delivered by both the POST and a WS frame", () => {
    const loaded = [msg("m1", 1), msg("m2", 2)];
    expect(ids(mergeMessages(loaded, [msg("m2", 2), msg("m3", 3)]))).toEqual(["m1", "m2", "m3"]);
  });

  it("keeps history beyond one page when merging the latest page", () => {
    const history = Array.from({ length: 45 }, (_, i) => msg(`m${i}`, i));
    const merged = mergeMessages(history, [...history.slice(-19), msg("new", 59)]);
    expect(merged).toHaveLength(46);
    expect(merged.at(-1)?.id).toBe("new");
  });

  it("lets incoming data replace a stale copy", () => {
    const edited = { ...msg("m1", 1), body: "edited" };
    expect(mergeMessages([msg("m1", 1)], [edited])[0].body).toBe("edited");
  });
});

describe("isSeen", () => {
  const list = [msg("a", 1, "me"), msg("b", 2), msg("c", 3, "me"), msg("d", 4)];

  it("is true when the receipt is at or after my latest message", () => {
    expect(isSeen(list, "c", "me")).toBe(true);
    expect(isSeen(list, "d", "me")).toBe(true);
  });

  it("is false when the receipt is before my latest message", () => {
    expect(isSeen(list, "b", "me")).toBe(false);
  });

  it("is false without a receipt, an unknown id, or a message of mine", () => {
    expect(isSeen(list, null, "me")).toBe(false);
    expect(isSeen(list, "not-loaded", "me")).toBe(false);
    expect(isSeen([msg("b", 2)], "b", "me")).toBe(false);
  });
});

describe("isSeenByOthers", () => {
  const list = [msg("a", 1, "me"), msg("b", 2, "peer"), msg("c", 3, "me")];
  const state = (account_id: string, last_read_message_id: string | null) => ({
    account_id,
    role: "member",
    last_read_message_id,
  });

  it("survives a reload: read state comes from the conversation", () => {
    expect(isSeenByOthers(list, [state("peer", "c"), state("me", "c")], "me")).toBe(true);
  });
  it("ignores my own read state and older receipts", () => {
    expect(isSeenByOthers(list, [state("peer", "b"), state("me", "c")], "me")).toBe(false);
  });
  it("is true when any group member has read it", () => {
    expect(isSeenByOthers(list, [state("x", null), state("y", "c")], "me")).toBe(true);
  });
});

describe("reactions", () => {
  const r = (account_id: string, type: string) => ({ account_id, type });

  it("a member has one reaction, and null removes it", () => {
    const start = [r("a", "like"), r("b", "love")];
    expect(applyReaction(start, "a", "haha")).toEqual([r("b", "love"), r("a", "haha")]);
    expect(applyReaction(start, "a", null)).toEqual([r("b", "love")]);
  });

  it("summarises by count, most used first", () => {
    const summary = reactionSummary([r("a", "like"), r("b", "love"), r("c", "love")]);
    expect(summary).toEqual([{ type: "love", count: 2 }, { type: "like", count: 1 }]);
  });
});

describe("pickContainer", () => {
  it("takes the first format the browser can record", () => {
    expect(pickContainer((m) => m === "audio/mp4")?.ext).toBe("m4a");
    expect(pickContainer((m) => m.startsWith("audio/"))?.ext).toBe("webm");
    expect(pickContainer(() => false)).toBeNull();
  });
});
