import { execSync } from "node:child_process";

import AxeBuilder from "@axe-core/playwright";
import { type Browser, type Page, expect, request, test } from "@playwright/test";

import { type Account, API, apiAs, pageAs, PASSWORD, sharedAccounts, signupData, unique, useLocale, verificationToken } from "./helpers";

// Track T7: every moderation and support feature is reached from navigation
// (main menu, console rail, footer, notifications), in Arabic and English:
// a member reports a profile and follows it in the Support inbox; staff claim
// the case, read its report and decide with a reason; the owner is notified,
// sees the decision and requests a review; staff keep the decision from the
// Appeals tab; staff send an administrative notice; a suspended account learns
// until when at sign-in; the Community Standards open from the footer.

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };
const SHOTS = process.env.T7_SHOTS ?? "";

const promote = (email: string) =>
  execSync(`docker exec tara-identity-1 python manage.py create_admin ${email}`, { stdio: "pipe" });

async function axe(page: Page, selector: string): Promise<string[]> {
  // Let .btn's 150ms transition (opacity/colour after enabling) settle first.
  await page.waitForTimeout(300);
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).include(selector).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false });
}

async function open(browser: Browser, account: Account, lang: "ar" | "en", size = DESKTOP): Promise<Page> {
  const page = await pageAs(browser, account);
  await useLocale(page, lang);
  await page.setViewportSize(size);
  return page;
}

async function menu(page: Page, id: string) {
  await page.getByTestId("main-menu-button").click();
  await expect(page.getByTestId(`menu-item-${id}`)).toBeVisible();
  await page.getByTestId(`menu-item-${id}`).click();
}

const L = {
  ar: {
    consoleNav: "أقسام الإدارة",
    moderation: "الإشراف",
    notices: "الإعلانات الإدارية",
    adReview: "مراجعة الإعلانات",
    warned: "وصلك تحذير بخصوص: ملف شخصي",
    suspended: "حسابك موقوف",
    standards: "معايير المجتمع",
  },
  en: {
    consoleNav: "Admin sections",
    moderation: "Moderation",
    notices: "Announcements",
    adReview: "Ad review",
    warned: "You got a warning about your Profile",
    suspended: "Your account is suspended",
    standards: "Community Standards",
  },
} as const;

/** The open case about `targetId`, paging through the queue if it is long. */
async function findCase(page: Page, targetId: string) {
  const card = page.getByTestId("mod-case").filter({ has: page.locator(`a[href="/admin/users/${targetId}"]`) });
  for (let i = 0; i < 15 && !(await card.count()); i++) {
    const more = page.getByTestId("mod-more");
    if (!(await more.count())) break;
    await more.click();
    await page.waitForTimeout(400);
  }
  return card.first();
}

test.describe.configure({ mode: "serial" });

