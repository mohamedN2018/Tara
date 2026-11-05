import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, type Page, expect, test } from "@playwright/test";

import { type Account, API, apiAs, BASE_URL, pageAs, sharedAccounts, unfriend } from "./helpers";

// Wave 1B: the app shell's columns, the mobile bottom bar and /menu, and the legal pages.

const MOBILE = { width: 390, height: 844 };
const DESKTOP = { width: 1440, height: 900 };

async function noHorizontalScroll(page: Page) {
  const { scroll, inner } = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    inner: window.innerWidth,
  }));
  expect(scroll, `scrollWidth ${scroll} > innerWidth ${inner} on ${page.url()}`).toBeLessThanOrEqual(inner);
}

async function seriousA11y(page: Page, selectors: string[]): Promise<string[]> {
  let builder = new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]);
  for (const s of selectors) builder = builder.include(s);
  const result = await builder.analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

test("at 390px there is no horizontal scroll on /home, /menu and a profile", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  await page.setViewportSize(MOBILE);

  await page.goto("/home");
  await expect(page.getByTestId("mobile-nav")).toBeVisible();
  await page.waitForLoadState("networkidle").catch(() => {});
  await noHorizontalScroll(page);

  await page.goto("/menu");
  await expect(page.getByTestId("mobile-menu")).toBeVisible();
  await expect(page.getByTestId("menu-item-friends")).toBeVisible();
  await page.waitForLoadState("networkidle").catch(() => {});
  await noHorizontalScroll(page);

  await page.goto(`/u/${a.handle}`);
  await expect(page.locator("main").getByText(a.name).first()).toBeVisible();
  await page.waitForLoadState("networkidle").catch(() => {});
  await noHorizontalScroll(page);
});

test("the fifth mobile tab opens /menu, whose items are the built services", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  await page.setViewportSize(MOBILE);
  await page.goto("/home");

  const tabs = page.getByTestId("mobile-nav").locator("a, button");
  // Home, Friends | Create | Reels, Notifications, Menu.
  await expect(tabs).toHaveCount(6);
  await expect(tabs.nth(3)).toHaveAttribute("data-testid", "mobile-tab-reels");
  await expect(tabs.nth(5)).toHaveAttribute("data-testid", "mobile-tab-menu");
  await tabs.nth(5).click();
  await expect(page).toHaveURL(/\/menu$/);
  await expect(page.getByTestId("mobile-menu")).toBeVisible();
  // The tab shows as current, and the profile card leads to the account's profile.
  await expect(page.getByTestId("mobile-tab-menu")).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("menu-profile")).toHaveAttribute("href", `/u/${a.handle}`);
  // Unbuilt modules never show, and a regular account gets no admin entry.
  await expect(page.getByTestId("menu-item-memories")).toHaveCount(0);
  await expect(page.getByTestId("menu-item-reels")).toHaveCount(1);
  await expect(page.getByTestId("menu-item-admin")).toHaveCount(0);

  await page.getByTestId("menu-item-friends").click();
  await expect(page).toHaveURL(/\/friends$/);

  expect(await seriousA11y(page, ['[data-testid="mobile-nav"]'])).toEqual([]);
  await page.goto("/menu");
  await expect(page.getByTestId("mobile-menu")).toBeVisible();
  expect(await seriousA11y(page, ["main"])).toEqual([]);
});

/** Leave `from` with a pending request to `to` (cancelling one the other way round first). */
async function pendingRequest(fromApi: APIRequestContext, toApi: APIRequestContext, from: Account, to: Account) {
  await unfriend(from, to);
  type Row = { id: string; requested_by: string };
  const toIncoming = (await (await toApi.get(`${API}/friends/requests/`)).json()).data as Row[];
  // A request from `to` to `from` would block ours: `from` declines it.
  const fromIncoming = (await (await fromApi.get(`${API}/friends/requests/`)).json()).data as Row[];
  for (const row of fromIncoming.filter((r) => r.requested_by === to.id)) {
    await fromApi.post(`${API}/friends/requests/${row.id}/reject/`);
  }
  if (!toIncoming.some((r) => r.requested_by === from.id)) {
    const res = await fromApi.post(`${API}/friends/requests/`, { data: { to_user_id: to.id } });
    expect([201, 200, 409]).toContain(res.status());
  }
}

