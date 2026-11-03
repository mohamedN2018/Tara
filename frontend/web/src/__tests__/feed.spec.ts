import { describe, expect, it, vi } from "vitest";

import { feedService, hydrateFeed, type FeedResponse } from "@/services/feed";
import { postService } from "@/services/post";
import type { CursorPage, FeedItem, Post } from "@/types";

const item = (id: string): FeedItem => ({
  id: `f-${id}`,
  post_id: id,
  author_id: "author",
  reason: "follow",
  snapshot: { excerpt: `excerpt ${id}`, audience: "friends", media_ids: [] },
  post_created_at: "2026-11-03T10:00:00Z",
});
const post = (id: string): Post => ({
  id,
  author_id: "author",
  author_type: "user",
  type: "text",
  body: `full ${id}`,
  audience: "public",
  media_ids: [],
  reaction_count: 3,
  comment_count: 1,
  share_count: 0,
  my_reaction: "love",
  is_saved: true,
  created_at: "2026-11-03T10:00:00Z",
});
const feedPage = (items: FeedItem[], next: string | null): FeedResponse => ({
  data: items,
  sponsored: null,
  page: { next_cursor: next, has_more: !!next },
});
const timeline = (posts: Post[], next: string | null): CursorPage<Post> => ({
  data: posts,
  page: { next_cursor: next, prev_cursor: null, has_more: !!next },
});

describe("hydrateFeed", () => {
  it("uses live posts, keeps feed order, and drops ids the batch omits", async () => {
    vi.spyOn(postService, "batch").mockResolvedValue([post("c"), post("a")]);
    const posts = await hydrateFeed([item("a"), item("b"), item("c")]);
    expect(posts.map((p) => p.id)).toEqual(["a", "c"]);
    expect(posts[0]).toMatchObject({ body: "full a", my_reaction: "love", is_saved: true });
    expect(posts[0].partial).toBeUndefined();
  });

  it("falls back to snapshots marked partial when the batch fails", async () => {
    vi.spyOn(postService, "batch").mockRejectedValue(new Error("down"));
    const [p] = await hydrateFeed([item("a")]);
    expect(p).toMatchObject({ id: "a", body: "excerpt a", audience: "friends", partial: true });
  });

  it("makes no request for an empty page", async () => {
    const batch = vi.spyOn(postService, "batch");
    await expect(hydrateFeed([])).resolves.toEqual([]);
    expect(batch).not.toHaveBeenCalled();
  });
});

describe("feedService.page", () => {
  it("keeps following the cursor past pages whose posts all disappeared", async () => {
    vi.spyOn(feedService, "home")
      .mockResolvedValueOnce(feedPage([item("gone")], "c1"))
      .mockResolvedValueOnce(feedPage([item("a")], "c2"));
    vi.spyOn(postService, "batch").mockImplementation(async (ids) =>
      ids.filter((id) => id !== "gone").map(post),
    );
    const page = await feedService.page();
    expect(page.posts.map((p) => p.id)).toEqual(["a"]);
    expect(page.nextCursor).toBe("c2");
    expect(page.hasMore).toBe(true);
  });
});

describe("postService.batch", () => {
  it("is called in chunks of 50", async () => {
    const { api } = await import("@/lib/api");
    const spy = vi.spyOn(api, "post").mockResolvedValue({ data: { data: [] } });
    await postService.batch(Array.from({ length: 120 }, (_, i) => `p${i}`));
    expect(spy.mock.calls.map((c) => (c[1] as { ids: string[] }).ids.length)).toEqual([50, 50, 20]);
  });
});

describe("postService.timelinePage", () => {
  it("follows next_cursor until a non-empty page", async () => {
    const byAuthor = vi
      .spyOn(postService, "byAuthor")
      .mockResolvedValueOnce(timeline([], "c1"))
      .mockResolvedValueOnce(timeline([], "c2"))
      .mockResolvedValueOnce(timeline([post("a")], "c3"));
    const page = await postService.timelinePage("author");
    expect(page.data.map((p) => p.id)).toEqual(["a"]);
    expect(page.page.next_cursor).toBe("c3");
    expect(byAuthor.mock.calls.map((c) => c[1])).toEqual([undefined, "c1", "c2"]);
  });

  it("stops when has_more is false", async () => {
    const byAuthor = vi
      .spyOn(postService, "byAuthor")
      .mockResolvedValueOnce(timeline([], "c1"))
      .mockResolvedValueOnce(timeline([], null));
    const page = await postService.timelinePage("author");
    expect(page.data).toEqual([]);
    expect(page.page.has_more).toBe(false);
    expect(byAuthor).toHaveBeenCalledTimes(2);
  });
});
