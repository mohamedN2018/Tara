import { describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { addReply, emptyThread, mergeById, removeComment, replaceComment, replyTargetAuthor, threadRootId } from "@/lib/commentThreads";
import { applyReactionChange, topReactions } from "@/lib/reactionCounts";
import { type Comment, postService } from "@/services/post";

const c = (id: string, extra: Partial<Comment> = {}): Comment => ({
  id,
  post_id: "p",
  author_id: `author-${id}`,
  parent_id: null,
  reply_to_id: null,
  reply_to_author_id: null,
  body: id,
  reply_count: 0,
  created_at: "2026-11-03T10:00:00Z",
  ...extra,
});

describe("flattened threads", () => {
  it("labels a reply to a reply with the author answered", () => {
    const replyToReply = c("r2", { parent_id: "root", reply_to_id: "r1", reply_to_author_id: "bob" });
    expect(replyTargetAuthor(replyToReply)).toBe("bob");
  });

  it("does not label a reply to the root, or a root", () => {
    expect(replyTargetAuthor(c("r1", { parent_id: "root", reply_to_id: "root", reply_to_author_id: "ann" }))).toBeNull();
    expect(replyTargetAuthor(c("root"))).toBeNull();
  });

  it("files every reply under its root", () => {
    expect(threadRootId(c("r2", { parent_id: "root", reply_to_id: "r1" }))).toBe("root");
    expect(threadRootId(c("root"))).toBe("root");
  });

  it("merges pages without duplicates and keeps the order", () => {
    const merged = mergeById([c("a"), c("b")], [c("b", { body: "new" }), c("c")]);
    expect(merged.map((x) => x.id)).toEqual(["a", "b", "c"]);
    expect(merged[1].body).toBe("new");
  });

  it("adds a created reply to its thread once and counts it once", () => {
    const roots = [c("root", { reply_count: 1 })];
    const reply = c("r2", { parent_id: "root", reply_to_id: "r1" });
    const first = addReply(roots, {}, reply);
    expect(first.roots[0].reply_count).toBe(2);
    expect(first.threads.root.open).toBe(true);
    const again = addReply(first.roots, first.threads, reply);
    expect(again.roots[0].reply_count).toBe(2);
    expect(again.threads.root.replies).toHaveLength(1);
  });

  it("removes a reply and decrements its root", () => {
    const reply = c("r1", { parent_id: "root" });
    const state = removeComment([c("root", { reply_count: 1 })], { root: { ...emptyThread(), replies: [reply] } }, reply);
    expect(state.roots[0].reply_count).toBe(0);
    expect(state.threads.root.replies).toEqual([]);
  });

  it("removes a root together with its thread", () => {
    const state = removeComment([c("root"), c("other")], { root: emptyThread() }, c("root"));
    expect(state.roots.map((x) => x.id)).toEqual(["other"]);
    expect(state.threads.root).toBeUndefined();
  });

  it("replaces an edited reply in its thread", () => {
    const reply = c("r1", { parent_id: "root" });
    const state = replaceComment([c("root")], { root: { ...emptyThread(), replies: [reply] } }, { ...reply, body: "edited" });
    expect(state.threads.root.replies[0].body).toBe("edited");
  });
});

describe("reaction counts", () => {
  it("moves one count when the reaction changes", () => {
    expect(applyReactionChange({ like: 2 }, "like", "love")).toEqual({ like: 1, love: 1 });
    expect(applyReactionChange({ like: 1 }, "like", null)).toEqual({});
    expect(applyReactionChange({}, null, "wow")).toEqual({ wow: 1 });
  });

  it("orders the summary by count, then catalogue order", () => {
    expect(topReactions({ haha: 1, like: 3, love: 3, sad: 2 })).toEqual(["like", "love", "sad"]);
    expect(topReactions({ bogus: 9, like: 0 })).toEqual([]);
  });
});

describe("postService comment endpoints", () => {
  it("pages replies from the thread root", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({
      data: { data: [], page: { next_cursor: null, prev_cursor: null, has_more: false } },
    });
    await postService.replies("root-1", "cur");
    expect(get).toHaveBeenCalledWith("/comments/root-1/replies/", { params: { cursor: "cur" } });
  });

  it("returns the post's new count after a delete", async () => {
    vi.spyOn(api, "delete").mockResolvedValue({ data: { data: { comment_id: "c1", comment_count: 4 } } });
    expect(await postService.deleteComment("c1")).toEqual({ comment_id: "c1", comment_count: 4 });
  });

  it("follows empty share pages until something visible turns up", async () => {
    const page = (data: unknown[], next: string | null) => ({
      data: { data, page: { next_cursor: next, prev_cursor: null, has_more: !!next } },
    });
    const get = vi
      .spyOn(api, "get")
      .mockResolvedValueOnce(page([], "c2"))
      .mockResolvedValueOnce(page([{ account_id: "a", share_post_id: "s" }], null));
    const result = await postService.shares("p1");
    expect(get).toHaveBeenCalledTimes(2);
    expect(result.data).toHaveLength(1);
  });

  it("filters who reacted by type", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({
      data: { data: [], page: { next_cursor: null, prev_cursor: null, has_more: false } },
    });
    await postService.reactions("p1", "love");
    expect(get).toHaveBeenCalledWith("/posts/p1/reactions/", { params: { type: "love", cursor: undefined } });
  });
});
