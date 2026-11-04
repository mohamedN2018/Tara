import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { API, apiAs, befriend, pageAs, sharedAccounts, unique, useLocale } from "./helpers";

// Track T4: the feed, post menu, saved collections, videos, feed preferences
// and the search home are reached from navigation (click paths, not typed
// URLs) in Arabic and English, act on real data, and pass axe.

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };

async function axe(page: Page, selector: string): Promise<string[]> {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).include(selector).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

for (const lang of ["ar", "en"] as const) {
  test.describe(`posts and feed from navigation (${lang})`, () => {
    test(`feeds, post menu, snooze, saved collections (${lang})`, async ({ browser }) => {
      test.setTimeout(240_000);
      const { a, b } = await sharedAccounts();
      await befriend(a, b);
      const aApi = await apiAs(a);
      const bApi = await apiAs(b);
      await aApi.delete(`${API}/feed/snooze/${b.id}/`);
      const tag = `t4${lang}${unique()}`;
      const created = await bApi.post(`${API}/posts/`, { data: { type: "text", audience: "public", body: `post ${tag}`, media_ids: [] } });
      expect(created.ok(), await created.text()).toBe(true);
      const postId = ((await created.json()) as { data: { id: string } }).data.id;
      await expect
        .poll(async () => {
          const res = await aApi.get(`${API}/feed/`, { params: { mode: "recent", limit: 50 } });
          if (!res.ok()) return false;
          return ((await res.json()) as { data: { post_id: string }[] }).data.some((i) => i.post_id === postId);
        }, { timeout: 30_000 })
        .toBe(true);

      const page = await pageAs(browser, a);
      await useLocale(page, lang);
      await page.addInitScript(() => localStorage.setItem("tara.feedMode", "recent"));
      await page.setViewportSize(DESKTOP);
      await page.goto("/home");
      await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");

      // 1. Left rail -> Feeds: Home sorted "For you", the mode in the URL.
      await page.getByTestId("sidebar-feeds").click();
      await expect(page).toHaveURL(/\/home\?mode=for_you/);
      await expect(page.getByTestId("feed-modes")).toBeVisible();
      await expect(page.getByTestId("feed-modes").locator('button[aria-pressed="true"]')).toHaveCount(1);
      // Back to Latest from the mode bar: b's post is near the top.
      await page.getByTestId("feed-modes").locator("button").nth(1).click();
      await expect(page).toHaveURL(/mode=recent/);
      const card = page.locator(`[data-feed-item="${postId}"]`);
      await expect(card).toBeVisible({ timeout: 20_000 });

      // 2. The post menu: real actions for someone else's post.
      await card.getByTestId("post-menu").click();
      const menu = card.getByTestId("post-menu-panel");
      for (const id of ["menu-save", "menu-collection", "menu-copy-link", "menu-why", "menu-snooze", "menu-favorite", "menu-mute"]) {
        await expect(menu.getByTestId(id)).toBeVisible();
      }
      expect(await axe(page, `[data-feed-item="${postId}"]`)).toEqual([]);
      await menu.getByTestId("menu-why").click();
      await expect(page.getByRole("dialog")).toBeVisible();
      await page.keyboard.press("Escape");

      // 3. Snooze from the menu, then Undo.
      await card.getByTestId("post-menu").click();
      await card.getByTestId("menu-snooze").click();
      await expect(card.getByTestId("snoozed-notice")).toBeVisible();
      await expect
        .poll(async () => ((await (await aApi.get(`${API}/feed/snoozes/`)).json()) as { data: { author_id: string }[] }).data.map((s) => s.author_id))
        .toContain(b.id);
      await card.getByTestId("snoozed-notice").getByRole("button").click();
      await expect(card.getByTestId("snoozed-notice")).toHaveCount(0);
      await expect(card.getByTestId("post-menu")).toBeVisible();

      // 4. Save into a new collection from the post menu.
      const collection = `col ${tag}`;
      await card.getByTestId("post-menu").click();
      await card.getByTestId("menu-collection").click();
      const picker = page.getByRole("dialog");
      await expect(picker).toBeVisible();
      await picker.getByRole("button", { name: lang === "ar" ? /مجموعة جديدة|إنشاء/ : /new collection/i }).first().click();
      await picker.locator("input").fill(collection);
      await picker.locator("input").press("Enter");
      await expect(picker).toHaveCount(0, { timeout: 10_000 });

      // 5. Feed preferences from the mode bar gear: the snoozed list (empty again).
      await page.getByTestId("feed-manage").click();
      await expect(page).toHaveURL(/\/feeds\/manage$/);
      await expect(page.getByTestId("snoozed-list")).toBeVisible();
      await expect(page.getByTestId("snoozed-empty")).toBeVisible();
      expect(await axe(page, "[data-testid=feed-preferences]")).toEqual([]);

      // 6. Left rail -> Saved: the collection holds the post; rename and delete it.
      await page.getByTestId("sidebar-saved").click();
      await expect(page).toHaveURL(/\/saved$/);
      const row = page.getByTestId("saved-collection").filter({ hasText: collection });
      await expect(row).toBeVisible();
      await row.click();
      await expect(page.getByTestId("saved-title")).toHaveText(collection);
      await expect(page.getByTestId("saved-item")).toHaveCount(1);
      expect(await axe(page, "[data-testid=saved-nav]")).toEqual([]);
      await page.getByTestId("collection-options").click();
      await page.getByTestId("collection-rename").click();
      await page.getByTestId("saved-name").fill(`${collection} 2`);
      await page.getByTestId("saved-name-submit").click();
      await expect(page.getByTestId("saved-title")).toHaveText(`${collection} 2`);
      await page.getByTestId("collection-options").click();
      await page.getByTestId("collection-delete").click();
      await page.getByTestId("saved-delete-confirm").click();
      await expect(page.getByTestId("saved-collection").filter({ hasText: collection })).toHaveCount(0);
      // Its post stayed saved (moved back to the default collection).
      await expect(page.locator(`[data-testid=saved-item]`).first()).toBeVisible();

      // 7. Main menu -> Videos and Manage feed are listed.
      await page.getByTestId("main-menu-button").click();
      await expect(page.getByTestId("menu-item-videos")).toBeVisible();
      await expect(page.getByTestId("menu-item-feedPreferences")).toBeVisible();
      await page.getByTestId("menu-item-videos").click();
      await expect(page).toHaveURL(/\/videos$/);
      await expect(page.locator("h1")).toBeVisible();

      await aApi.post(`${API}/posts/${postId}/save/`);
      await aApi.delete(`${API}/posts/${postId}/save/`);
      await page.context().close();
      await aApi.dispose();
      await bApi.dispose();
    });

    test(`search home: recent and trending on a phone (${lang})`, async ({ browser }) => {
      test.setTimeout(120_000);
      const { a } = await sharedAccounts();
      const api = await apiAs(a);
      const q = `t4q${unique()}`;
      expect((await api.post(`${API}/search/recent/`, { data: { query: q } })).ok()).toBe(true);

      const page = await pageAs(browser, a);
      await useLocale(page, lang);
      await page.setViewportSize(MOBILE);
      await page.goto("/home");
      // The phone's top bar search button opens the search screen.
      await page.getByRole("link", { name: lang === "ar" ? /بحث|استكشاف/ : /search|explore/i }).first().click();
      await expect(page).toHaveURL(/\/search/);
      await expect(page.getByTestId("search-mobile-field").locator("input")).toBeVisible();
      await expect(page.getByTestId("search-recent")).toBeVisible();
      await expect(page.getByTestId("search-recent-row").filter({ hasText: q })).toBeVisible();
      await expect(page.getByTestId("search-trending")).toBeVisible();
      expect(await axe(page, "[data-testid=search-home]")).toEqual([]);
      // Remove the recent search.
      await page.getByTestId("search-recent-row").filter({ hasText: q }).locator("button").last().click();
      await expect(page.getByTestId("search-recent-row").filter({ hasText: q })).toHaveCount(0);
      // Live suggestions from the same field.
      await page.getByTestId("search-mobile-field").locator("input").fill("ta");
      await page.getByTestId("search-mobile-field").locator("input").focus();
      await expect(page.getByTestId("global-search-panel")).toBeVisible();
      await page.context().close();
      await api.dispose();
    });
  });
}
