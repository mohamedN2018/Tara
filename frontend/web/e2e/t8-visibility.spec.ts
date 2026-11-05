import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { API, apiAs, pageAs, sharedAccounts, unique, useLocale } from "./helpers";

// Track T8: Creator Studio, the content library and the planner are reached
// from navigation (main menu and left sidebar, then the studio's own nav) in
// Arabic and English, show real data, and their actions work.

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };

async function axe(page: Page, selector: string): Promise<string[]> {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).include(selector).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

/** Three days ahead at 18:00 local (browser and runner share a zone). */
function inDays(n: number, hour = 18): Date {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n, hour, 0);
}

for (const lang of ["ar", "en"] as const) {
  test.describe(`studio from navigation (${lang})`, () => {
    // Runs even when a test fails, so its posts don't pile up on the shared account.
    const cleanup: (() => Promise<unknown>)[] = [];
    test.afterEach(async () => {
      for (const undo of cleanup.splice(0)) await undo().catch(() => {});
    });

    test(`menu -> studio home -> library -> planner, real rows, actions (${lang})`, async ({ browser }) => {
      test.setTimeout(180_000);
      const { a } = await sharedAccounts();
      const api = await apiAs(a);
      const tag = `t8${lang}${unique()}`;
      // Early in the day: a month cell shows its first two posts, by time.
      const scheduledAt = inDays(3, 6);
      const made = async (body: object) => {
        const res = await api.post(`${API}/posts/`, { data: { type: "text", audience: "public", media_ids: [], ...body } });
        expect(res.ok(), await res.text()).toBe(true);
        const row = (await res.json()).data as { id: string };
        cleanup.push(() => api.delete(`${API}/posts/drafts/${row.id}/`));
        return row;
      };
      const scheduled = await made({ body: `scheduled ${tag}`, publish_at: scheduledAt.toISOString() });
      const draft = await made({ body: `draft ${tag}`, draft: true });
      await made({ body: `published ${tag}` });

      const page = await pageAs(browser, a);
      await useLocale(page, lang);
      await page.setViewportSize(DESKTOP);
      await page.goto("/home");
      await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");

      // 1. Main menu -> Creator studio.
      await page.getByTestId("main-menu-button").click();
      await expect(page.getByTestId("menu-item-creatorStudio")).toBeVisible();
      await expect(page.getByTestId("menu-item-contentLibrary")).toBeVisible();
      await expect(page.getByTestId("menu-item-planner")).toBeVisible();
      await page.getByTestId("menu-item-creatorStudio").click();
      await expect(page).toHaveURL(/\/studio$/);
      await expect(page.getByTestId("studio-home")).toBeVisible();
      await expect(page.getByTestId("studio-stats")).toBeVisible();
      // Real numbers only: no impressions / reach tiles.
      await expect(page.getByTestId("studio-stat-value")).toHaveCount(5);
      expect(await axe(page, "[data-testid=studio-home]")).toEqual([]);

      // 2. Studio nav -> Content library; Drafts tab lists my draft with its actions.
      await page.getByTestId("studio-nav-studio-library").click();
      await expect(page).toHaveURL(/\/studio\/library/);
      await page.getByTestId("library-tab-drafts").click();
      const draftRow = page.getByTestId("library-rows").locator("li", { hasText: `draft ${tag}` });
      await expect(draftRow).toBeVisible();
      await expect(draftRow.getByTestId("library-edit")).toBeVisible();
      await expect(draftRow.getByTestId("library-publish")).toBeVisible();
      await page.getByTestId("library-tab-scheduled").click();
      await expect(page.getByTestId("library-rows").locator("li", { hasText: `scheduled ${tag}` })).toBeVisible();
      expect(await axe(page, "[data-testid=studio-library]")).toEqual([]);

      // Edit opens the composer on the draft itself.
      await page.getByTestId("library-tab-drafts").click();
      await draftRow.getByTestId("library-edit").click();
      await expect(page.getByTestId("composer-dialog")).toBeVisible();
      await expect(page.getByTestId("composer-dialog").locator("textarea").first()).toHaveValue(`draft ${tag}`);
      await page.keyboard.press("Escape");
      await expect(page.getByTestId("composer-dialog")).toBeHidden();

      // Delete (with confirmation) removes it on the server.
      await draftRow.getByTestId("library-delete").click();
      await draftRow.getByTestId("library-confirm-delete").click();
      await expect(draftRow).toBeHidden();
      expect((await api.get(`${API}/posts/drafts/${draft.id}/`)).status()).toBe(404);

      // 3. Studio nav -> Planner: the scheduled post sits on its day, the zone is named.
      await page.getByTestId("studio-nav-studio-planner").click();
      await expect(page).toHaveURL(/\/studio\/planner/);
      await expect(page.getByTestId("planner-zone")).toContainText(Intl.DateTimeFormat().resolvedOptions().timeZone);
      const dayKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      if (scheduledAt.getMonth() !== new Date().getMonth()) await page.getByTestId("planner-next").click();
      const chip = page.locator(`[data-day="${dayKey(scheduledAt)}"] [data-post-id="${scheduled.id}"]`);
      await expect(chip).toBeVisible();
      expect(await axe(page, "[data-testid=studio-planner]")).toEqual([]);

      // Drag it one day later: same local time, saved on the server.
      const target = inDays(4, 6);
      // The next day is on this grid unless it opens a new week of the next month.
      const targetCell = page.locator(`[data-day="${dayKey(target)}"]`);
      if (await targetCell.count()) {
        await chip.dragTo(targetCell);
        await expect(page.locator(`[data-day="${dayKey(target)}"] [data-post-id="${scheduled.id}"]`)).toBeVisible();
        await expect
          .poll(async () => {
            const res = await api.get(`${API}/posts/drafts/${scheduled.id}/`);
            return new Date((await res.json()).data.publish_at).getTime();
          })
          .toBe(target.getTime());
      }

      // Week view and back.
      await page.getByTestId("planner-view").click();
      await page.getByTestId("planner-view-week").click();
      await expect(page.getByTestId("planner-grid")).toHaveAttribute("data-view", "week");
      await page.getByTestId("planner-view").click();
      await page.getByTestId("planner-view-month").click();
      await expect(page.getByTestId("planner-grid")).toHaveAttribute("data-view", "month");

      // Create post -> scheduled post opens the composer already scheduled.
      const sidebar = page.getByTestId("studio-sidebar");
      await sidebar.getByTestId("studio-create").click();
      await sidebar.getByTestId("studio-create-scheduled").click();
      await expect(page.getByTestId("composer-dialog")).toBeVisible();
      await expect(page.getByTestId("composer-schedule-summary")).toBeVisible();
      await page.keyboard.press("Escape");

      // Deep link to one draft still opens it (legacy /posts/drafts/:id).
      const other = await made({ body: `deep ${tag}`, draft: true });
      await page.goto(`/posts/drafts/${other.id}`);
      await expect(page).toHaveURL(/\/studio\/library/);
      await expect(page.getByTestId("composer-dialog")).toBeVisible();
      await api.delete(`${API}/posts/drafts/${other.id}/`);
      await api.delete(`${API}/posts/drafts/${scheduled.id}/`);
      await api.dispose();
    });

    test(`sidebar and phone tabs reach the studio (${lang})`, async ({ browser }) => {
      const { a } = await sharedAccounts();
      const page = await pageAs(browser, a);
      await useLocale(page, lang);
      await page.setViewportSize(DESKTOP);
      await page.goto("/home");
      const link = page.getByTestId("sidebar-studio");
      if (!(await link.isVisible())) await page.getByTestId("sidebar-see-more").click();
      await link.click();
      await expect(page).toHaveURL(/\/studio$/);
      await expect(page.getByTestId("studio-sidebar")).toBeVisible();

      // Phones: the studio nav becomes tabs under the top bar; no horizontal scroll.
      await page.setViewportSize(MOBILE);
      await expect(page.getByTestId("studio-tabs")).toBeVisible();
      await page.getByTestId("studio-tab-studio-planner").click();
      await expect(page).toHaveURL(/\/studio\/planner/);
      await expect(page.getByTestId("planner-agenda")).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow).toBeLessThanOrEqual(1);
      expect(await axe(page, "[data-testid=studio-planner]")).toEqual([]);
    });

    test(`insights and engagement sections show my real counters and comments (${lang})`, async ({ browser }) => {
      test.setTimeout(120_000);
      const { a, b } = await sharedAccounts();
      const api = await apiAs(a);
      const other = await apiAs(b);
      const tag = unique();
      const post = (await (await api.post(`${API}/posts/`, { data: { type: "text", audience: "public", media_ids: [], body: `insights ${tag}` } })).json()).data;
      const comment = (await (await other.post(`${API}/posts/${post.id}/comments/`, { data: { body: `comment ${tag}` } })).json()).data;

      const page = await pageAs(browser, a);
      await useLocale(page, lang);
      await page.setViewportSize(DESKTOP);
      await page.goto("/home");
      await page.getByTestId("main-menu-button").click();
      await page.getByTestId("menu-item-creatorStudio").click();
      const sidebar = page.getByTestId("studio-sidebar");
      // Insights -> Content performance (the section opens like the reference's).
      await sidebar.getByTestId("studio-nav-insights").click();
      await expect(sidebar.getByTestId("studio-nav-insights")).toHaveAttribute("aria-expanded", "true");
      await sidebar.getByTestId("studio-nav-studio-insights").click();
      await expect(page).toHaveURL(/\/studio\/insights$/);
      const table = page.getByTestId("insights-by-type");
      await expect(table).toBeVisible();
      const insights = (await (await api.get(`${API}/posts/studio/insights/`)).json()).data as { by_type: { type: string; posts: number }[] };
      const textRow = insights.by_type.find((r) => r.type === "text");
      expect(textRow?.posts).toBeGreaterThan(0);
      expect(await axe(page, "[data-testid=studio-insights]")).toEqual([]);

      // Engagement -> Comments: b's comment on my post, newest first, with a link to the post.
      if (!(await sidebar.getByTestId("studio-nav-studio-engagement").isVisible())) await sidebar.getByTestId("studio-nav-engagement").click();
      await sidebar.getByTestId("studio-nav-studio-engagement").click();
      await expect(page).toHaveURL(/\/studio\/engagement$/);
      const row = page.locator(`[data-comment="${comment.id}"]`);
      await expect(row).toContainText(`comment ${tag}`);
      await expect(row).toContainText(`insights ${tag}`);
      expect(await axe(page, "[data-testid=studio-engagement]")).toEqual([]);

      // Phones: every studio page is one tab and nothing scrolls sideways.
      await page.setViewportSize(MOBILE);
      const tabs = page.getByTestId("studio-tabs");
      await expect(tabs.locator("a")).toHaveCount(5);
      for (const name of ["studio", "studio-insights", "studio-library", "studio-planner", "studio-engagement"]) {
        const box = await tabs.getByTestId(`studio-tab-${name}`).boundingBox();
        expect(box && box.x >= 0 && box.x + box.width <= MOBILE.width).toBe(true);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);

      await api.delete(`${API}/posts/${post.id}/`);
      await api.dispose();
      await other.dispose();
      await page.context().close();
    });

    test(`another member's draft is a 404 (${lang})`, async () => {
      const { a, b } = await sharedAccounts();
      const mine = await apiAs(a);
      const theirs = await apiAs(b);
      const res = await mine.post(`${API}/posts/`, { data: { type: "text", audience: "public", media_ids: [], body: "private draft", draft: true } });
      const { id } = (await res.json()).data;
      expect((await theirs.get(`${API}/posts/drafts/${id}/`)).status()).toBe(404);
      const cal = await theirs.get(`${API}/posts/calendar/`, {
        params: { from: new Date(Date.now() - 86_400_000).toISOString(), to: new Date(Date.now() + 30 * 86_400_000).toISOString() },
      });
      expect(cal.ok()).toBe(true);
      expect(((await cal.json()).data as { id: string }[]).some((p) => p.id === id)).toBe(false);
      await mine.delete(`${API}/posts/drafts/${id}/`);
      await mine.dispose();
      await theirs.dispose();
    });
  });
}
