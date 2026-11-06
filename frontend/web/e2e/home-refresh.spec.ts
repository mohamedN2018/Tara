import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, type Browser, type BrowserContextOptions, type Page, expect, request, test } from "@playwright/test";

import { type Account, API, BASE_URL, PASSWORD, apiAs, befriend, sharedAccounts, unique, useLocale } from "./helpers";

// Tara Intelligence R3, track B (06 §6.1-6.2, 07 WP 4b.7/4b.8, 08 §7.6): Home after
// time away, the "new posts" pill, pull-to-refresh, For You reload, and the
// new-since divider, on the preview build against the real stack. The viewer is the
// shared e2e account a; its friend b posts real posts through the API.
// Time away is simulated with Playwright's clock in the page (never the server's).

const T = {
  ar: { newSince: "جديد من آخر زيارة", caughtUp: "انت كده شفت الجديد" },
  en: { newSince: "New since your last visit", caughtUp: "You're all caught up" },
} as const;
const FIRST_PAGE = /\/api\/v1\/feed\/\?(?!.*cursor=)(?!.*peek=1)/;
const PEEK = /\/api\/v1\/feed\/\?(?=.*peek=1)/;
const MIN = 60_000;

let accounts: { a: Account; b: Account };
let bApi: APIRequestContext;
let aApi: APIRequestContext;

async function feedIds(api: APIRequestContext): Promise<string[]> {
  const res = await api.get(`${API}/feed/`, { params: { mode: "recent", limit: 50 } });
  expect(res.status()).toBe(200);
  return ((await res.json()) as { data: { post_id: string }[] }).data.map((i) => i.post_id);
}

/**
 * b posts; resolves once the post reached a's feed (fan-out is asynchronous). Checked
 * with a's peek, spaced out: first pages are throttled per account (30 a minute) and
 * the browser under test needs them.
 */
async function friendPosts(label: string): Promise<string> {
  const since = new Date(Date.now() - 60_000).toISOString();
  const created = await bApi.post(`${API}/posts/`, { data: { body: `${label} ${unique()}`, audience: "friends", type: "text" } });
  expect(created.ok(), await created.text()).toBe(true);
  const id = ((await created.json()) as { data: { id: string } }).data.id;
  await expect
    .poll(
      async () => {
        const res = await aApi.get(`${API}/feed/`, { params: { mode: "recent", peek: 1, since } });
        if (res.status() !== 200) return false;
        return ((await res.json()) as { ids?: string[] }).ids?.includes(id) ?? false;
      },
      { timeout: 30_000, intervals: [1000, 2000, 3000, 4000] },
    )
    .toBe(true);
  return id;
}

/**
 * First pages are throttled per account (`session.rate.first_page_per_min`, 30): other
 * specs share account a, so wait until a first page is allowed again (a refused one
 * does not count against the quota) before a test that loads Home.
 */
async function awaitQuota() {
  await expect
    .poll(async () => (await aApi.get(`${API}/feed/`, { params: { mode: "recent", limit: 1 } })).status(), {
      timeout: 90_000,
      intervals: [2000, 5000, 10_000],
    })
    .toBe(200);
}

async function pageFor(browser: Browser, lang: "ar" | "en", options: BrowserContextOptions = {}): Promise<Page> {
  const anon = await request.newContext();
  const res = await anon.post(`${API}/auth/login/`, { data: { email: accounts.a.email, password: PASSWORD } });
  expect(res.ok()).toBe(true);
  const { data } = await res.json();
  await anon.dispose();
  const context = await browser.newContext({ baseURL: BASE_URL, serviceWorkers: "block", ...options });
  await context.addInitScript(
    ([access, refresh]) => {
      if (sessionStorage.getItem("e2e.seeded")) return;
      sessionStorage.setItem("e2e.seeded", "1");
      localStorage.setItem("tara.access", access);
      localStorage.setItem("tara.refresh", refresh);
    },
    [data.access_token, data.refresh_token],
  );
  const page = await context.newPage();
  await useLocale(page, lang);
  return page;
}

const rendered = (page: Page) => page.evaluate(() => [...document.querySelectorAll<HTMLElement>("[data-feed-item]")].map((n) => n.dataset.feedItem ?? ""));

