import { expect, test } from "@playwright/test";

import { API, apiAs, befriend, pageAs, sharedAccounts, unique, useLocale } from "./helpers";

// Tara Intelligence phase 4, track B: the five Home modes with Friends (WP 4.6),
// the mode remembered per account (a new browser opens on it), the read-only
// peek (WP 4.7) and "Why am I seeing this?" v2 from the server (WP 4.8).

const LABELS = {
  ar: { latest: "الأحدث", friends: "الأصدقاء", whyTitle: "لماذا ترى هذا المنشور", friendLine: "أنت صديق لـ" },
  en: { latest: "Latest", friends: "Friends", whyTitle: "Why you're seeing this post", friendLine: "You're friends with" },
} as const;

for (const lang of ["ar", "en"] as const) {
  test(`friends mode, remembered in a new browser, and why-this from the server (${lang})`, async ({ browser }) => {
    test.setTimeout(150_000);
    const { a, b } = await sharedAccounts();
    await befriend(a, b);
    const marker = `modes-${lang}-${unique()}`;
    const friendApi = await apiAs(b);
    const friendPost = await friendApi.post(`${API}/posts/`, { data: { body: `friend ${marker}`, audience: "public", type: "text" } });
    expect(friendPost.ok()).toBe(true);
    const friendPostId = (await friendPost.json()).data.id as string;
    await friendApi.dispose();
    const reader = await apiAs(a);
    const ownPost = await reader.post(`${API}/posts/`, { data: { body: `own ${marker}`, audience: "public", type: "text" } });
    const ownPostId = (await ownPost.json()).data.id as string;
    // Fan-out is asynchronous: wait for both rows in the reader's feed.
    await expect
      .poll(async () => {
        const res = await reader.get(`${API}/feed/`, { params: { mode: "recent", limit: 50 } });
        const ids = ((await res.json()) as { data: { post_id: string }[] }).data.map((i) => i.post_id);
        return ids.includes(friendPostId) && ids.includes(ownPostId);
      }, { timeout: 60_000 })
      .toBe(true);
    // Start this shared account on the default mode.
    expect((await reader.patch(`${API}/feed/preferences/`, { data: { default_mode: "recent" } })).ok()).toBe(true);

    const l = LABELS[lang];
    const page = await pageAs(browser, a);
    await useLocale(page, lang);
    await page.goto("/home");
    await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
    const modes = page.getByTestId("feed-modes");
    await expect(modes.getByRole("button", { name: l.latest })).toHaveAttribute("aria-pressed", "true");
    // The five modes (R3 adds a refresh control beside them, not a mode).
    await expect(modes.locator("button[aria-pressed]")).toHaveCount(5);

    // Friends: the friend's post, never the viewer's own.
    const remembered = page.waitForResponse((r) => r.url().includes("/feed/preferences/") && r.request().method() === "PATCH");
    await modes.getByRole("button", { name: l.friends }).click();
    expect((await remembered).status()).toBe(200);
    await expect(page).toHaveURL(/mode=friends/);
    const friendCard = page.locator(`[data-feed-item="${friendPostId}"]`);
    await expect(friendCard).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(`[data-feed-item="${ownPostId}"]`)).toHaveCount(0);

    // Why am I seeing this? The server explains the item it served to this viewer.
    await friendCard.getByTestId("post-menu").click();
    const why = page.waitForResponse((r) => r.url().includes(`/feed/why/post/${friendPostId}/`));
    await friendCard.getByTestId("menu-why").click();
    expect((await why).status()).toBe(200);
    const dialog = page.getByTestId("why-post");
    await expect(dialog.getByRole("heading", { name: l.whyTitle })).toBeVisible();
    await expect(dialog.getByTestId("why-factors")).toContainText(l.friendLine);
    await page.keyboard.press("Escape");

    // A new browser (no local copy) opens on the remembered mode.
    const fresh = await pageAs(browser, a);
    await useLocale(fresh, lang);
    await fresh.goto("/home");
    await expect(fresh.getByTestId("feed-modes").getByRole("button", { name: l.friends })).toHaveAttribute("aria-pressed", "true");
    await expect(fresh.locator(`[data-feed-item="${friendPostId}"]`)).toBeVisible({ timeout: 20_000 });
    await fresh.context().close();

    // Why is 404 for an item never served to this viewer, whatever it is.
    const notServed = await reader.get(`${API}/feed/why/post/${crypto.randomUUID()}/`);
    expect(notServed.status()).toBe(404);

    await reader.patch(`${API}/feed/preferences/`, { data: { default_mode: "recent" } });
    await reader.dispose();
    await page.context().close();
  });
}

test("a peek keeps the ranked session: page 2 reads it, no fallback", async () => {
  const { a } = await sharedAccounts();
  const reader = await apiAs(a);
  const first = (await (await reader.get(`${API}/feed/`, { params: { mode: "for_you", limit: 5 } })).json()) as {
    data: { post_id: string }[];
    page: { next_cursor: string | null };
    meta: { ad_slots: number[]; as_of: string };
  };
  expect(first.meta.ad_slots).toEqual([4]);
  test.skip(!first.page.next_cursor, "the reader's feed has a single page");
  const peek = await reader.get(`${API}/feed/`, { params: { mode: "for_you", peek: 1, since: first.meta.as_of } });
  expect(peek.ok()).toBe(true);
  const peeked = await peek.json();
  expect(peeked.peek).toBe(true);
  expect(peeked).not.toHaveProperty("sponsored");
  const second = await (await reader.get(`${API}/feed/`, { params: { mode: "for_you", cursor: first.page.next_cursor! } })).json();
  expect(second.page.fallback).toBe(false);
  const shown = new Set(first.data.map((i) => i.post_id));
  expect((second.data as { post_id: string }[]).filter((i) => shown.has(i.post_id))).toEqual([]);
  await reader.dispose();
});
