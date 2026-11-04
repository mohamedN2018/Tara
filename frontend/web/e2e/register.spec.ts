// Full registration (plan 08, track 1D): the new fields against the real stack,
// the live handle check, the server's own password check, English, and axe.
import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, request, test } from "@playwright/test";

import { API, fillRegisterForm, PASSWORD, sharedAccounts, unique, verificationToken } from "./helpers";

async function seriousA11y(page: Page): Promise<string[]> {
  const result = await new AxeBuilder({ page }).include("main").withTags(["wcag2a", "wcag2aa"]).analyze();
  return result.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id);
}

/** A small real PNG, drawn by the browser (no binary fixture in the repo). */
async function pngBytes(page: Page): Promise<Buffer> {
  const dataUrl = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 96;
    const ctx = canvas.getContext("2d")!;
    const gradient = ctx.createLinearGradient(0, 0, 96, 96);
    gradient.addColorStop(0, "#6A00F4");
    gradient.addColorStop(1, "#FF4ED8");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 96, 96);
    return canvas.toDataURL("image/png");
  });
  return Buffer.from(dataUrl.split(",")[1], "base64");
}

test("a full Arabic registration with the new fields, then the profile photo step", async ({ page }) => {
  const tag = unique();
  const handle = `reg_ar_${tag}`;
  const email = `e2e_${handle}@example.com`;

  await page.goto("/register");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await fillRegisterForm(page, { first: "ليلى", last: `أحمد${tag}`, handle, email, dob: ["14", "3", "1995"] });

  // Live, debounced check against profile.
  await expect(page.getByTestId("handle-status")).toHaveAttribute("data-state", "available");
  await expect(page.getByTestId("handle-status")).toContainText(`@${handle} متاح`);
  await expect(page.getByTestId("password-strength")).toContainText("قوة كلمة المرور: قوية");
  await page.getByLabel("أنثى").check();

  const sent = page.waitForRequest("**/auth/register/");
  await page.getByRole("button", { name: "تسجيل", exact: true }).click();
  const body = (await sent).postDataJSON();
  expect(body).toMatchObject({
    first_name: "ليلى",
    last_name: `أحمد${tag}`,
    handle,
    date_of_birth: "1995-03-14",
    gender: "female",
    accept_terms: true,
    language: "ar",
  });
  expect(body.terms_version).toBeTruthy();
  await expect(page.getByText("تم إنشاء الحساب")).toBeVisible();

  const mailpit = await request.newContext();
  const token = await verificationToken(mailpit, email);
  await mailpit.dispose();
  await page.goto(`/verify-email?token=${token}`);
  await expect(page.getByText("تم تأكيد البريد")).toBeVisible();
  await expect(page.getByText("سجّل الدخول وأضف صورة شخصية")).toBeVisible();

  await page.goto("/login");
  await page.getByLabel("البريد الإلكتروني").first().fill(email);
  await page.getByLabel("كلمة المرور", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "دخول", exact: true }).click();
  await expect(page).toHaveURL(/\/home$/);

  // The display name is built from the first and last names.
  await expect(page.getByText(`ليلى أحمد${tag}`).first()).toBeVisible();

  const card = page.getByTestId("complete-profile");
  await expect(card).toBeVisible();
  await expect(card.getByRole("heading", { name: "أكمل ملفك الشخصي" })).toBeVisible();
  await card.getByLabel("إضافة صورة").setInputFiles({
    name: "me.png",
    mimeType: "image/png",
    buffer: await pngBytes(page),
  });
  await expect(card.getByText("تم تعيين صورتك الشخصية.")).toBeVisible({ timeout: 30_000 });
  await card.getByRole("button", { name: "تم" }).click();
  await expect(card).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("complete-profile")).toHaveCount(0);
});