async function away(page: Page, ms: number) {
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.clock.fastForward(ms);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

test.beforeAll(async () => {
  test.setTimeout(180_000);
  const shared = await sharedAccounts();
  accounts = { a: shared.a, b: shared.b };
  await befriend(accounts.a, accounts.b);
  aApi = await apiAs(accounts.a);
  bApi = await apiAs(accounts.b);
  await aApi.delete(`${API}/feed/snooze/${accounts.b.id}/`); // a snooze left by another spec
  await awaitQuota();
  // Enough rows in a's feed to scroll (real posts by the e2e friend).
  const have = (await feedIds(aApi)).length;
  for (let i = have; i < 14; i++) {
    const r = await bApi.post(`${API}/posts/`, { data: { body: `e2e r3 filler ${unique()}`, audience: "friends", type: "text" } });
    expect(r.ok()).toBe(true);
  }
  await expect.poll(async () => (await feedIds(aApi)).length, { timeout: 30_000 }).toBeGreaterThanOrEqual(14);
});

test.afterAll(async () => {
  await aApi?.dispose();
  await bApi?.dispose();
});

test.beforeEach(async () => {
  test.setTimeout(180_000);
  await awaitQuota();
});

for (const lang of ["ar", "en"] as const) {
  test.describe(`home refresh (${lang})`, () => {
    test("a friend posts mid-session: back after 10 min while scrolled shows the pill with peek's new_count; nothing reorders", async ({ browser }) => {
      test.setTimeout(120_000);
      const page = await pageFor(browser, lang);
      await page.clock.install();
      const peeks: Array<{ new_count: number; ids?: string[]; new_count_capped?: boolean }> = [];
      page.on("response", async (r) => {
        if (PEEK.test(r.url()) && r.status() === 200) peeks.push(await r.json());
      });
      await page.goto("/home?mode=recent");
      await expect(page.locator("[data-feed-item]").nth(3)).toBeVisible({ timeout: 20_000 });
      await page.mouse.wheel(0, 900);
      await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(300);
      await page.waitForTimeout(500);
      const before = await rendered(page);
      const scrollBefore = await page.evaluate(() => window.scrollY);

      const fresh = await friendPosts(lang === "ar" ? "منشور جديد أثناء الزيارة" : "posted mid-session");
      expect(before).not.toContain(fresh);
      await away(page, 11 * MIN);

      const pill = page.getByTestId("new-posts-pill").getByRole("button");
      await expect(pill).toBeVisible({ timeout: 20_000 });
      await expect.poll(() => peeks.length).toBeGreaterThan(0);
      const last = peeks.at(-1)!;
      const held = (last.ids ?? []).filter((id) => before.includes(id)).length;
      expect(held).toBe(0);
      expect(last.ids).toContain(fresh);
      expect(Number(await pill.getAttribute("data-count"))).toBe(last.new_count);
      // The words are the server's number (Arabic says one and two without a numeral).
      if (!last.new_count_capped && (lang === "en" || last.new_count > 2)) await expect(pill).toContainText(String(last.new_count));
      // 0 reordering of the rendered cards, the list and the scroll unchanged.
      expect(await rendered(page)).toEqual(before);
      expect(Math.abs((await page.evaluate(() => window.scrollY)) - scrollBefore)).toBeLessThanOrEqual(2);
      // RTL: the pill follows the page direction; its arrow points up in both.
      expect(await pill.evaluate((el) => getComputedStyle(el).direction)).toBe(lang === "ar" ? "rtl" : "ltr");
      const axe = await new AxeBuilder({ page }).include('[data-testid="new-posts-pill"]').withTags(["wcag2a", "wcag2aa"]).analyze();
      expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
      // Showing them: the new post on top, no duplicate id.
      await pill.click();
      await expect(page.locator(`[data-feed-item="${fresh}"]`)).toBeAttached();
      const after = await rendered(page);
      expect(new Set(after).size).toBe(after.length);
      await page.context().close();
    });

    test("back after 30 min at the top: a silent first page with entry=return, no duplicate ids", async ({ browser }) => {
      test.setTimeout(120_000);
      const page = await pageFor(browser, lang);
      await page.clock.install();
      await page.goto("/home?mode=recent");
      await expect(page.locator("[data-feed-item]").first()).toBeVisible({ timeout: 20_000 });
      const fresh = await friendPosts(lang === "ar" ? "منشور بعد نص ساعة" : "after half an hour");
      const refetch = page.waitForRequest((r) => FIRST_PAGE.test(r.url()) && new URL(r.url()).searchParams.get("entry") === "return");
      await away(page, 31 * MIN);
      const req = await refetch;
      expect(new URL(req.url()).searchParams.get("sid")).toMatch(/^[0-9a-f-]{36}$/);
      await expect(page.locator("[data-feed-item]").first()).toHaveAttribute("data-feed-item", fresh, { timeout: 20_000 });
      const ids = await rendered(page);
      expect(new Set(ids).size).toBe(ids.length);
      await expect(page.getByTestId("feed-first-loading")).toHaveCount(0); // silent: no skeleton flash
      await page.context().close();
    });

    test("pull-to-refresh at the top inserts the new post above; the card under the finger stays (±8 px); no duplicates", async ({ browser }) => {
      test.setTimeout(120_000);
      const page = await pageFor(browser, lang, { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
      await page.goto("/home?mode=recent");
      await expect(page.locator("[data-feed-item]").nth(1)).toBeVisible({ timeout: 20_000 });
      await page.waitForTimeout(1500); // hydration and rails settle
      const fresh = await friendPosts(lang === "ar" ? "منشور للسحب" : "pull me");
      const under = await page.evaluate(() => {
        const n = [...document.querySelectorAll<HTMLElement>("[data-feed-item]")].find((x) => x.getBoundingClientRect().bottom > 65);
        return n ? { id: n.dataset.feedItem!, top: n.getBoundingClientRect().top } : null;
      });
      expect(under).not.toBeNull();
      const pulled = page.waitForResponse((r) => FIRST_PAGE.test(r.url()) && new URL(r.url()).searchParams.get("entry") === "pull");
      await page.evaluate(async () => {
        const touch = (y: number) => new Touch({ identifier: 1, target: document.body, clientX: 200, clientY: y });
        const fire = (type: string, y: number | null) =>
          document.dispatchEvent(
            new TouchEvent(type, { bubbles: true, cancelable: true, touches: y === null ? [] : [touch(y)], changedTouches: [touch(y ?? 400)] }),
          );
        fire("touchstart", 150);
        for (let y = 170; y <= 450; y += 40) {
          fire("touchmove", y);
          await new Promise((r) => setTimeout(r, 16));
        }
        fire("touchend", null);
      });
      await pulled;
      await expect(page.locator(`[data-feed-item="${fresh}"]`)).toBeAttached({ timeout: 20_000 });
      await page.waitForTimeout(800);
      const top = await page.evaluate((id) => {
        const n = [...document.querySelectorAll<HTMLElement>("[data-feed-item]")].find((x) => x.dataset.feedItem === id);
        return n ? n.getBoundingClientRect().top : null;
      }, under!.id);
      expect(top).not.toBeNull();
      expect(Math.abs(top! - under!.top)).toBeLessThanOrEqual(8);
      const ids = await rendered(page);
      expect(new Set(ids).size).toBe(ids.length);
      expect(ids.indexOf(fresh)).toBeLessThan(ids.indexOf(under!.id)); // above it
      await page.context().close();
    });

    test("For You: a reload comes back to the same card (±1)", async ({ browser }) => {
      test.setTimeout(120_000);
      const page = await pageFor(browser, lang);
      await page.goto("/home?mode=for_you");
      await expect(page.locator("[data-feed-item]").nth(4)).toBeVisible({ timeout: 20_000 });
      await page.waitForTimeout(1500);
      await page.evaluate(() => {
        const n = document.querySelectorAll<HTMLElement>("[data-feed-item]")[3];
        window.scrollTo({ top: n.getBoundingClientRect().top + window.scrollY - 80, behavior: "instant" as ScrollBehavior });
      });
      await page.waitForTimeout(800);
      const top = () =>
        page.evaluate(() => {
          const items = [...document.querySelectorAll<HTMLElement>("[data-feed-item]")];
          const hit = items.find((n) => n.getBoundingClientRect().bottom > 65);
          return { id: hit?.dataset.feedItem ?? null, ids: items.map((n) => n.dataset.feedItem ?? "") };
        });
      const before = await top();
      expect(before.ids.indexOf(before.id!)).toBeGreaterThan(0);
      const reload = page.waitForRequest((r) => FIRST_PAGE.test(r.url()));
      await page.reload();
      const url = new URL((await reload).url());
      expect(url.searchParams.get("entry")).toBe("reload");
      expect(url.searchParams.get("mode")).toBe("for_you");
      await expect(page.locator(`[data-feed-item="${before.id}"]`)).toBeAttached({ timeout: 20_000 });
      await page.waitForTimeout(2500);
      const after = await top();
      expect(Math.abs(before.ids.indexOf(after.id!) - before.ids.indexOf(before.id!))).toBeLessThanOrEqual(1);
      await page.context().close();
    });

    test("the new-since divider and the caught-up marker render where the server's meta puts them", async ({ browser }) => {
      // The rows are the server's; only meta.visit / caught_up_index are set here (the
      // server path, a 3-day return, is covered by the backend's test_new_since.py and
      // the web's newSinceDivider.spec.ts: the dev stack runs without the test clock).
      const page = await pageFor(browser, lang);
      await page.route(FIRST_PAGE, async (route) => {
        const res = await route.fetch();
        const body = await res.json();
        const meta = {
          ...body.meta,
          visit: { kind: "returning", since: new Date(Date.now() - 3 * 86_400_000).toISOString(), new_count: 3, anchor_index: 3, min_to_show: 3 },
          caught_up_index: 3,
        };
        await route.fulfill({ response: res, json: { ...body, meta } });
      });
      await page.goto("/home?mode=recent");
      const divider = page.getByTestId("new-since-divider");
      const marker = page.getByTestId("caught-up-marker");
      await expect(divider).toBeVisible({ timeout: 20_000 });
      await expect(divider).toHaveText(T[lang].newSince);
      await expect(marker).toHaveText(T[lang].caughtUp);
      const order = await page.evaluate(() =>
        [...document.querySelectorAll<HTMLElement>("[data-feed-item], [data-testid='new-since-divider'], [data-testid='caught-up-marker']")].map(
          (n) => (n.dataset.feedItem ? "post" : n.dataset.testid),
        ),
      );
      expect(order.slice(0, 5)).toEqual(["post", "post", "post", "new-since-divider", "caught-up-marker"]);
      expect(await divider.evaluate((el) => getComputedStyle(el).direction)).toBe(lang === "ar" ? "rtl" : "ltr");
      const axe = await new AxeBuilder({ page }).include('[data-testid="new-since-divider"]').include('[data-testid="caught-up-marker"]').withTags(["wcag2a", "wcag2aa"]).analyze();
      expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
      await page.context().close();
    });
  });
}
