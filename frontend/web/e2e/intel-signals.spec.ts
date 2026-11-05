import { type Page, type Request, expect, test } from "@playwright/test";

import { API, apiAs, befriend, pageAs, sharedAccounts, unique, useLocale } from "./helpers";

// Tara Intelligence WP 2.8: the web tracker. The signals endpoint is feed's
// (WP 2.3); here it is answered by the test so the payload the browser builds is
// what is checked: ids and enums only, a batch and session id, no cfg/variant.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

type Batch = { batch_id: string; session_id: string; events: Record<string, unknown>[] };

async function captureSignals(page: Page) {
  const batches: Batch[] = [];
  const requests: Request[] = [];
  await page.route("**/api/v1/feed/signals/", async (route) => {
    requests.push(route.request());
    batches.push(route.request().postDataJSON() as Batch);
    await route.fulfill({ status: 202, contentType: "application/json", body: '{"data":{"accepted":true}}' });
  });
  return { batches, requests, events: () => batches.flatMap((b) => b.events) };
}

/** The tab goes to the background: the tracker flushes with keepalive. */
async function hideTab(page: Page) {
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

for (const lang of ["ar", "en"] as const) {
  test(`home impressions and opens reach the signals endpoint, ids only (${lang})`, async ({ browser }) => {
    test.setTimeout(120_000);
    const { a, b } = await sharedAccounts();
    await befriend(a, b);
    const marker = `signals-${lang}-${unique()}`;
    const author = await apiAs(b);
    const created = await author.post(`${API}/posts/`, { data: { body: `منشور ${marker}`, audience: "public", type: "text" } });
    expect(created.ok()).toBe(true);
    const postId = (await created.json()).data.id as string;
    await author.dispose();

    const page = await pageAs(browser, a);
    await useLocale(page, lang);
    const signals = await captureSignals(page);
    const card = page.locator("article").filter({ hasText: marker });
    // Fan-out to the reader's feed is asynchronous.
    await expect
      .poll(
        async () => {
          await page.goto("/home");
          await page.locator("[data-feed-item]").first().waitFor();
          return card.count();
        },
        { timeout: 60_000 },
      )
      .toBe(1);
    await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
    await card.scrollIntoViewIfNeeded();
    await page.waitForTimeout(1_600); // half on screen for a full second
    // Opening the comments is an open.
    await card.getByRole("button", { name: lang === "ar" ? /تعليق/ : /comment/i }).first().click();
    await page.waitForTimeout(300);
    await hideTab(page);

    await expect.poll(() => signals.events().length, { timeout: 15_000 }).toBeGreaterThan(0);
    const item = `post:${postId}`;
    const mine = signals.events().filter((e) => e.item === item);
    expect(mine.map((e) => e.t).sort()).toEqual(["feed_impression", "post_open"]);
    for (const batch of signals.batches) {
      expect(batch.batch_id).toMatch(UUID);
      expect(batch.session_id).toMatch(UUID);
      expect(Object.keys(batch).sort()).toEqual(["batch_id", "events", "session_id"]);
      for (const e of batch.events) {
        expect(e).not.toHaveProperty("cfg");
        expect(e).not.toHaveProperty("variant");
        for (const key of Object.keys(e)) {
          expect(["id", "t", "item", "ts", "st", "surface", "pos", "watch_ms", "pos_ms", "play_index"]).toContain(key);
        }
        expect(String(e.id)).toMatch(UUID);
      }
    }
    expect(JSON.stringify(signals.batches)).not.toContain(a.email);
    expect(signals.requests[0].headers()["authorization"]).toMatch(/^Bearer /);

    // One impression per (session, item): coming back and scrolling again adds none.
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await card.scrollIntoViewIfNeeded();
    await page.waitForTimeout(1_500);
    await hideTab(page);
    await page.waitForTimeout(500);
    expect(signals.events().filter((e) => e.item === item && e.t === "feed_impression")).toHaveLength(1);
  });
}

test("a reel counts as viewed only after a second of play, with its watch time", async ({ browser }) => {
  test.setTimeout(120_000);
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  const signals = await captureSignals(page);
  const viewCall = page.waitForRequest((r) => r.method() === "POST" && /\/reels\/[0-9a-f-]{36}\/view\/$/.test(new URL(r.url()).pathname), {
    timeout: 60_000,
  });
  viewCall.catch(() => {}); // a skipped test ends before it
  await page.goto("/reels");
  const slide = page.locator("[data-testid=reel-slide][aria-current=true]");
  const shown = await slide
    .waitFor({ timeout: 30_000 })
    .then(() => true)
    .catch(() => false);
  test.skip(!shown, "no reel visible to this account");
  await expect(slide.getByTestId("reel-player")).toHaveAttribute("data-state", "ready", { timeout: 30_000 });
  // Started, but not yet a view: nothing is counted before a second of real play.
  const request = await viewCall;
  const reelId = request.url().match(/reels\/([0-9a-f-]{36})\/view/)?.[1];
  expect((request.postDataJSON() as { watch_ms: number }).watch_ms).toBeGreaterThanOrEqual(1000);
  const played = await slide.getByTestId("reel-video").evaluate((v: HTMLVideoElement) => v.currentTime);
  expect(played).toBeGreaterThan(0.9);
  await hideTab(page);
  await expect.poll(() => signals.events().filter((e) => e.item === `reel:${reelId}`).map((e) => e.t), { timeout: 15_000 }).toEqual(
    expect.arrayContaining(["video_start", "reel_view"]),
  );
});
