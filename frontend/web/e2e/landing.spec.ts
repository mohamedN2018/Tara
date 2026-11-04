import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { BASE_URL, PASSWORD, pageAs, sharedAccounts, unique } from "./helpers";

// The visitor landing on `/` (1C, decision 5.7): the sign-in card on the page
// itself, email or username (5.6), show/hide password and "Remember me".
// Arabic (RTL) is the default locale.

async function seriousViolations(page: Page) {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  return result.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id);
}

const card = (page: Page) => page.getByRole("region", { name: /تسجيل الدخول إلى تارا|Log in to Tara/ });

test("a visitor on / sees the card, logs in and lands on /home", async ({ page }) => {
  const { a } = await sharedAccounts();
  await page.goto("/");
  await expect(page).toHaveURL(`${BASE_URL}/`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(card(page)).toBeVisible();
  await expect(page.getByRole("link", { name: "إنشاء حساب جديد" })).toHaveAttribute("href", "/register");
  await expect(page.getByRole("link", { name: "نسيت كلمة المرور؟" })).toHaveAttribute("href", "/forgot-password");
  await expect(page.getByRole("link", { name: "إنشاء صفحة" })).toBeVisible();

  await page.getByLabel("البريد الإلكتروني أو اسم المستخدم").fill(a.email);
  await page.getByLabel("كلمة المرور").fill(PASSWORD);
  const sent = page.waitForRequest("**/auth/login/");
  await page.getByRole("button", { name: "دخول" }).click();
  expect((await sent).postDataJSON()).toEqual({ identifier: a.email, password: PASSWORD, remember: true });
  await expect(page).toHaveURL(/\/home$/);
  await expect(page.getByText(a.name).first()).toBeVisible();
});

test("a signed-in user visiting / is sent to /home", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  await page.goto("/");
  await expect(page).toHaveURL(/\/home$/);
  await expect(page.getByText(a.name).first()).toBeVisible();
});

test("the password toggle switches the field type and aria-pressed", async ({ page }) => {
  await page.goto("/");
  const password = page.getByLabel("كلمة المرور");
  const toggle = page.getByRole("button", { name: "إظهار كلمة المرور" });
  await password.fill("secret-value");
  await expect(password).toHaveAttribute("type", "password");
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await toggle.click();
  await expect(password).toHaveAttribute("type", "text");
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(password).toHaveValue("secret-value");
  await toggle.click();
  await expect(password).toHaveAttribute("type", "password");
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
});

test("logging in by username, with ?next= kept", async ({ page }) => {
  const { a } = await sharedAccounts();
  await page.goto("/login?next=/friends");
  await page.getByLabel("البريد الإلكتروني أو اسم المستخدم").fill(`@${a.handle.toUpperCase()}`);
  await page.getByLabel("كلمة المرور").fill(PASSWORD);
  await page.getByRole("button", { name: "دخول" }).click();
  await expect(page).toHaveURL(/\/friends$/);
  await expect(page.getByText(a.name).first()).toBeVisible();
});

test("an unknown username and a wrong password get the same message", async ({ page }) => {
  const { a } = await sharedAccounts();
  const expected = "البريد الإلكتروني أو اسم المستخدم أو كلمة المرور غير صحيحة.";
  await page.goto("/");
  await page.getByLabel("البريد الإلكتروني أو اسم المستخدم").fill(a.handle);
  await page.getByLabel("كلمة المرور").fill("definitely-wrong-password");
  await page.getByRole("button", { name: "دخول" }).click();
  await expect(page.getByRole("alert")).toHaveText(expected);

  await page.getByLabel("البريد الإلكتروني أو اسم المستخدم").fill(`nobody_${unique()}`);
  await page.getByRole("button", { name: "دخول" }).click();
  await expect(page.getByRole("alert")).toHaveText(expected);
  await expect(page).toHaveURL(`${BASE_URL}/`);
});

test("without Remember me the session ends when the browser closes", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const context = await browser.newContext({ baseURL: BASE_URL });
  const page = await context.newPage();
  await page.goto("/");
  await page.getByLabel("البريد الإلكتروني أو اسم المستخدم").fill(a.email);
  await page.getByLabel("كلمة المرور").fill(PASSWORD);
  await page.getByLabel("تذكرني").uncheck();
  const sent = page.waitForRequest("**/auth/login/");
  await page.getByRole("button", { name: "دخول" }).click();
  expect((await sent).postDataJSON()).toMatchObject({ remember: false });
  await expect(page).toHaveURL(/\/home$/);

  // Still signed in while the browser stays open...
  await page.reload();
  await expect(page).toHaveURL(/\/home$/);

  // ...but closing it drops session cookies: the next visit starts signed out.
  const logout = page.waitForRequest("**/auth/logout/");
  await context.clearCookies({ name: "tara_browser_session" });
  await page.goto("/home");
  await logout;
  await expect(page).toHaveURL(/\/login\?redirect=/);
  expect(await page.evaluate(() => localStorage.getItem("tara.refresh"))).toBeNull();
  await context.close();
});

test("the landing in Arabic and English, switched from the languages row", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(card(page)).toContainText("تسجيل الدخول إلى تارا");
  const languages = page.getByRole("navigation", { name: "اللغات" });
  await expect(languages.getByRole("button", { name: "العربية" })).toHaveAttribute("aria-pressed", "true");

  await languages.getByRole("button", { name: "English" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("heading", { name: "Log in to Tara" })).toBeVisible();
  await expect(page.getByLabel("Email or username")).toBeVisible();
  await expect(page.getByRole("button", { name: "Show password" })).toBeVisible();
  await expect(page.getByLabel("Remember me")).toBeChecked();
  await expect(page.getByRole("link", { name: "Create new account" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Create a Page" })).toBeVisible();
  const english = page.getByRole("navigation", { name: "Languages" });
  await expect(english.getByRole("button", { name: "English" })).toHaveAttribute("aria-pressed", "true");

  await english.getByRole("button", { name: "العربية" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
});

test("the landing has no serious accessibility violations, in both languages", async ({ page }) => {
  await page.goto("/");
  await expect(card(page)).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);

  await page.addInitScript(() => localStorage.setItem("tara.locale", "en"));
  await page.reload();
  await expect(page.getByRole("heading", { name: "Log in to Tara" })).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);
});

test("the landing fits a phone screen without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(card(page)).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