test("a friend request is accepted from the right column, and the sidebar is complete", async ({ browser }) => {
  const { a, c } = await sharedAccounts();
  const aApi = await apiAs(a);
  const cApi = await apiAs(c);
  const wereFriends = ((await (await aApi.get(`${API}/friends/`)).json()).data.friends as string[]).includes(c.id);
  await pendingRequest(cApi, aApi, c, a);

  const page = await pageAs(browser, a);
  await page.setViewportSize(DESKTOP);
  try {
    await page.goto("/home");
    const rail = page.getByTestId("right-rail");
    const row = rail.getByTestId("rail-request").filter({ hasText: c.name });
    await expect(row).toBeVisible();
    // With no ad served, the column has no (empty) sponsored card.
    const served = ((await (await aApi.get(`${API}/feed/`)).json()) as { sponsored: unknown }).sponsored;
    if (!served) await expect(rail.getByTestId("rail-sponsored")).toHaveCount(0);

    await row.getByTestId("rail-request-accept").click();
    await expect(row).toHaveCount(0);
    await expect
      .poll(async () => ((await (await aApi.get(`${API}/friends/`)).json()).data.friends as string[]).includes(c.id))
      .toBe(true);
    // The new friend is a contact; clicking a contact opens a docked mini chat
    // (desktop), and "Open in Messenger" leads to the inbox thread.
    const contact = rail.getByTestId("rail-contact").filter({ hasText: c.name });
    await expect(contact).toBeVisible();
    await contact.click();
    await expect(page.getByTestId("chat-window")).toBeVisible();
    await page.getByTestId("chat-window-open").click();
    await expect(page).toHaveURL(/\/messages\/[\w-]+$/);

    // Left column: profile first, eight items, See more persists across a reload.
    await page.goto("/home");
    const sidebar = page.locator("aside").getByTestId("left-sidebar");
    await expect(sidebar.getByTestId("sidebar-profile")).toHaveAttribute("href", `/u/${a.handle}`);
    await expect(sidebar.getByTestId("sidebar-items").locator("a")).toHaveCount(8);
    await sidebar.getByTestId("sidebar-see-more").click();
    await expect(sidebar.getByTestId("sidebar-see-more")).toHaveAttribute("aria-expanded", "true");
    const expanded = await sidebar.getByTestId("sidebar-items").locator("a").count();
    expect(expanded).toBeGreaterThan(8);
    await page.reload();
    await expect(sidebar.getByTestId("sidebar-items").locator("a")).toHaveCount(expanded);
    await sidebar.getByTestId("sidebar-see-more").click();
    await expect(sidebar.getByTestId("sidebar-items").locator("a")).toHaveCount(8);
    await expect(sidebar.getByTestId("sidebar-footer").locator('a[href="/legal/terms"]')).toBeVisible();

    expect(await seriousA11y(page, ['[data-testid="left-sidebar"]', '[data-testid="right-rail"]'])).toEqual([]);
  } finally {
    if (!wereFriends) await unfriend(a, c);
  }
});

test("the legal pages load signed out, in Arabic and in English, with the draft banner", async ({ browser }) => {
  const context = await browser.newContext({ baseURL: BASE_URL });
  const page = await context.newPage();

  await page.goto("/legal/terms");
  await expect(page).toHaveURL(/\/legal\/terms$/);
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("شروط الخدمة");
  await expect(page.getByTestId("legal-draft-banner")).toContainText("مسودة");
  await expect(page.getByText("2026-11-04-draft")).toBeVisible();
  expect(await seriousA11y(page, ["body"])).toEqual([]);

  await page.getByTestId("legal-other").click();
  await expect(page).toHaveURL(/\/legal\/privacy$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("سياسة الخصوصية");

  // English (the language toggle on the page).
  await page.getByRole("button", { name: "English" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Privacy Policy");
  await expect(page.getByTestId("legal-draft-banner")).toContainText("Draft pending legal review");
  await page.goto("/legal/terms");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Terms of Service");
  await expect(page.getByText(/at least 13 years old/)).toBeVisible();
  expect(await seriousA11y(page, ["body"])).toEqual([]);

  // Mobile width: readable without sideways scrolling.
  await page.setViewportSize(MOBILE);
  await noHorizontalScroll(page);
  await context.close();
});
