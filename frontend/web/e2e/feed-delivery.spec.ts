import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import AxeBuilder from "@axe-core/playwright";
import { type Browser, type Page, expect, request, test } from "@playwright/test";

import { API, BASE_URL, useLocale } from "./helpers";

// Tara Intelligence R2, track B (08 §7.4-7.12, WP 4c-B3): Home's delivery on the
// preview build, as a real seeded account (the dev dataset; many feed rows).
// The account is a seed account from .seed-state/manifest.json; its e-mail and
// password are never printed.

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const T = {
  ar: { retry: "تعذّر التحميل، حاول تاني", retryButton: "حاول تاني", end: "خلّصت كل الجديد" },
  en: { retry: "Couldn't load, try again", retryButton: "Try again", end: "You're all caught up" },
} as const;

function seedLogin(): { email: string; password: string } {
  const manifest = JSON.parse(readFileSync(join(ROOT, ".seed-state", "manifest.json"), "utf8"));
  const emails = (Object.values(manifest.accounts) as Array<{ email: string }>).map((a) => a.email).sort();
  const src = readFileSync(join(ROOT, "scripts", "seed", "seed_dataset.py"), "utf8");
  const fallback = /DEFAULT_PASSWORD = os\.getenv\("TARA_SEED_PASSWORD", "([^"]+)"\)/.exec(src)?.[1] ?? "";
  return { email: emails[0], password: process.env.TARA_SEED_PASSWORD || fallback };
}

let seedTokens: { access: string; refresh: string } | null = null;
async function seededPage(browser: Browser, lang: "ar" | "en"): Promise<Page> {
  if (!seedTokens) {
    const anon = await request.newContext();
    const res = await anon.post(`${API}/auth/login/`, { data: seedLogin() });
    expect(res.ok(), "seed account login (is the seed dataset loaded?)").toBe(true);
    const { data } = await res.json();
    seedTokens = { access: data.access_token, refresh: data.refresh_token };
    await anon.dispose();
  }
  // Every test opens `/home?mode=recent`: a `?mode=` link is not remembered, so the
  // seed account's own settings stay untouched.
  const context = await browser.newContext({ baseURL: BASE_URL, serviceWorkers: "block" });
  await context.addInitScript(
    ([access, refresh]) => {
      if (sessionStorage.getItem("e2e.seeded")) return;
      sessionStorage.setItem("e2e.seeded", "1");
      localStorage.setItem("tara.access", access);
      localStorage.setItem("tara.refresh", refresh);
    },
    [seedTokens.access, seedTokens.refresh],
  );
  const page = await context.newPage();
  await useLocale(page, lang);
  return page;
}

