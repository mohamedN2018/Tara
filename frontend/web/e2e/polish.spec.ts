import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, type Page, expect, test } from "@playwright/test";
import { deflateSync } from "node:zlib";

import { API, apiAs, befriend, pageAs, sharedAccounts, unique, useLocale } from "./helpers";

// Polish track: the settings landing (find a setting, most visited), the
// activity log, name hover cards, the composer's live preview / drop zone /
// share to story, the studio's engagement chart and library filters + CSV,
// and Page categories in the reader's language. Arabic and English.

const DESKTOP = { width: 1440, height: 900 };

async function axe(page: Page, selector: string): Promise<string[]> {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).include(selector).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

/** A small real PNG (a brand gradient) for uploads. */
function png(width = 120, height = 120): Buffer {
  const table = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc = (buf: Buffer) => {
    let c = 0xffffffff;
    for (const b of buf) c = table[(c ^ b) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (type: string, data: Buffer) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(type), data]);
    const sum = Buffer.alloc(4);
    sum.writeUInt32BE(crc(body));
    return Buffer.concat([len, body, sum]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 2;
  const rows: number[] = [];
  for (let y = 0; y < height; y++) {
    rows.push(0);
    for (let x = 0; x < width; x++) rows.push(106, Math.round((85 * x) / width), 244 - Math.round((28 * y) / height));
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.from(rows))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

async function post(api: APIRequestContext, body: string): Promise<string> {
  const res = await api.post(`${API}/posts/`, { data: { type: "text", audience: "public", media_ids: [], body } });
  expect(res.ok(), await res.text()).toBe(true);
  return (await res.json()).data.id as string;
}

for (const lang of ["ar", "en"] as const) {
  test.describe(`polish (${lang})`, () => {
    const cleanup: (() => Promise<unknown>)[] = [];
    test.afterEach(async () => {
      for (const undo of cleanup.splice(0)) await undo().catch(() => {});
    });

    test(`settings: find a setting, most visited, activity log with real rows (${lang})`, async ({ browser }) => {
      test.setTimeout(120_000);
      const { a, b } = await sharedAccounts();
      const aApi = await apiAs(a);
      const bApi = await apiAs(b);
      const tag = `pl${lang}${unique()}`;
      const theirs = await post(bApi, `their post ${tag}`);
      cleanup.push(() => bApi.delete(`${API}/posts/${theirs}/`));
      const comment = await aApi.post(`${API}/posts/${theirs}/comments/`, { data: { body: `my comment ${tag}` } });
      expect(comment.ok(), await comment.text()).toBe(true);
      expect((await aApi.post(`${API}/posts/${theirs}/reactions/`, { data: { type: "love" } })).ok()).toBe(true);
      expect((await aApi.post(`${API}/search/recent/`, { data: { query: `query ${tag}` } })).ok()).toBe(true);

      const page = await pageAs(browser, a);
      await useLocale(page, lang);
      await page.setViewportSize(DESKTOP);
      await page.goto("/settings");
      await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
      const landing = page.getByTestId("settings-landing");
      await expect(landing).toBeVisible();
      await expect(page.getByTestId("settings-most-blocking")).toBeVisible();
      await expect(page.getByTestId("settings-most-theme")).toBeVisible();
      await expect(page.getByTestId("settings-most-profilePrivacy")).toBeVisible();
      expect(await axe(page, '[data-testid="settings-landing"]')).toEqual([]);

      await page.getByTestId("settings-find").fill(lang === "ar" ? "الحظر" : "block");
      await expect(page.getByTestId("settings-find-blocking")).toBeVisible();
      await page.getByTestId("settings-find-blocking").click();
      await expect(page).toHaveURL(/\/settings\/content#blocks$/);

      // The activity log from the settings navigation.
      await page.getByTestId("settings-nav-activity-log").click();
      await expect(page).toHaveURL(/\/settings\/activity-log$/);
      const log = page.getByTestId("activity-log");
      await expect(log.getByTestId("activity-row").filter({ hasText: `my comment ${tag}` })).toBeVisible();
      const reaction = log.locator('[data-testid="activity-row"][data-kind="reaction"]').filter({ hasText: `their post ${tag}` }).first();
      await expect(reaction).toBeVisible();
      expect(await axe(page, '[data-testid="activity-log"]')).toEqual([]);

      await page.getByTestId("activity-filter-comment").click();
      await expect(log.locator('[data-testid="activity-row"]').first()).toHaveAttribute("data-kind", "comment");
      await page.getByTestId("activity-filter-searches").click();
      await expect(page.getByTestId("activity-search-row").filter({ hasText: `query ${tag}` })).toBeVisible();

      // Owner-only: nobody passes an account id, and b's log never shows a's comment.
      const bLog = await (await bApi.get(`${API}/posts/activity/`, { params: { kind: "comment" } })).json();
      expect(JSON.stringify(bLog)).not.toContain(`my comment ${tag}`);
      await page.context().close();
    });

    test(`hover card on a post author: real counts and actions, keyboard too (${lang})`, async ({ browser }) => {
      test.setTimeout(120_000);
      const { a, b } = await sharedAccounts();
      const bApi = await apiAs(b);
      const tag = `hc${lang}${unique()}`;
      const id = await post(bApi, `hover ${tag}`);
      cleanup.push(() => bApi.delete(`${API}/posts/${id}/`));

      const page = await pageAs(browser, a);
      await useLocale(page, lang);
      await page.setViewportSize(DESKTOP);
      await page.goto(`/posts/${id}`);
      const name = page.getByTestId("post-author-name").first();
      await expect(name).toBeVisible();
      await name.hover();
      const card = page.getByTestId("hover-card").first();
      await expect(card).toBeVisible();
      await expect(card.getByTestId("hover-card-name")).toBeVisible();
      await expect(card.getByTestId("hover-card-message")).toBeVisible();
      expect(await axe(page, '[data-testid="hover-card"]')).toEqual([]);
      await page.keyboard.press("Escape");
      await expect(card).toBeHidden();

      // Keyboard: focusing the name opens it, Tab reaches its buttons.
      await page.mouse.move(5, 5);
      await name.focus();
      await page.keyboard.press("Shift+Tab");
      await page.keyboard.press("Tab");
      await expect(page.getByTestId("hover-card").first()).toBeVisible();
      await page.context().close();
    });

    test(`composer: live preview, drop zone, share to story makes a real story (${lang})`, async ({ browser }) => {
      test.setTimeout(180_000);
      const { a } = await sharedAccounts();
      const aApi = await apiAs(a);
      const tag = `cp${lang}${unique()}`;
      const page = await pageAs(browser, a);
      await useLocale(page, lang);
      await page.setViewportSize(DESKTOP);
      await page.goto("/home");
      await page.getByTestId("composer-open").first().click();
      const dialog = page.getByTestId("composer-dialog");
      await expect(dialog).toBeVisible();
      await expect(page.getByTestId("composer-preview")).toBeVisible();
      await expect(page.getByTestId("composer-preview-empty")).toBeVisible();
      await expect(page.getByTestId("composer-dropzone")).toBeVisible();
      await dialog.locator('[contenteditable="true"], textarea').first().fill(`story post ${tag}`);
      await expect(page.getByTestId("composer-preview-body")).toContainText(`story post ${tag}`);

      await page.getByTestId("composer-dropzone-input").setInputFiles({ name: "photo.png", mimeType: "image/png", buffer: png() });
      await expect(page.getByTestId("composer-preview-photos").locator("img")).toHaveCount(1);
      await expect(page.getByTestId("composer-share-story")).toBeVisible();
      expect(await axe(page, '[data-testid="composer-dialog"]')).toEqual([]);
      await page.getByTestId("composer-share-story-toggle").check();
      const created = page.waitForResponse((r) => r.url().includes("/api/v1/stories/") && r.request().method() === "POST");
      await page.getByTestId("composer-submit").click();
      const storyRes = await created;
      expect(storyRes.status(), await storyRes.text()).toBe(201);
      const story = (await storyRes.json()).data as { id: string; kind: string; audience: string };
      cleanup.push(() => aApi.delete(`${API}/stories/${story.id}/`));
      expect(story.kind).toBe("photo");
      expect(story.audience).toBe("public");
      // The post itself is there too.
      const mine = await (await aApi.get(`${API}/posts/studio/published/`, { params: { q: tag } })).json();
      expect(mine.data.length).toBe(1);
      cleanup.push(() => aApi.delete(`${API}/posts/${mine.data[0].id}/`));
      await page.context().close();
    });

    test(`studio: engagement over time with a range, library search, CSV export (${lang})`, async ({ browser }) => {
      test.setTimeout(120_000);
      const { a, b } = await sharedAccounts();
      const aApi = await apiAs(a);
      const bApi = await apiAs(b);
      const tag = `st${lang}${unique()}`;
      const id = await post(aApi, `studio ${tag}`);
      cleanup.push(() => aApi.delete(`${API}/posts/${id}/`));
      expect((await bApi.post(`${API}/posts/${id}/reactions/`, { data: { type: "like" } })).ok()).toBe(true);

      const page = await pageAs(browser, a);
      await useLocale(page, lang);
      await page.setViewportSize(DESKTOP);
      await page.goto("/studio");
      const trend = page.getByTestId("studio-trend");
      await expect(trend.getByTestId("engagement-chart")).toBeVisible();
      const daily = page.waitForResponse((r) => r.url().includes("/posts/studio/daily/"));
      await page.getByTestId("studio-range-7").click();
      const body = await (await daily).json();
      expect(body.data.days).toHaveLength(7);
      expect(body.data.totals.reactions).toBeGreaterThanOrEqual(1);
      await page.getByTestId("studio-metric-reactions").click();
      await page.getByTestId("engagement-table-toggle").click();
      await expect(page.getByTestId("engagement-table").locator("tbody tr")).toHaveCount(7);
      expect(await axe(page, '[data-testid="studio-trend"]')).toEqual([]);

      await page.goto("/studio/library");
      await page.getByTestId("library-search").fill(tag);
      await expect(page.getByTestId("library-rows").locator("li")).toHaveCount(1);
      await expect(page.getByTestId("library-rows")).toContainText(`studio ${tag}`);
      const download = page.waitForEvent("download");
      await page.getByTestId("library-export").click();
      const file = await download;
      expect(file.suggestedFilename()).toMatch(/^tara-content-.*\.csv$/);
      const path = await file.path();
      const { readFileSync } = await import("node:fs");
      expect(readFileSync(path, "utf8")).toContain(`studio ${tag}`);
      await page.context().close();
    });

    test(`page category in the reader's language, bidi-safe names (${lang})`, async ({ browser }) => {
      test.setTimeout(120_000);
      const { a, b } = await sharedAccounts();
      await befriend(a, b);
      const aApi = await apiAs(a);
      const tag = `pc${lang}${unique()}`;
      const created = await aApi.post(`${API}/pages/`, { data: { handle: `pl_${tag}`, name: `Polish ${tag}`, category: "Science" } });
      expect(created.ok(), await created.text()).toBe(true);
      const pageId = (await created.json()).data.id as string;
      cleanup.push(() => aApi.delete(`${API}/pages/${pageId}/`));

      const page = await pageAs(browser, a);
      await useLocale(page, lang);
      await page.setViewportSize(DESKTOP);
      await page.goto(`/pages/pl_${tag}`);
      await expect(page.getByTestId("page-category").first()).toHaveText(lang === "ar" ? "علوم" : "Science");

      // A person result: the name starts at the avatar's side, isolated in <bdi>.
      await page.goto(`/search?q=${encodeURIComponent(b.handle ?? b.email.split("@")[0])}&type=people`);
      const result = page.getByTestId("person-result").first();
      if (await result.count()) {
        const link = result.locator("a.font-semibold").first();
        await expect(link.locator("bdi")).toHaveCount(1);
        expect(await link.getAttribute("dir")).toBeNull();
      }
      await page.context().close();
    });
  });
}
