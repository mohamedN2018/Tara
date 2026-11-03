import { execSync } from "node:child_process";

import { expect, test } from "@playwright/test";

import { API, apiAs, pageAs, sharedAccounts, unique } from "./helpers";

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
  await card.getByRole("button").click();

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