for (const lang of ["ar", "en"] as const) {
  test(`report -> claim -> decide -> notify -> appeal -> keep, from navigation (${lang})`, async ({ browser }) => {
    test.setTimeout(240_000);
    const { a, b, c } = await sharedAccounts();
    promote(c.email);
    const tag = `t7${lang}${unique()}`;

    // Bob reports Alice's profile (the profile menu's Report files this call).
    const bobApi = await apiAs(b);
    const filed = await bobApi.post(`${API}/moderation/reports/file/`, {
      data: { target_type: "user", target_id: a.id, reason: `impersonation: ${tag}` },
    });
    expect(filed.status(), await filed.text()).toBe(202);

    // 1. Bob: Menu -> Support inbox -> Your reports.
    const bob = await open(browser, b, lang);
    await bob.goto("/home");
    await expect(bob.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
    await menu(bob, "support");
    await expect(bob).toHaveURL(/\/support/);
    await bob.getByTestId("support-tab-reports").click();
    await expect(bob.getByTestId("support-report").first()).toBeVisible();
    expect(await axe(bob, "[data-testid=support-nav], [data-testid=support-reports]")).toEqual([]);
    await shot(bob, `support-reports-${lang}-desktop`);

    // 2. Carol: Menu -> Console -> Moderation; claim the case and read its report.
    const carol = await open(browser, c, lang);
    await carol.goto("/home");
    await menu(carol, "admin");
    await expect(carol).toHaveURL(/\/admin$/);
    await expect(carol.getByTestId("admin-attention")).toBeVisible();
    const rail = carol.getByRole("navigation", { name: L[lang].consoleNav });
    await expect(rail.getByRole("link", { name: L[lang].adReview })).toBeVisible();
    await expect(rail.getByRole("link", { name: L[lang].notices })).toBeVisible();
    await shot(carol, `admin-overview-${lang}-desktop`);
    await rail.getByRole("link", { name: L[lang].moderation }).click();
    await expect(carol).toHaveURL(/\/admin\/moderation/);
    await expect(carol.getByTestId("mod-cases")).toBeVisible();
    const card = await findCase(carol, a.id);
    // A retried run may already have claimed it: then it waits under "Assigned to me".
    if (await card.count()) {
      await shot(carol, `admin-moderation-${lang}-desktop`);
      expect(await axe(carol, "[data-testid=mod-cases]")).toEqual([]);
      await card.getByTestId("mod-claim").click();
      await expect(card).toHaveCount(0);
    }
    await carol.getByTestId("mod-tab-mine").click();
    const mine = await findCase(carol, a.id);
    await expect(mine.getByTestId("mod-assignee")).toBeVisible();
    await mine.getByTestId("mod-open-reports").click();
    const detail = carol.getByTestId("case-detail");
    // Bob's report (one per reporter per open case: an earlier run's may be the one kept).
    await expect(detail.getByTestId("report-row").filter({ hasText: lang === "ar" ? "انتحال شخصية" : "Pretending to be someone" }).first()).toBeVisible();
    await shot(carol, `admin-case-detail-${lang}-desktop`);
    await detail.getByTestId("detail-decide").click();
    const decision = carol.getByTestId("case-decision-dialog");
    // A profile can be restricted or warned, never "removed".
    await expect(decision.getByTestId("decision-remove")).toHaveCount(0);
    await decision.getByTestId("decision-warn").check();
    await decision.getByTestId("decision-reason").fill(`Reason ${tag}`);
    expect(await axe(carol, "[data-testid=case-decision-dialog]")).toEqual([]);
    await decision.getByTestId("decision-confirm").click();
    await expect(decision).toHaveCount(0);

    // 3. Alice is notified; the row opens her Support inbox at the decision.
    const alice = await open(browser, a, lang);
    await alice.goto("/notifications");
    const row = alice.getByTestId("notification-item").filter({ hasText: L[lang].warned }).first();
    await expect
      .poll(async () => {
        if (await row.count()) return true;
        await alice.reload();
        return false;
      }, { timeout: 45_000, intervals: [1500] })
      .toBe(true);
    await row.click();
    await expect(alice).toHaveURL(/\/support\?case=/);
    const decided = alice.getByTestId("support-case").filter({ hasText: `Reason ${tag}` });
    await expect(decided).toBeVisible();
    await shot(alice, `support-status-${lang}-desktop`);
    await decided.getByTestId("support-request-review").click();
    await alice.getByTestId("appeal-text").fill(`Please review ${tag}`);
    expect(await axe(alice, "[data-testid=appeal-dialog]")).toEqual([]);
    await alice.getByTestId("appeal-send").click();
    await expect(decided.getByTestId("support-appeal-status")).toBeVisible();

    // 4. Carol keeps the decision from the Appeals tab.
    await carol.getByTestId("mod-tab-appeals").click();
    const appeal = carol.getByTestId("mod-appeal").filter({ hasText: `Please review ${tag}` });
    await expect(appeal).toBeVisible();
    await shot(carol, `admin-appeals-${lang}-desktop`);
    await appeal.getByTestId("appeal-uphold").click();
    await expect(appeal).toHaveCount(0);
    await carol.getByTestId("appeal-status-upheld").click();
    await expect(carol.getByTestId("mod-appeal").filter({ hasText: `Please review ${tag}` })).toBeVisible();

    // Alice sees the outcome on the decision.
    await expect
      .poll(async () => {
        await alice.reload();
        return (await decided.getByTestId("support-appeal-status").innerText()).trim();
      }, { timeout: 20_000 })
      .not.toBe("");

    // Mobile: the console rail becomes chips, the inbox sections a row.
    await carol.setViewportSize(MOBILE);
    await carol.goto("/admin/moderation?tab=open");
    await expect(carol.getByTestId("admin-nav").filter({ visible: true }).first()).toBeVisible();
    await shot(carol, `admin-moderation-${lang}-mobile`);
    await alice.setViewportSize(MOBILE);
    await alice.reload();
    await shot(alice, `support-status-${lang}-mobile`);

    await Promise.all([bob.context().close(), carol.context().close(), alice.context().close(), bobApi.dispose()]);
  });

  test(`staff send a notice from Announcements; it reaches the member (${lang})`, async ({ browser }) => {
    test.setTimeout(120_000);
    const { a, c } = await sharedAccounts();
    promote(c.email);
    const tag = `notice ${lang} ${unique()}`;
    const carol = await open(browser, c, lang);
    await carol.goto("/admin");
    await carol.getByRole("navigation", { name: L[lang].consoleNav }).getByRole("link", { name: L[lang].notices }).click();
    await expect(carol).toHaveURL(/\/admin\/notices$/);
    const composer = carol.getByTestId("notice-composer");
    await composer.getByRole("searchbox").fill(a.email);
    await composer.getByRole("searchbox").press("Enter");
    await composer.getByRole("button", { name: lang === "ar" ? "إضافة" : "Add", exact: true }).first().click();
    await composer.locator("textarea").fill(tag);
    expect(await axe(carol, "[data-testid=notice-composer]")).toEqual([]);
    await shot(carol, `admin-notices-${lang}-desktop`);
    await carol.getByTestId("notice-send").click();
    await expect(carol.getByTestId("notices-history")).toContainText(tag);

    const alice = await open(browser, a, lang);
    await alice.goto("/home");
    await menu(alice, "support");
    await alice.getByTestId("support-tab-notices").click();
    await expect
      .poll(async () => {
        if (await alice.getByTestId("support-notice").filter({ hasText: tag }).count()) return true;
        await alice.reload();
        return false;
      }, { timeout: 45_000, intervals: [1500] })
      .toBe(true);
    await shot(alice, `support-notices-${lang}-desktop`);
    await Promise.all([carol.context().close(), alice.context().close()]);
  });

  test(`Community Standards from the footer and the menu (${lang})`, async ({ browser }) => {
    const { a } = await sharedAccounts();
    const page = await open(browser, a, lang);
    await page.goto("/home");
    await page.getByTestId("footer-standards").click();
    await expect(page).toHaveURL(/\/legal\/community-standards$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(L[lang].standards);
    expect(await axe(page, "[data-testid=community-standards]")).toEqual([]);
    await shot(page, `standards-${lang}-desktop`);
    await page.getByTestId("standards-support").click();
    await expect(page).toHaveURL(/\/support$/);
    await page.setViewportSize(MOBILE);
    await page.goto("/home");
    await menu(page, "communityStandards");
    await expect(page).toHaveURL(/\/legal\/community-standards$/);
    await shot(page, `standards-${lang}-mobile`);
    await page.context().close();
  });
}

test("a suspended account learns until when at sign-in, in Arabic and English", async ({ browser }) => {
  test.setTimeout(120_000);
  const { c } = await sharedAccounts();
  promote(c.email);
  // A throwaway account: never suspend the shared ones.
  const api = await request.newContext();
  const handle = `e2e_t7_${unique()}`;
  const email = `${handle}@example.com`;
  const res = await api.post(`${API}/auth/register/`, { data: signupData(email, handle, "موقوف", "t7") });
  expect(res.status(), await res.text()).toBe(201);
  const token = await verificationToken(api, email);
  expect((await api.post(`${API}/auth/verify-email/`, { data: { token } })).ok()).toBe(true);
  const id = (await res.json()).data.account_id as string;
  const until = new Date(Date.now() + 3 * 86_400_000).toISOString();
  const staff = await apiAs(c);
  const suspended = await staff.post(`${API}/admin/users/${id}/suspend/`, {
    data: { reason: "automated t7 check", until },
    headers: { "Idempotency-Key": `t7-${unique()}-suspend` },
  });
  expect(suspended.ok(), await suspended.text()).toBe(true);

  for (const lang of ["ar", "en"] as const) {
    const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL });
    const page = await context.newPage();
    await useLocale(page, lang);
    await page.setViewportSize(lang === "ar" ? MOBILE : DESKTOP);
    await page.goto("/login");
    await page.locator('input[autocomplete="username"]').fill(email);
    await page.locator('input[autocomplete="current-password"]').fill(PASSWORD);
    await page.locator('input[autocomplete="current-password"]').press("Enter");
    const notice = page.getByTestId("suspended-notice");
    await expect(notice).toContainText(L[lang].suspended);
    await expect(notice.getByRole("link")).toHaveAttribute("href", "/legal/community-standards");
    expect(await axe(page, "[data-testid=suspended-notice]")).toEqual([]);
    await shot(page, `login-suspended-${lang}-${lang === "ar" ? "mobile" : "desktop"}`);
    await context.close();
  }
  await Promise.all([api.dispose(), staff.dispose()]);
});
