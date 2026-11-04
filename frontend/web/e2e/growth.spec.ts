import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, request, test } from "@playwright/test";

import {
  type Account,
  API,
  PASSWORD,
  apiAs,
  pageAs,
  sharedAccounts,
  signupData,
  unique,
  verificationToken,
} from "./helpers";

const promote = (email: string) =>
  execSync(`docker exec tara-identity-1 python manage.py create_admin ${email}`, { stdio: "pipe" });

// The campaign test grants Bob `ad_reviewer`; take it back even when a test
// failed half way, so the next test (and the next run) starts without it.
async function revokeReviewer() {
  const { b, c } = await sharedAccounts();
  promote(c.email);
  const admin = await apiAs(c);
  await admin.delete(`${API}/admin/roles/`, { data: { account_id: b.id, role: "ad_reviewer" } });
  await admin.dispose();
}
test.beforeEach(revokeReviewer);
test.afterEach(revokeReviewer);

test("campaign to feed: review, serve token, stats, and forged events are refused", async ({ browser }) => {
  const { a, b, c } = await sharedAccounts();
  const tag = unique();
  promote(c.email); // Carol runs the admin console.

  // The advertiser builds a campaign in the dashboard.
  const advertiser = await pageAs(browser, a);
  await advertiser.goto("/ads");
  await advertiser.getByRole("button", { name: "حملة جديدة" }).click();
  await advertiser.getByLabel("اسم الحملة").fill(`حملة ${tag}`);
  await advertiser.getByLabel("الميزانية").fill("50");
  await advertiser.getByRole("button", { name: "إنشاء الحملة" }).click();
  await expect(advertiser).toHaveURL(/\/ads\/campaigns\//);
  await advertiser.getByRole("textbox", { name: "اسم المجموعة الإعلانية" }).fill(`set ${tag}`);
  await advertiser.getByRole("button", { name: "إضافة مجموعة إعلانية" }).click();
  await advertiser.getByRole("textbox", { name: "العنوان" }).fill(`إعلان ${tag}`);
  await advertiser.getByRole("button", { name: "إضافة إعلان" }).click();
  await expect(advertiser.getByTestId("creative")).toContainText("قيد المراجعة");

  // An admin grants the reviewer role; it reaches Bob's token on his next login.
  const admin = await pageAs(browser, c);
  await admin.goto("/admin");
  await admin.getByRole("textbox", { name: "بريد الحساب" }).fill(b.email);
  await admin.getByRole("combobox", { name: "الدور" }).selectOption("ad_reviewer");
  await admin.getByRole("button", { name: "منح الدور" }).click();
  await expect(admin.getByTestId("role-holders")).toContainText(b.email);

  const reviewer = await pageAs(browser, b);
  await reviewer.goto("/ads/review");
  const item = reviewer.getByTestId("review-item").filter({ hasText: tag });
  await expect(item).toBeVisible();
  await item.getByRole("button", { name: "موافقة" }).click();
  await expect(item).toHaveCount(0);

  // Without a token, or with someone else's, nothing is spent.
  const bobApi = await apiAs(b);
  const feed = (await (await bobApi.get(`${API}/feed/`)).json()) as { sponsored: { creative_id: string; token: string; headline: string } };
  expect(feed.sponsored.headline).toBe(`إعلان ${tag}`);
  const carolApi = await apiAs(c);
  const stolen = await carolApi.post(`${API}/ads/events/`, {
    data: { kind: "click", creative_id: feed.sponsored.creative_id, token: feed.sponsored.token },
    headers: { "Idempotency-Key": unique() },
  });
  expect(stolen.status()).toBe(403);
  const missing = await carolApi.post(`${API}/ads/events/`, {
    data: { kind: "click", creative_id: feed.sponsored.creative_id },
    headers: { "Idempotency-Key": unique() },
  });
  expect(missing.status()).toBe(400);

  // The real card reports its impression and click.
  const viewer = await pageAs(browser, b);
  await viewer.goto("/home");
  const card = viewer.getByTestId("sponsored");
  await card.scrollIntoViewIfNeeded();
  await expect(card).toContainText(`إعلان ${tag}`);
  // The CTA: the card also has a "Hide ad" X since 2B.
  await card.getByRole("button", { name: "اعرف المزيد" }).click();

  await expect
    .poll(async () => {
      await advertiser.reload();
      return advertiser.getByTestId("campaign-stats").innerText();
    }, { timeout: 15_000 })
    .toMatch(/مرات الظهور\s*1[\s\S]*النقرات\s*1/);

  await advertiser.getByRole("button", { name: "إيقاف مؤقت" }).click();
  await expect(advertiser.getByRole("button", { name: "استئناف" })).toBeVisible();

  // Revoke the role again so later runs start clean.
  await admin.reload();
  await admin
    .getByTestId("role-holders")
    .getByRole("button", { name: new RegExp(`${b.email.replace(/[.]/g, "\\.")}`) })
    .click();
  await expect(admin.getByTestId("role-holders")).not.toContainText(b.email);
});

test("a role reaches the token: the review page opens only after a grant", async ({ browser }) => {
  const { b } = await sharedAccounts();
  const page = await pageAs(browser, b);
  await page.goto("/ads/review");
  await expect(page).toHaveURL(/\/home$/);
  const queue = await (await apiAs(b)).get(`${API}/ads/review-queue/`);
  expect(queue.status()).toBe(403);
});

test("feature flags can be added and toggled, and only admins see the panels", async ({ browser }) => {
  const { b, c } = await sharedAccounts();
  const key = `flag_${unique()}`;
  promote(c.email);
  const admin = await pageAs(browser, c);
  await admin.goto("/admin");
  await admin.getByRole("textbox", { name: "مفتاح جديد" }).fill(key);
  await admin.getByRole("button", { name: "إضافة", exact: true }).click();
  const row = admin.getByTestId("feature-flags").locator("li", { hasText: key });
  await row.getByRole("checkbox").check();
  await row.getByRole("spinbutton").fill("25");
  await row.getByRole("spinbutton").blur();
  await expect
    .poll(async () => {
      const flag = (await (await (await apiAs(b)).get(`${API}/admin/feature-flags/${key}/`)).json()).data;
      return [flag.enabled, flag.rollout_pct];
    })
    .toEqual([true, 25]);

  const forbidden = await (await apiAs(b)).patch(`${API}/admin/feature-flags/${key}/`, { data: { enabled: false } });
  expect(forbidden.status()).toBe(403);
});

// ---- Capability matrix, unified audit and monitor (roadmap 8.1, 8.11, 8.12) ----

const ANALYST_MONITOR = { role: "analyst", capability: "admin.monitor.view" };

// The matrix test grants analysts the monitor; put the default back even when it failed half way.
async function resetMatrix() {
  const { c } = await sharedAccounts();
  promote(c.email);
  const admin = await apiAs(c);
  await admin.put(`${API}/admin/capabilities/`, { data: { changes: [{ ...ANALYST_MONITOR, state: "default" }] } });
  await admin.dispose();
}

/** Show only `action` on the audit page, and wait until an entry matching `text` arrives (events are async). */
async function auditShows(page: import("@playwright/test").Page, action: string, text: string) {
  await page.getByRole("combobox", { name: "الإجراء" }).selectOption(action);
  await expect
    .poll(
      async () => {
        // Count only once the list has reloaded: while loading, the table is not shown.
        await Promise.all([
          page.waitForResponse((r) => r.url().includes("/admin/audit/?") && r.request().method() === "GET"),
          page.getByRole("button", { name: "تطبيق" }).click(),
        ]);
        const rows = page.getByTestId("audit-entries").locator(`tr[data-action="${action}"]`);
        await rows.first().waitFor({ timeout: 2_000 }).catch(() => {});
        return rows.filter({ hasText: text }).count();
      },
      { timeout: 30_000 },
    )
    .toBeGreaterThan(0);
}

test("an admin edits the capability matrix after a diff preview, and the change is audited", async ({ browser }) => {
  const { c } = await sharedAccounts();
  await resetMatrix();
  try {
    const admin = await pageAs(browser, c);
    await admin.goto("/admin/capabilities");
    const matrix = admin.getByTestId("capability-matrix");
    // The admin role is locked: always on, never editable.
    await expect(matrix.getByRole("checkbox", { name: "عرض المراقبة لدور مدير" })).toBeDisabled();
    await expect(matrix.getByRole("checkbox", { name: "عرض المراقبة لدور مدير" })).toBeChecked();

    const cell = matrix.getByRole("checkbox", { name: "عرض المراقبة لدور محلل" });
    await expect(cell).not.toBeChecked();
    await cell.check();
    await expect(matrix.getByRole("button", { name: "إرجاع عرض المراقبة لدور محلل إلى الافتراضي" })).toBeVisible();

    await admin.getByRole("button", { name: "مراجعة التغييرات" }).click();
    const preview = admin.getByRole("dialog", { name: "مراجعة التغييرات" });
    await expect(preview.getByTestId("matrix-diff").getByRole("listitem")).toHaveCount(1);
    await expect(preview.getByTestId("matrix-diff")).toContainText("منح");
    await expect(preview.getByTestId("matrix-diff")).toContainText("عرض المراقبة لدور محلل");
    await preview.getByRole("button", { name: "حفظ التغييرات" }).click();
    await expect(preview).toHaveCount(0);

    // The saved matrix comes back from identity with the grant in place.
    await admin.reload();
    await expect(admin.getByTestId("capability-matrix").getByRole("checkbox", { name: "عرض المراقبة لدور محلل" })).toBeChecked();

    await admin.goto("/admin/audit");
    await auditShows(admin, "capability.changed", "analyst");
  } finally {
    await resetMatrix();
  }
});

test("the audit log filters by action and downloads a CSV that Excel reads as UTF-8", async ({ browser }) => {
  const { b, c } = await sharedAccounts();
  promote(c.email);
  const carolApi = await apiAs(c);
  expect((await carolApi.post(`${API}/admin/roles/`, { data: { account_id: b.id, role: "ad_reviewer" } })).status()).toBe(201);

  const admin = await pageAs(browser, c);
  await admin.goto("/admin/audit");
  await auditShows(admin, "role.granted", b.id);

  const [download] = await Promise.all([admin.waitForEvent("download"), admin.getByRole("button", { name: "تنزيل CSV" }).click()]);
  expect(download.suggestedFilename()).toMatch(/^tara-audit-\d{4}-\d{2}-\d{2}\.csv$/);
  const bytes = readFileSync((await download.path()) as string);
  expect([...bytes.subarray(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
  const lines = bytes.subarray(3).toString("utf8").split(/\r?\n/);
  expect(lines[0]).toMatch(/action/);
  expect(lines.some((line) => line.includes("role.granted") && line.includes(b.id))).toBe(true);
});

test("a request id forged by the client never reaches the audit log", async () => {
  const { c } = await sharedAccounts();
  promote(c.email);
  const carolApi = await apiAs(c);
  const forged = `forged-${unique()}`;
  const exported = await carolApi.get(`${API}/admin/audit/export.csv`, { headers: { "X-Request-Id": forged } });
  expect(exported.status()).toBe(200);

  const res = await carolApi.get(`${API}/admin/audit/`, { params: { action: "audit.exported", actor: c.id, limit: 1 } });
  expect(res.status()).toBe(200);
  const [entry] = (await res.json()).data as { request_id: string; actor_id: string }[];
  expect(entry.actor_id).toBe(c.id);
  expect(entry.request_id).not.toBe("");
  expect(entry.request_id).not.toContain(forged);
});

test("the monitor shows service health and platform statistics, in Arabic and English", async ({ browser }) => {
  const { c } = await sharedAccounts();
  promote(c.email);
  const admin = await pageAs(browser, c);
  await admin.goto("/admin/monitor");
  await expect(admin.getByTestId("service-tiles").locator('[data-service="identity"]')).toBeVisible();
  const stats = admin.getByTestId("platform-stats");
  await expect(stats.getByRole("listitem")).toHaveCount(5);
  await expect(stats.locator('[data-metric="accounts"]')).toContainText("الحسابات");
  await expect(admin.getByRole("navigation", { name: "أقسام الإدارة" }).getByRole("link", { name: "المراقبة" })).toBeVisible();

  const english = await pageAs(browser, c);
  await english.addInitScript(() => localStorage.setItem("tara.locale", "en"));
  await english.goto("/admin/monitor");
  await expect(english.getByRole("heading", { name: "Platform statistics" })).toBeVisible();
  await expect(english.getByTestId("platform-stats").locator('[data-metric="open_cases"]')).toContainText("Open moderation cases");
});

test("without a capability there is no admin menu, the routes redirect and the API answers 403", async ({ browser }) => {
  const { b } = await sharedAccounts();
  const page = await pageAs(browser, b);
  await page.goto("/home");
  await expect(page.getByRole("link", { name: "الإدارة" })).toHaveCount(0);
  await page.getByRole("button", { name: "القائمة" }).click();
  await expect(page.getByRole("menuitem", { name: "الإدارة" })).toHaveCount(0);

  for (const path of ["/admin", "/admin/audit", "/admin/capabilities", "/admin/monitor"]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/home$/);
  }
  const bobApi = await apiAs(b);
  for (const path of ["/admin/audit/", "/admin/audit/export.csv", "/admin/capabilities/", "/admin/monitor/"]) {
    expect((await bobApi.get(`${API}${path}`)).status(), path).toBe(403);
  }
});

// ---- User management console (roadmap 8.6) and suspensions (8.4) ----

/**
 * A throwaway account for the suspension test. Never suspend the shared e2e
 * accounts: every other spec signs in with them.
 */
async function throwawayAccount(): Promise<Account> {
  const api = await request.newContext();
  try {
    const tag = unique();
    const handle = `e2e_s_${tag}`;
    const email = `${handle}@example.com`;
    const name = `موقوف ${tag}`;
    const res = await api.post(`${API}/auth/register/`, { data: signupData(email, handle, "موقوف", tag) });
    expect(res.status(), await res.text()).toBe(201);
    const token = await verificationToken(api, email);
    expect((await api.post(`${API}/auth/verify-email/`, { data: { token } })).ok()).toBe(true);
    return { email, handle, name, id: (await res.json()).data.account_id };
  } finally {
    await api.dispose();
  }
}

async function signIn(email: string): Promise<{ status: number; refresh?: string }> {
  const api = await request.newContext();
  try {
    const res = await api.post(`${API}/auth/login/`, { data: { email, password: PASSWORD } });
    const body = res.ok() ? await res.json() : null;
    return { status: res.status(), refresh: body?.data?.refresh_token };
  } finally {
    await api.dispose();
  }
}

async function seriousA11y(page: Page): Promise<string[]> {
  const result = await new AxeBuilder({ page }).include("main").withTags(["wcag2a", "wcag2aa"]).analyze();
  return result.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id);
}

test("staff search accounts, reveal personal data with an audited reason, and suspend then lift", async ({ browser }) => {
  const { c } = await sharedAccounts();
  promote(c.email);
  const target = await throwawayAccount();
  const before = await signIn(target.email);
  expect(before.status).toBe(200);

  // Search by email: results carry the masked address only.
  const admin = await pageAs(browser, c);
  await admin.goto("/admin");
  await admin.getByRole("navigation", { name: "أقسام الإدارة" }).getByRole("link", { name: "المستخدمون" }).click();
  await expect(admin).toHaveURL(/\/admin\/users$/);
  const searchForm = admin.getByRole("search", { name: "البحث في الحسابات" });
  await searchForm.getByRole("searchbox").fill(target.email);
  await searchForm.getByRole("button", { name: "بحث", exact: true }).click();
  const results = admin.getByTestId("user-results");
  await expect(results.locator(`tr[data-account="${target.id}"]`)).toBeVisible();
  await expect(results).not.toContainText(target.email);
  expect(await seriousA11y(admin)).toEqual([]);

  // The account page: masked until revealed; every view is audited.
  // Names come from profile; the link always exists, whatever it shows.
  await results.locator(`tr[data-account="${target.id}"]`).getByRole("link").click();
  await expect(admin).toHaveURL(new RegExp(`/admin/users/${target.id}$`));
  await expect(admin.getByTestId("user-status")).toHaveText("نشط");
  await expect(admin.getByTestId("user-overview")).not.toContainText(target.email);
  expect(await seriousA11y(admin)).toEqual([]);

  // Reveal needs a typed reason, and that reason lands in the audit log.
  const reason = `تذكرة دعم ${unique()}`;
  await admin.getByRole("button", { name: "إظهار البيانات الشخصية" }).first().click();
  const reveal = admin.getByRole("dialog", { name: "إظهار البيانات الشخصية" });
  await expect(reveal.getByRole("button", { name: "إظهار", exact: true })).toBeDisabled();
  await reveal.getByRole("textbox", { name: "السبب" }).fill(reason);
  await reveal.getByRole("button", { name: "إظهار", exact: true }).click();
  await expect(reveal).toHaveCount(0);
  await expect(admin.getByTestId("revealed-email")).toHaveText(target.email);
  await admin.getByRole("tab", { name: "الجلسات" }).click();
  await expect(admin.getByTestId("user-sessions").getByRole("listitem")).not.toHaveCount(0);

  const carolApi = await apiAs(c);
  const audited = async (action: string) =>
    (await (await carolApi.get(`${API}/admin/audit/`, { params: { action, target_id: target.id } })).json()).data as {
      actor_id: string;
      reason: string;
    }[];
  const [revealed] = await audited("user.personal_data.revealed");
  expect(revealed.actor_id).toBe(c.id);
  expect(revealed.reason).toBe(reason);
  expect((await audited("user.viewed")).length).toBeGreaterThan(0);

  // Suspend, after a confirmation: login and refresh stop working at once.
  await admin.getByRole("button", { name: "إيقاف", exact: true }).click();
  const suspend = admin.getByRole("dialog", { name: /^إيقاف/ });
  await suspend.getByRole("textbox", { name: "السبب" }).fill("حساب اختبار آلي");
  await suspend.getByRole("button", { name: "إيقاف الحساب" }).click();
  await expect(suspend).toHaveCount(0);
  await expect(admin.getByTestId("user-status")).toHaveText("موقوف");
  expect((await signIn(target.email)).status).toBe(403);
  const anon = await request.newContext();
  const refreshed = await anon.post(`${API}/auth/refresh/`, { data: { refresh_token: before.refresh } });
  expect(refreshed.status()).toBe(401);
  await anon.dispose();

  // Admin's audit consumer records the suspension (events are asynchronous).
  await admin.getByRole("tab", { name: "النشاط" }).click();
  await expect
    .poll(async () => (await audited("account.suspended")).length, { timeout: 30_000 })
    .toBeGreaterThan(0);

  // Lift it: the account can sign in again.
  await admin.reload();
  await admin.getByRole("button", { name: "رفع الإيقاف" }).click();
  const lift = admin.getByRole("dialog", { name: /رفع الإيقاف/ });
  await lift.getByRole("textbox", { name: "السبب" }).fill("انتهى الاختبار");
  await lift.getByRole("button", { name: "رفع الإيقاف" }).click();
  await expect(lift).toHaveCount(0);
  await expect(admin.getByTestId("user-status")).toHaveText("نشط");
  expect((await signIn(target.email)).status).toBe(200);
  await expect
    .poll(async () => (await audited("account.unsuspended")).length, { timeout: 30_000 })
    .toBeGreaterThan(0);
  await carolApi.dispose();
});

test("the users console reads in English and refuses members without the capability", async ({ browser }) => {
  const { b, c } = await sharedAccounts();
  promote(c.email);
  const english = await pageAs(browser, c);
  await english.addInitScript(() => localStorage.setItem("tara.locale", "en"));
  await english.goto(`/admin/users?q=${encodeURIComponent(b.email)}&field=email`);
  await expect(english.getByRole("heading", { name: "Users" })).toBeVisible();
  await expect(english.getByTestId("user-results").locator(`tr[data-account="${b.id}"]`)).toBeVisible();

  const member = await pageAs(browser, b);
  await member.goto("/admin/users");
  await expect(member).toHaveURL(/\/home$/);
  const bobApi = await apiAs(b);
  expect((await bobApi.get(`${API}/admin/users/`, { params: { q: c.email } })).status()).toBe(403);
  expect((await bobApi.get(`${API}/admin/users/${c.id}/`)).status()).toBe(403);
  expect((await bobApi.post(`${API}/admin/users/${c.id}/reveal/`, { data: { reason: "curious" } })).status()).toBe(403);
  expect((await bobApi.post(`${API}/admin/users/${c.id}/suspend/`, { data: { reason: "nope nope" } })).status()).toBe(403);
});
