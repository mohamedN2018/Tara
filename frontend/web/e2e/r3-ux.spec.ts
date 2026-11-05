// Fix round 3, track r3-ux, in Arabic and English:
// 1. A Latin page name stays at the UI's start edge in search results and as a
//    page post's author (the same fix as PageHeader: no dir="auto" on the
//    block, the name alone in a <bdi>).
// 2. A member's message to Tara Support reaches the support team: a
//    notification that names Tara Support, quotes the message in its own
//    isolate, and opens the support inbox on that thread.
import { execSync } from "node:child_process";

import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, type Browser, expect, type Locator, type Page, test } from "@playwright/test";

import { type Account, API, apiAs, pageAs, sharedAccounts, unique, useLocale } from "./helpers";

const LANGS = ["ar", "en"] as const;
type Lang = (typeof LANGS)[number];

async function open(browser: Browser, who: Account, lang: Lang): Promise<Page> {
  const page = await pageAs(browser, who);
  await page.setViewportSize({ width: 1440, height: 900 });
  await useLocale(page, lang);
  await page.addInitScript(() => localStorage.setItem("tara.push.dismissed", "1"));
  return page;
}

async function axe(page: Page, selector: string) {
  await page.waitForTimeout(300);
  const result = await new AxeBuilder({ page }).include(selector).withTags(["wcag2a", "wcag2aa"]).analyze();
  const bad = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${v.id}: ${v.nodes[0]?.target}`)).toEqual([]);
}

/** The name sits on the UI's start edge of its block: right in ar, left in en. */
async function expectStartAligned(block: Locator, lang: Lang) {
  await expect(block).toBeVisible();
  expect(await block.getAttribute("dir")).toBeNull();
  const outer = (await block.boundingBox())!;
  const name = (await block.locator("bdi").first().boundingBox())!;
  if (lang === "ar") expect(Math.abs(outer.x + outer.width - (name.x + name.width))).toBeLessThanOrEqual(2);
  else expect(Math.abs(outer.x - name.x)).toBeLessThanOrEqual(2);
}

async function pageHits(api: APIRequestContext, q: string): Promise<string[]> {
  const res = await api.get(`${API}/search/`, { params: { q, type: "pages" } });
  if (!res.ok()) return [];
  return ((await res.json()).data.results as { id: string }[]).map((r) => r.id);
}

for (const lang of LANGS) {
  test(`a Latin page name stays start-aligned in search and as a post author (${lang})`, async ({ browser }) => {
    test.setTimeout(180_000);
    const { a, b } = await sharedAccounts();
    const tag = `${lang}${unique()}`;
    const name = `Nile Books ${tag}`;
    const ownerApi = await apiAs(a);
    const created = await ownerApi.post(`${API}/pages/`, { data: { handle: `r3ux_${tag}`, name, category: "Bookshop" } });
    expect(created.ok(), await created.text()).toBe(true);
    const pageId = (await created.json()).data.id as string;
    const posted = await ownerApi.post(`${API}/posts/`, { data: { body: `r3ux news ${tag}`, page_id: pageId } });
    expect(posted.ok(), await posted.text()).toBe(true);
    const postId = (await posted.json()).data.id as string;
    try {
      await expect.poll(() => pageHits(ownerApi, name), { timeout: 40_000 }).toContain(pageId);
      const visitor = await open(browser, b, lang);
      await visitor.goto(`/search?q=${encodeURIComponent(name)}&type=pages`);
      await expectStartAligned(visitor.getByTestId("page-result-name").filter({ hasText: name }).first(), lang);

      await visitor.goto(`/posts/${postId}`);
      const card = visitor.locator(`article[data-post-id="${postId}"]`);
      await expectStartAligned(card.getByTestId("post-author-name"), lang);
      await expect(card.getByTestId("post-author-name")).toHaveText(name);
    } finally {
      await ownerApi.delete(`${API}/posts/${postId}/`);
    }
  });

  test(`a message to Tara Support notifies the support team and opens the thread (${lang})`, async ({ browser }) => {
    test.setTimeout(180_000);
    const { b, c } = await sharedAccounts();
    execSync(`docker exec tara-identity-1 python manage.py create_admin ${c.email}`, { stdio: "pipe" });
    const memberApi = await apiAs(b);
    const conv = await memberApi.post(`${API}/conversations/`, { data: { type: "support" } });
    expect(conv.ok(), await conv.text()).toBe(true);
    const conversationId = (await conv.json()).data.id as string;
    const body = `locked out ${lang}${unique()}?`;
    const sent = await memberApi.post(`${API}/conversations/${conversationId}/messages/`, { data: { body } });
    expect(sent.ok(), await sent.text()).toBe(true);

    // The member is never told of their own message as staff would be.
    const staffApi = await apiAs(c);
    await expect
      .poll(
        async () => {
          const rows = (await (await staffApi.get(`${API}/notifications/`)).json()).data as { kind: string; body: string; url: string }[];
          return rows.find((r) => r.kind === "message.support" && r.body === body)?.url ?? "";
        },
        { timeout: 30_000 },
      )
      .toBe(`/admin/support?conversation=${conversationId}`);
    const own = (await (await memberApi.get(`${API}/notifications/`)).json()).data as { kind: string }[];
    expect(own.some((r) => r.kind === "message.support")).toBe(false);

    const staff = await open(browser, c, lang);
    await staff.goto("/notifications");
    const row = staff.locator('[data-testid="notification-item"][data-kind="message.support"]').filter({ hasText: body }).first();
    await expect(row).toBeVisible({ timeout: 20_000 });
    await expect(row).toContainText(lang === "ar" ? "دعم تارا" : "Tara Support");
    const excerpt = row.getByTestId("notification-excerpt");
    await expect(excerpt).toHaveText(body);
    await expect(excerpt).toHaveAttribute("dir", "auto");
    await axe(staff, '[data-testid="notification-item"][data-kind="message.support"]');
    await row.locator("a").first().click();
    await expect(staff).toHaveURL(new RegExp(`/admin/support\\?conversation=${conversationId}`));
    await expect(staff.getByTestId("team-thread")).toContainText(body);
    await expect(staff.getByTestId("team-inbox-name").locator("bdi")).toBeVisible();
    expect(await staff.getByTestId("team-inbox-name").getAttribute("dir")).toBeNull();
  });
}
