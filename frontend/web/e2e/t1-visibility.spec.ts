import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, type Page, expect, request, test } from "@playwright/test";

import { type Account, API, apiAs, pageAs, PASSWORD, sharedAccounts, signupData, unique, useLocale, verificationToken } from "./helpers";

// Track T1: every section of the settings & privacy centre is reached by
// clicking through navigation (profile menu, main menu, the settings column,
// the mobile index), in Arabic and English, and passes axe. Nothing here
// changes a shared account's settings (2FA and deactivation are covered by
// pytest and vitest: turning them on would lock the shared accounts out).

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };

async function axe(page: Page, selector: string): Promise<string[]> {
  // A button enabling or a chip turning active once its data loads runs a
  // 150ms colour/opacity transition; axe measuring mid-way reports contrast.
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== "running"));
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).include(selector).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

const nav = (page: Page, id: string) => page.locator(`[data-testid="settings-nav-${id}"]:visible`);

for (const lang of ["ar", "en"] as const) {
  test(`settings centre sections from navigation, desktop (${lang})`, async ({ browser }) => {
    test.setTimeout(180_000);
    const { a } = await sharedAccounts();
    const page = await pageAs(browser, a);
    if (lang === "en") await useLocale(page, "en");
    await page.setViewportSize(DESKTOP);
    await page.goto("/home");
    await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");

    // Profile menu > Settings & privacy panel > Privacy centre.
    await page.getByTestId("profile-menu-button").click();
    await page.getByTestId("profile-menu-settings").click();
    await expect(page.getByTestId("profile-menu-security")).toBeVisible();
    expect(await axe(page, '[data-testid="profile-menu"]')).toEqual([]);
    await page.getByTestId("profile-menu-privacy").click();
    await expect(page).toHaveURL(/\/settings\/privacy$/);
    await expect(page.getByTestId("privacy-profile")).toBeVisible();
    await expect(page.getByTestId("privacy-friends_list_visibility")).toBeVisible();
    await expect(page.getByTestId("privacy-friend_requests_from")).toBeVisible();
    await expect(page.getByTestId("tag-privacy")).toBeVisible();
    await expect(page.getByTestId("toggle-show_presence")).toHaveAttribute("role", "switch");
    expect(await axe(page, "main")).toEqual([]);

    // The settings column: security.
    await nav(page, "security").click();
    await expect(page).toHaveURL(/\/settings\/security$/);
    await expect(page.getByTestId("two-factor-status")).toBeVisible();
    await expect(page.getByTestId("two-factor-turn-on").or(page.getByTestId("two-factor-turn-off"))).toBeVisible();
    await expect(page.getByTestId("toggle-login_alerts")).toBeVisible();
    await expect(page.getByTestId("device-row").first()).toBeVisible();
    await expect(page.getByTestId("activity-row").first()).toBeVisible();
    // Repeats are grouped and only five groups show until "Show more".
    expect(await page.getByTestId("activity-row").count()).toBeLessThanOrEqual(5);
    expect(await axe(page, "main")).toEqual([]);

    // Feed and content preferences: tabs are deep-linked.
    await nav(page, "content").click();
    await expect(page.getByTestId("content-preferences")).toBeVisible();
    await page.getByTestId("content-tab-blocks").click();
    await expect(page).toHaveURL(/\/settings\/content#blocks$/);
    await page.getByTestId("content-tab-snoozed").click();
    await expect(page.getByTestId("content-tab-snoozed")).toHaveAttribute("aria-selected", "true");
    expect(await axe(page, "main")).toEqual([]);

    // Display, notifications.
    await nav(page, "display").click();
    await expect(page.getByTestId("display-settings")).toBeVisible();
    await expect(page.getByTestId(`display-locale-${lang}`)).toBeChecked();
    await nav(page, "notifications").click();
    await expect(page.getByTestId("push-settings")).toBeVisible();

    // Account centre card: details, birthday and gender, deactivation.
    await page.locator('[data-testid="settings-account-centre"]:visible').click();
    await expect(page).toHaveURL(/\/settings\/account$/);
    await expect(page.getByTestId("account-status")).toBeVisible();
    await expect(page.getByTestId("birthday-gender")).toBeVisible();
    await expect(page.getByTestId("deactivate-account")).toBeVisible();
    await expect(page.getByTestId("delete-account")).toBeVisible();
    expect(await axe(page, "main")).toEqual([]);

    // Main menu: the Security centre entry exists now that it is built.
    await page.getByTestId("main-menu-button").click();
    await page.getByTestId("menu-item-securityCenter").click();
    await expect(page).toHaveURL(/\/settings\/security$/);

    // An old one-page anchor lands on its section.
    await page.goto("/settings#notifications");
    await expect(page).toHaveURL(/\/settings\/notifications$/);
    await page.context().close();
  });

  test(`settings centre on mobile: index, section, back (${lang})`, async ({ browser }) => {
    const { a } = await sharedAccounts();
    const page = await pageAs(browser, a);
    if (lang === "en") await useLocale(page, "en");
    await page.setViewportSize(MOBILE);
    await page.goto("/menu");
    await page.locator('a[href="/settings"]:visible').first().click();
    await expect(page).toHaveURL(/\/settings$/);
    await nav(page, "privacy").click();
    await expect(page.getByTestId("privacy-connections")).toBeVisible();
    await page.getByTestId("settings-back").click();
    await expect(page).toHaveURL(/\/settings$/);
    await expect(nav(page, "security")).toBeVisible();
    expect(await axe(page, "main")).toEqual([]);

    // Feed and content tabs wrap at phone width: Snoozed is on screen.
    await nav(page, "content").click();
    const snoozed = await page.getByTestId("content-tab-snoozed").boundingBox();
    expect(snoozed && snoozed.x >= 0 && snoozed.x + snoozed.width <= MOBILE.width).toBe(true);
    await page.context().close();
  });
}

// ---- Fix track A: account lifecycle, blocked names, language sync ----------

/** One fresh account (registration is rate limited, so only one per run). */
async function freshAccount(api: APIRequestContext): Promise<Account> {
  const tag = unique();
  const handle = `e2e_life_${tag}`;
  const email = `${handle}@example.com`;
  const res = await api.post(`${API}/auth/register/`, { data: signupData(email, handle, "Nour", tag) });
  expect(res.status(), await res.text()).toBe(201);
  const token = await verificationToken(api, email);
  expect((await api.post(`${API}/auth/verify-email/`, { data: { token } })).ok()).toBe(true);
  return { email, handle, name: `Nour ${tag}`, id: (await res.json()).data.account_id };
}

test("blocked names, language from the account, deactivation and deletion hide the account", async ({ browser }) => {
  test.setTimeout(240_000);
  const { a, b } = await sharedAccounts();
  const anon = await request.newContext();
  const x = await freshAccount(anon);
  const asA = await apiAs(a);
  const asB = await apiAs(b);
  const profileOfX = () => asB.get(`${API}/users/id/${x.id}/`).then((r) => r.status());

  // 1. The Blocked tab names who you blocked (it used to read "Unknown user").
  expect((await asA.post(`${API}/blocks/${x.id}/`)).ok()).toBe(true);
  try {
    // Profile learns of the block through an event: wait until it can name x.
    await expect
      .poll(async () => JSON.stringify((await (await asA.post(`${API}/profile/me/blocked/lookup/`, { data: { ids: [x.id] } })).json()).data), { timeout: 30_000 })
      .toContain(x.id);
    const page = await pageAs(browser, a);
    await useLocale(page, "en");
    await page.goto("/settings/content#blocks");
    await expect(page.getByTestId("content-row-name").filter({ hasText: x.name })).toBeVisible();
    await expect(page.getByTestId("content-row").filter({ hasText: x.name }).locator("a")).toHaveCount(0);
    await page.goto("/connections?tab=blocked");
    await expect(page.getByTestId("connections-blocked-name").filter({ hasText: x.name })).toBeVisible();
    // Across a block, birthday/gender lookups are a 404 both ways.
    const asX = await apiAs(x);
    expect((await asX.get(`${API}/me/people/${a.id}/personal/`)).status()).toBe(404);
    expect((await asA.get(`${API}/me/people/${x.id}/personal/`)).status()).toBe(404);
    await page.context().close();
  } finally {
    await asA.delete(`${API}/blocks/${x.id}/`);
  }

  // 2. Language follows the account even when this browser chose before.
  const asX = await apiAs(x);
  expect((await asX.patch(`${API}/me/`, { data: { language: "en" } })).ok()).toBe(true);
  const xPage = await pageAs(browser, x);
  await xPage.addInitScript(() => localStorage.setItem("tara.locale", "ar"));
  await xPage.goto("/home");
  await expect(xPage.locator("html")).toHaveAttribute("lang", "en");
  await xPage.context().close();

  // 3. Deactivation hides the profile and the posts from others; signing in
  //    brings both back, the post in a follower's home feed included (post
  //    emits post.hidden / post.unhidden, feed keeps the rows meanwhile).
  await expect.poll(profileOfX, { timeout: 20_000 }).toBe(200);
  expect((await asB.post(`${API}/follows/${x.id}/`)).ok()).toBe(true);
  const created = await asX.post(`${API}/posts/`, { data: { body: `Back soon ${unique()}`, audience: "public", type: "text" } });
  expect(created.ok(), await created.text()).toBe(true);
  const postId = (await created.json()).data.id as string;
  const inBFeed = async () => {
    const res = await asB.get(`${API}/feed/`, { params: { mode: "recent", limit: 100 } });
    return ((await res.json()).data as { post_id: string }[]).some((i) => i.post_id === postId);
  };
  await expect.poll(inBFeed, { timeout: 30_000 }).toBe(true);
  expect((await asX.post(`${API}/me/deactivate/`, { data: { password: PASSWORD } })).ok()).toBe(true);
  await expect.poll(profileOfX, { timeout: 30_000 }).toBe(404);
  await expect.poll(inBFeed, { timeout: 30_000 }).toBe(false);
  expect((await asB.get(`${API}/posts/${postId}/`)).status()).toBe(404);
  const again = await apiAs(x); // signing in reactivates
  await expect.poll(profileOfX, { timeout: 30_000 }).toBe(200);
  await expect.poll(inBFeed, { timeout: 30_000 }).toBe(true);
  expect((await asB.get(`${API}/posts/${postId}/`)).status()).toBe(200);
  await asB.delete(`${API}/follows/${x.id}/`);

  // 4. Delete account from Settings: re-auth, confirm, signed out, hidden;
  //    signing in within the grace period cancels it.
  const del = await pageAs(browser, x);
  await del.setViewportSize(DESKTOP);
  await del.goto("/settings/account#delete");
  const card = del.getByTestId("delete-account");
  await expect(card).toBeVisible();
  await card.locator("input[type=password]").fill(PASSWORD);
  await del.getByTestId("delete-submit").click();
  await del.getByTestId("confirm-action").locator("button").last().click();
  await expect(del).toHaveURL(/\/(login)?(\?.*)?$/);
  expect((await again.get(`${API}/me/`)).status()).toBe(401);
  await expect.poll(profileOfX, { timeout: 30_000 }).toBe(404);
  await del.context().close();
  const back = await apiAs(x);
  const me = (await (await back.get(`${API}/me/`)).json()).data;
  expect(me.status).toBe("active");
  await expect.poll(profileOfX, { timeout: 30_000 }).toBe(200);
  await anon.dispose();
});

// "Add phone" in Settings > Account opens Settings > Security on the phone card,
// which renders only after its own fetch: the page must land on it anyway. The
// running stack may have the Telegram bot off, so the providers answer is the
// real one with Telegram switched on; the security overview is held back so
// the card renders well after the route.
for (const lang of ["ar", "en"] as const) {
  for (const [label, viewport] of [["desktop", DESKTOP], ["mobile", MOBILE]] as const) {
    test(`"Add phone" lands on the phone card after it loads, ${label} (${lang})`, async ({ browser }) => {
      const anon = await request.newContext();
      const fresh = await freshAccount(anon);
      const page = await pageAs(browser, fresh);
      await useLocale(page, lang);
      await page.setViewportSize(viewport);
      await page.route(/\/api\/v1\/auth\/providers\/(\?.*)?$/, async (route) => {
        const res = await route.fetch();
        const body = await res.json();
        body.data.telegram = { ...body.data.telegram, enabled: true };
        await route.fulfill({ response: res, json: body });
      });
      await page.route(/\/api\/v1\/me\/security\/(\?.*)?$/, async (route) => {
        await new Promise((r) => setTimeout(r, 1200));
        await route.continue();
      });
      await page.goto("/settings/account");
      const link = page.getByTestId("account-add-phone");
      await expect(link).toBeVisible();
      await link.click();
      await expect(page).toHaveURL(/\/settings\/security#phone$/);
      const card = page.locator("#phone");
      await expect(card).toBeVisible({ timeout: 15_000 });
      await expect(card).toBeInViewport();
      // Landed on it (below the sticky top bar), not merely somewhere on the page.
      await expect
        .poll(async () => card.evaluate((el) => Math.round(el.getBoundingClientRect().top)))
        .toBeLessThan(viewport.height / 2);
      expect(await page.evaluate(() => document.documentElement.dir)).toBe(lang === "ar" ? "rtl" : "ltr");
      await page.context().close();
      await anon.dispose();
    });
  }
}
