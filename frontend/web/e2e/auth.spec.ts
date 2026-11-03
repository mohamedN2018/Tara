import { expect, request, test } from "@playwright/test";

import { pageAs, PASSWORD, sharedAccounts, unique, verificationToken } from "./helpers";

test("register, verify through the mailed link, log in", async ({ page }) => {
  const tag = unique();
  const email = `e2e_reg_${tag}@example.com`;
  const name = `سارة ${tag}`;

  await page.goto("/register");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");

  await page.getByLabel("الاسم الظاهر").fill(name);
  await page.getByLabel("اسم المستخدم").fill(`sara_${tag}`);
  await page.getByLabel("البريد الإلكتروني").fill(email);
  await page.getByLabel("كلمة المرور").fill(PASSWORD);

  const sent = page.waitForRequest("**/auth/register/");
  await page.getByRole("button", { name: "تسجيل" }).click();
  expect((await sent).postDataJSON()).toMatchObject({
    display_name: name,
    handle: `sara_${tag}`,
    language: "ar",
  });
  await expect(page.getByText("تم إنشاء الحساب")).toBeVisible();

  const mailpit = await request.newContext();
  const token = await verificationToken(mailpit, email);
  await mailpit.dispose();
  await page.goto(`/verify-email?token=${token}`);
  await expect(page.getByText("تم تأكيد البريد")).toBeVisible();

  await page.goto("/login");
  await page.getByLabel("البريد الإلكتروني").fill(email);
  await page.getByLabel("كلمة المرور").fill(PASSWORD);
  await page.getByRole("button", { name: "دخول" }).click();
  await expect(page).toHaveURL(/\/home$/);
  await expect(page.getByText(name).first()).toBeVisible();
});

test("registering shows the error on the field it belongs to", async ({ page }) => {
  await page.route("**/auth/register/", (route) =>
    route.fulfill({
      status: 400,
      json: {
        error: {
          code: "validation_error",
          message: "x",
          details: [
            { field: "password", code: "weak_password", message: "too common" },
            { field: "handle", code: "validation_error", message: "bad" },
          ],
        },
      },
    }),
  );
  await page.goto("/register");
  await page.getByLabel("الاسم الظاهر").fill("سارة");
  await page.getByLabel("اسم المستخدم").fill("sara_taken");
  await page.getByLabel("البريد الإلكتروني").fill("x@example.com");
  await page.getByLabel("كلمة المرور").fill(PASSWORD);
  await page.getByRole("button", { name: "تسجيل" }).click();
  await expect(page.getByText("كلمة المرور هذه سهلة التخمين")).toBeVisible();
  await expect(page.getByLabel("كلمة المرور")).toHaveAttribute("aria-invalid", "true");
});

test("a wrong password stays on the login page with a translated error", async ({ page }) => {
  const { a } = await sharedAccounts();
  await page.goto("/login");
  await page.getByLabel("البريد الإلكتروني").fill(a.email);
  await page.getByLabel("كلمة المرور").fill("definitely-wrong-password");
  await page.getByRole("button", { name: "دخول" }).click();
  await expect(page.getByRole("alert")).toHaveText("البريد الإلكتروني أو كلمة المرور غير صحيحة.");
});

test("the redirect param can't leave the site", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await (await browser.newContext({ baseURL: "http://127.0.0.1:5173" })).newPage();
  await page.goto("/login?redirect=//evil.example/");
  await page.getByLabel("البريد الإلكتروني").fill(a.email);
  await page.getByLabel("كلمة المرور").fill(PASSWORD);
  await page.getByRole("button", { name: "دخول" }).click();
  await expect(page).toHaveURL(/127\.0\.0\.1:5173\/home$/);
});

test("the API being down does not end the session", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  await page.goto("/home");
  await expect(page.getByText(a.name).first()).toBeVisible();

  await page.route("**/api/v1/**", (route) => route.fulfill({ status: 503, body: "down" }));
  await page.reload();
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByText("تعذّر الوصول إلى الخادم")).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("tara.refresh"))).toBeTruthy();

  await page.unroute("**/api/v1/**");
  await page.getByRole("button", { name: "إعادة المحاولة" }).click();
  await expect(page).toHaveURL(/\/home$/);
});

test("two tabs refreshing at once keep the session alive", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const first = await pageAs(browser, a);
  await first.goto("/home");
  await expect(first.getByText(a.name).first()).toBeVisible();
  const second = await first.context().newPage();
  await second.goto("/home");
  await expect(second.getByText(a.name).first()).toBeVisible();

  // Invalidate the access token in shared storage: both tabs get a 401 together.
  await first.evaluate(() => localStorage.setItem("tara.access", "expired.invalid.token"));
  await Promise.all([first.reload(), second.reload()]);
  await expect(first.getByText(a.name).first()).toBeVisible();
  await expect(second.getByText(a.name).first()).toBeVisible();

  // Reuse detection would have revoked the session: prove it's still usable.
  await first.reload();
  await expect(first).toHaveURL(/\/home$/);
  await expect(first.getByText(a.name).first()).toBeVisible();
});

test("logging out in one tab ends the session in the other", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const first = await pageAs(browser, a);
  await first.goto("/friends");
  await expect(first.getByText(a.name).first()).toBeVisible();
  const second = await first.context().newPage();
  await second.goto("/home");
  await expect(second.getByText(a.name).first()).toBeVisible();

  await first.getByRole("button", { name: "الملف الشخصي" }).click();
  await first.getByRole("menuitem", { name: "تسجيل الخروج" }).click();
  await expect(first).toHaveURL(/\/login$/);
  await expect(second).toHaveURL(/\/login$/);
  expect(await first.evaluate(() => localStorage.getItem("tara.directory.v2"))).toBeNull();
  expect(await first.evaluate(() => localStorage.getItem("tara.refresh"))).toBeNull();
});

test("a chunk missing after a deploy reloads the page once", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  await page.goto("/home");
  await expect(page.getByText(a.name).first()).toBeVisible();

  let blocked = 0;
  await page.route("**/src/views/SavedView.vue*", (route) => {
    if (blocked++ === 0) return route.abort();
    return route.continue();
  });
  await page.getByRole("link", { name: "المحفوظات" }).first().click();
  await expect(page).toHaveURL(/\/saved$/);
  await expect(page.getByRole("heading", { name: "المحفوظات" })).toBeVisible();
  expect(blocked).toBe(2);
});
