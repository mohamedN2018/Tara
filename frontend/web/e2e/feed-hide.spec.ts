import { type APIRequestContext, expect, test } from "@playwright/test";

import { API, apiAs, befriend, sharedAccounts, unique } from "./helpers";

// Plan 08, track 2A: hide a post with a reason, undo it, snooze its author (API level).

type FeedBody = { data: { post_id: string }[]; page: { next_cursor: string | null }; mode: string };

async function feedIds(api: APIRequestContext, mode: string): Promise<string[]> {
  const res = await api.get(`${API}/feed/`, { params: { mode, limit: 100 } });
  expect(res.status()).toBe(200);
  const body = (await res.json()) as FeedBody;
  expect(body.mode).toBe(mode);
  return body.data.map((i) => i.post_id);
}

test("hide, undo and snooze keep a post out of every feed mode", async () => {
  const { a, b } = await sharedAccounts();
  await befriend(a, b);
  const aApi = await apiAs(a);
  const bApi = await apiAs(b);
  // A snooze left by an earlier run.
  await aApi.delete(`${API}/feed/snooze/${b.id}/`);

  const created = await bApi.post(`${API}/posts/`, {
    data: { body: `منشور للإخفاء ${unique()}`, audience: "public", type: "text" },
  });
  expect(created.ok()).toBe(true);
  const postId = ((await created.json()) as { data: { id: string } }).data.id;

  // Fan-out to the feed is asynchronous.
  await expect.poll(async () => (await feedIds(aApi, "recent")).includes(postId), { timeout: 20_000 }).toBe(true);

  const bad = await aApi.post(`${API}/feed/hide/`, { data: { post_id: postId, reason: "boring" } });
  expect(bad.status()).toBe(400);
  const stranger = await aApi.post(`${API}/feed/hide/`, { data: { post_id: crypto.randomUUID(), reason: "spam" } });
  expect(stranger.status()).toBe(404);

  const hidden = await aApi.post(`${API}/feed/hide/`, { data: { post_id: postId, reason: "not_interested" } });
  expect(hidden.status()).toBe(201);
  const hide = ((await hidden.json()) as { data: { post_id: string; reason: string; hidden_at: string } }).data;
  expect(hide).toMatchObject({ post_id: postId, reason: "not_interested" });
  expect(hide.hidden_at).toBeTruthy();
  // Idempotent.
  expect((await aApi.post(`${API}/feed/hide/`, { data: { post_id: postId, reason: "not_interested" } })).status()).toBe(201);

  for (const mode of ["recent", "for_you", "following", "favorites"]) {
    expect(await feedIds(aApi, mode)).not.toContain(postId);
  }
  // Only the viewer's feed changes.
  expect(await feedIds(bApi, "recent")).toContain(postId);

  expect((await aApi.delete(`${API}/feed/hide/${postId}/`)).status()).toBe(204);
  expect(await feedIds(aApi, "recent")).toContain(postId);
  expect(await feedIds(aApi, "for_you")).toContain(postId);

  const snoozed = await aApi.post(`${API}/feed/snooze/`, { data: { author_id: b.id } });
  expect(snoozed.status()).toBe(201);
  const snooze = ((await snoozed.json()) as { data: { author_id: string; until: string } }).data;
  expect(snooze.author_id).toBe(b.id);
  const days = (Date.parse(snooze.until) - Date.now()) / 86_400_000;
  expect(days).toBeGreaterThan(29.9);
  expect(days).toBeLessThanOrEqual(30);
  expect(await feedIds(aApi, "recent")).not.toContain(postId);
  const list = (await (await aApi.get(`${API}/feed/snoozes/`)).json()) as { data: { author_id: string }[] };
  expect(list.data.map((s) => s.author_id)).toContain(b.id);

  expect((await aApi.post(`${API}/feed/snooze/`, { data: { author_id: a.id } })).status()).toBe(400);
  expect((await aApi.delete(`${API}/feed/snooze/${b.id}/`)).status()).toBe(204);
  expect(await feedIds(aApi, "recent")).toContain(postId);

  await aApi.dispose();
  await bApi.dispose();
});

test("for you pages carry a signed cursor and a bad one is refused", async () => {
  const { a } = await sharedAccounts();
  const api = await apiAs(a);
  const first = await api.get(`${API}/feed/`, { params: { mode: "for_you", limit: 1 } });
  expect(first.status()).toBe(200);
  const body = (await first.json()) as FeedBody;
  expect(body.mode).toBe("for_you");
  if (body.page.next_cursor) {
    const next = await api.get(`${API}/feed/`, { params: { mode: "for_you", limit: 1, cursor: body.page.next_cursor } });
    expect(next.status()).toBe(200);
    const ids = ((await next.json()) as FeedBody).data.map((i) => i.post_id);
    expect(ids).not.toContain(body.data[0]?.post_id);
  }
  const forged = await api.get(`${API}/feed/`, { params: { mode: "for_you", cursor: "forged" } });
  expect(forged.status()).toBe(404);
  expect((await api.get(`${API}/feed/`, { params: { mode: "best" } })).status()).toBe(400);
  await api.dispose();
});