async function seriousViolations(page: Page, selector: string) {
  const result = await new AxeBuilder({ page }).include(selector).withTags(["wcag2a", "wcag2aa"]).analyze();
  return result.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes[0]?.target}`);
}

const NEXT_PAGE = /\/api\/v1\/feed\/\?(?=.*cursor=)(?!.*peek=1)/;
const FIRST_PAGE = /\/api\/v1\/feed\/\?(?!.*cursor=)(?!.*peek=1)/;

for (const lang of ["ar", "en"] as const) {
  test.describe(`feed delivery (${lang})`, () => {
    test("card skeletons show before data, then the first page is the server's first_page_size", async ({ browser }) => {
      const page = await seededPage(browser, lang);
      let items = -1;
      await page.route(FIRST_PAGE, async (route) => {
        await new Promise((r) => setTimeout(r, 1500));
        const res = await route.fetch();
        const body = await res.json();
        items = body.data.length;
        await route.fulfill({ response: res, json: body });
      });
      await page.goto("/home?mode=recent");
      const skeletons = page.getByTestId("feed-first-loading");
      await expect(skeletons).toBeVisible();
      await expect(skeletons.getByTestId("feed-card-skeleton")).toHaveCount(3);
      await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
      await expect(page.locator("[data-feed-item]").first()).toBeVisible({ timeout: 20_000 });
      const delivery = await page.evaluate(() => JSON.parse(sessionStorage.getItem("tara.delivery.v1") || "{}"));
      expect(delivery.home?.first_page_size, "meta.delivery reached the web").toBeGreaterThan(0);
      expect(items).toBe(delivery.home.first_page_size);
      await page.context().close();
    });

    test("a failing next page retries by itself, then shows the retry card; its button recovers", async ({ browser }) => {
      test.setTimeout(90_000);
      const page = await seededPage(browser, lang);
      let fail = true;
      let attempts = 0;
      await page.route(NEXT_PAGE, (route) => {
        attempts++;
        return fail ? route.abort("failed") : route.continue();
      });
      await page.goto("/home?mode=recent");
      await expect(page.locator("[data-feed-item]").first()).toBeVisible({ timeout: 20_000 });
      const before = await page.locator("[data-feed-item]").count();
      const card = page.getByTestId("feed-retry");
      await expect(async () => {
        await page.mouse.wheel(0, 3000);
        await expect(card).toBeVisible({ timeout: 1000 });
      }).toPass({ timeout: 40_000 });
      expect(attempts).toBe(4); // the first try and next_page_retries (3) retries, 1 s / 2 s / 4 s apart
      await expect(card).toContainText(T[lang].retry);
      await expect(page.locator("[aria-live='polite'][aria-relevant='additions'] > div")).toHaveCount(0); // no toast
      expect(await seriousViolations(page, '[data-testid="feed-retry"]')).toEqual([]);
      // The icon is a circular arrow: not mirrored. The card follows the page direction.
      expect(await card.evaluate((el) => getComputedStyle(el).direction)).toBe(lang === "ar" ? "rtl" : "ltr");
      fail = false;
      await card.getByRole("button", { name: T[lang].retryButton }).click();
      await expect(card).toBeHidden();
      await expect.poll(() => page.locator("[data-feed-item]").count(), { timeout: 15_000 }).toBeGreaterThan(before);
      await page.context().close();
    });

    test("the end card shows when the server says has_more=false", async ({ browser }) => {
      const page = await seededPage(browser, lang);
      await page.route(FIRST_PAGE, async (route) => {
        const res = await route.fetch();
        const body = await res.json();
        await route.fulfill({ response: res, json: { ...body, page: { ...body.page, next_cursor: null, has_more: false } } });
      });
      await page.goto("/home?mode=recent");
      const end = page.getByTestId("feed-end");
      await expect(end).toBeVisible({ timeout: 20_000 });
      await expect(end).toContainText(T[lang].end);
      await expect(end.getByTestId("feed-end-explore")).toHaveAttribute("href", "/search");
      await expect(end.getByTestId("feed-end-reels")).toHaveAttribute("href", "/reels");
      expect(await seriousViolations(page, '[data-testid="feed-end"]')).toEqual([]);
      // Directional chevrons point along the reading direction.
      const t = await end.locator("svg.rtl\\:-scale-x-100").first().evaluate((el) => getComputedStyle(el).transform);
      expect(t).toBe(lang === "ar" ? "matrix(-1, 0, 0, 1, 0, 0)" : "none");
      await page.context().close();
    });

    test("a reload comes back to the same card (±1)", async ({ browser }) => {
      test.setTimeout(90_000);
      const page = await seededPage(browser, lang);
      await page.goto("/home?mode=recent");
      await expect(page.locator("[data-feed-item]").first()).toBeVisible({ timeout: 20_000 });
      for (let i = 0; i < 6; i++) {
        await page.mouse.wheel(0, 900);
        await page.waitForTimeout(400);
      }
      await page.waitForTimeout(1500);
      const top = () =>
        page.evaluate(() => {
          const items = [...document.querySelectorAll<HTMLElement>("[data-feed-item]")];
          const hit = items.find((n) => n.getBoundingClientRect().bottom > 65);
          return { id: hit?.dataset.feedItem ?? null, ids: items.map((n) => n.dataset.feedItem ?? "") };
        });
      const before = await top();
      expect(before.id).not.toBeNull();
      expect(before.ids.indexOf(before.id!)).toBeGreaterThan(0);
      const reload = page.waitForRequest((r) => FIRST_PAGE.test(r.url()));
      await page.reload();
      expect(new URL((await reload).url()).searchParams.get("entry")).toBe("reload");
      await expect(page.locator(`[data-feed-item="${before.id}"]`)).toBeAttached({ timeout: 20_000 });
      await page.waitForTimeout(2500);
      const after = await top();
      const distance = Math.abs(before.ids.indexOf(after.id!) - before.ids.indexOf(before.id!));
      expect(distance).toBeLessThanOrEqual(1);
      await page.context().close();
    });

    test("after scrolling through several pages, no more than 6 <video> are mounted and ids never repeat", async ({ browser }) => {
      test.setTimeout(120_000);
      const page = await seededPage(browser, lang);
      let nextPages = 0;
      page.on("requestfinished", (r) => {
        if (NEXT_PAGE.test(r.url())) nextPages++;
      });
      await page.goto("/home?mode=recent");
      await expect(page.locator("[data-feed-item]").first()).toBeVisible({ timeout: 20_000 });
      for (let i = 0; i < 120 && nextPages < 5; i++) {
        await page.mouse.wheel(0, 900);
        await page.waitForTimeout(250);
      }
      await page.waitForTimeout(1500);
      expect(nextPages).toBeGreaterThanOrEqual(3);
      expect(await page.locator("video").count()).toBeLessThanOrEqual(6);
      const ids = await page.locator("[data-feed-item]").evaluateAll((n) => n.map((e) => (e as HTMLElement).dataset.feedItem));
      expect(ids.length - new Set(ids).size).toBe(0);
      await page.context().close();
    });
  });
}