test("a taken username is flagged before submitting", async ({ page }) => {
  const { a } = await sharedAccounts();
  let posted = false;
  page.on("request", (r) => {
    if (r.url().includes("/auth/register/")) posted = true;
  });
  await page.goto("/register");
  await fillRegisterForm(page, { first: "سارة", last: "علي", handle: a.handle, email: `taken_${unique()}@example.com` });
  const status = page.getByTestId("handle-status");
  await expect(status).toHaveAttribute("data-state", "taken");
  await expect(status).toHaveText("اسم المستخدم هذا غير متاح. جرّب اسمًا آخر.");
  await expect(page.getByLabel("اسم المستخدم", { exact: true })).toHaveAttribute("aria-invalid", "true");

  await page.getByRole("button", { name: "تسجيل", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("راجع الحقول المميّزة.");
  await expect(page.getByLabel("اسم المستخدم", { exact: true })).toBeFocused();
  expect(posted).toBe(false);
});

test("the server's own password_mismatch lands on the confirm field", async ({ page }) => {
  // The form never sends a mismatch, so change the confirmation on its way out:
  // the answer is the real server's.
  let status = 0;
  await page.route("**/auth/register/", async (route) => {
    const body = route.request().postDataJSON();
    const response = await route.fetch({ postData: JSON.stringify({ ...body, password_confirm: `${PASSWORD}x` }) });
    status = response.status();
    const json = await response.json();
    expect(json.error.details).toContainEqual(expect.objectContaining({ field: "password_confirm", code: "password_mismatch" }));
    await route.fulfill({ response });
  });
  await page.goto("/register");
  const handle = `reg_pm_${unique()}`;
  await fillRegisterForm(page, { first: "عمر", last: "نبيل", handle, email: `e2e_${handle}@example.com` });
  await page.getByRole("button", { name: "تسجيل", exact: true }).click();
  await expect(page.getByText("كلمتا المرور غير متطابقتين.")).toBeVisible();
  await expect(page.getByLabel("تأكيد كلمة المرور")).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByLabel("تأكيد كلمة المرور")).toBeFocused();
  expect(status).toBe(400);
});

test("the API refuses a sign-up without consent, under 13, or with mismatched passwords", async () => {
  const api = await request.newContext();
  try {
    const base = (tag: string) => ({
      email: `e2e_api_${tag}@example.com`,
      first_name: "Api",
      last_name: "Check",
      password: PASSWORD,
      password_confirm: PASSWORD,
      date_of_birth: "1990-01-01",
      accept_terms: true,
      terms_version: "2026-11-04-draft",
      privacy_version: "2026-11-04-draft",
    });
    const year = new Date().getFullYear();
    const cases: Array<[Record<string, unknown>, string, string]> = [
      [{ accept_terms: false }, "accept_terms", "consent_required"],
      [{ date_of_birth: `${year - 10}-01-01` }, "date_of_birth", "age_below_minimum"],
      [{ password_confirm: "Different-Pass-1!" }, "password_confirm", "password_mismatch"],
    ];
    for (const [change, field, code] of cases) {
      const res = await api.post(`${API}/auth/register/`, { data: { ...base(unique()), ...change } });
      expect(res.status()).toBe(400);
      const { error } = await res.json();
      expect(error.details).toContainEqual(expect.objectContaining({ field, code }));
    }
  } finally {
    await api.dispose();
  }
});

test("the English form registers too", async ({ browser, baseURL }) => {
  const context = await browser.newContext({ baseURL });
  await context.addInitScript(() => localStorage.setItem("tara.locale", "en"));
  const page = await context.newPage();
  const handle = `reg_en_${unique()}`;
  await page.goto("/register");
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  await fillRegisterForm(page, { first: "Omar", last: "Nabil", handle, email: `e2e_${handle}@example.com` }, "en");
  await expect(page.getByTestId("handle-status")).toHaveText(`@${handle} is available.`);
  await page.getByLabel("Prefer not to say").check();
  const sent = page.waitForRequest("**/auth/register/");
  await page.getByRole("button", { name: "Sign up", exact: true }).click();
  expect((await sent).postDataJSON()).toMatchObject({ first_name: "Omar", gender: "prefer_not_to_say", language: "en" });
  await expect(page.getByText("Account created.")).toBeVisible();
  await context.close();
});

test("the sign-up form has no serious accessibility problems, in Arabic and English", async ({ browser, baseURL }) => {
  for (const locale of ["ar", "en"]) {
    const context = await browser.newContext({ baseURL });
    await context.addInitScript((l) => localStorage.setItem("tara.locale", l), locale);
    const page = await context.newPage();
    await page.goto("/register");
    await expect(page.getByTestId("register-form")).toBeVisible();
    await page.getByLabel(locale === "ar" ? "كلمة المرور" : "Password", { exact: true }).fill("short");
    await page.getByLabel(locale === "ar" ? "مخصص" : "Custom", { exact: true }).check();
    expect(await seriousA11y(page)).toEqual([]);
    await context.close();
  }
});
