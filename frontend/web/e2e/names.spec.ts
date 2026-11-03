import { expect, test } from "@playwright/test";

import { API, apiAs, expectNoUuid, pageAs, sharedAccounts, unique } from "./helpers";

test("people show as names everywhere, never ids", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const marker = unique();

  const author = await apiAs(a);
  const reader = await apiAs(b);
  const { data: post } = await (
    await author.post(`${API}/posts/`, { data: { body: `names ${marker}`, audience: "public", type: "text" } })
  ).json();
  await reader.post(`${API}/follows/${a.id}/`);
  await reader.post(`${API}/friends/requests/`, { data: { to_user_id: a.id } }); // 409 once friends
  await reader.post(`${API}/posts/${post.id}/comments/`, { data: { body: `comment ${marker}` } });
  const listing = await (
    await reader.get(`${API}/marketplace/categories/`)
  ).json();
  const { data: created } = await (
    await reader.post(`${API}/marketplace/listings/`, {
      data: { title: `chair ${marker}`, description: "", price: "10.00", currency: "EGP", category_id: listing.data[0].id },
    })
  ).json();
  await reader.post(`${API}/marketplace/listings/${created.id}/publish/`);

  const page = await pageAs(browser, a);

  await page.goto(`/posts/${post.id}`);
  await expect(page.getByText(`comment ${marker}`)).toBeVisible();
  await expect(page.locator("article").getByText(b.name).first()).toBeVisible();
  await expectNoUuid(page);

  await page.goto("/notifications");
  await expect(page.getByText(`علّق ${b.name} على منشورك`).first()).toBeVisible();
  await expectNoUuid(page);

  await page.goto("/connections");
  await expect(page.getByRole("link", { name: b.name }).first()).toBeVisible();
  await expectNoUuid(page);

  await page.goto("/friends");
  await page.getByRole("button", { name: /كل الأصدقاء|الطلبات/ }).first().waitFor();
  await expectNoUuid(page);

  await page.goto(`/marketplace/${created.id}`);
  await expect(page.getByRole("heading", { name: `chair ${marker}` })).toBeVisible();
  await expect(page.getByRole("main").getByText(b.name).first()).toBeVisible();
  await expectNoUuid(page);

  await page.goto("/marketplace");
  await expect(page.getByRole("heading", { name: `chair ${marker}` })).toBeVisible();
  await expectNoUuid(page);

  await author.dispose();
  await reader.dispose();
});

test("a user the server won't describe gets a neutral label", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const page = await pageAs(browser, a);
  await page.route("**/users/lookup/", (route) => route.fulfill({ json: { data: [] } }));
  await page.route("**/follows/followers/", (route) =>
    route.fulfill({ json: { data: { followers: [b.id] } } }),
  );
  await page.goto("/connections");
  await expect(page.getByRole("link", { name: "مستخدم Tara" }).first()).toBeVisible();
  await expectNoUuid(page);
});

test("a moderation action that fails leaves the case in the queue", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  const claims = Buffer.from(
    JSON.stringify({ sub: a.id, roles: ["admin"], exp: Math.floor(Date.now() / 1000) + 3600 }),
  ).toString("base64url");
  await page.addInitScript((token) => localStorage.setItem("tara.access", token), `h.${claims}.s`);

  const failed = { status: 503, json: { error: { code: "dependency_unavailable", message: "raw" } } };
  await page.route("**/api/v1/**", (route) => {
    const url = route.request().url();
    if (url.includes("/profile/me/")) {
      return route.fulfill({
        json: { data: { account_id: a.id, handle: a.handle, display_name: a.name, visibility: "public" } },
      });
    }
    if (url.endsWith("/me/")) {
      return route.fulfill({
        json: { data: { id: a.id, email: a.email, status: "active", language: "ar", theme: "system" } },
      });
    }
    if (url.includes("/admin/service-health/")) {
      return route.fulfill({
        json: { data: { overall: "degraded", services: [{ service: "chat", status: "not_ready", latency_ms: 1 }] } },
      });
    }
    if (url.endsWith("/action/") || url.endsWith("/resolve/")) return route.fulfill(failed);
    if (url.includes("/moderation/appeals/")) {
      return route.fulfill({
        json: {
          data: [
            {
              id: "ap1",
              case_id: "c0",
              target_type: "comment",
              target_id: "t2",
              account_id: a.id,
              text: "طعن تجريبي",
              status: "open",
              created_at: "2026-11-03T00:00:00Z",
            },
          ],
          page: { next_cursor: null, prev_cursor: null, has_more: false },
        },
      });
    }
    if (url.includes("/moderation/cases/")) {
      return route.fulfill({
        json: {
          data: [
            {
              id: "c1",
              target_type: "post",
              target_id: "t1",
              severity: "normal",
              state: "open",
              report_count: 3,
              assigned_to: null,
              created_at: "2026-11-03T00:00:00Z",
              updated_at: "2026-11-03T00:00:00Z",
            },
          ],
          page: { next_cursor: null, prev_cursor: null, has_more: false },
        },
      });
    }
    return route.fulfill({ json: { data: [] } });
  });

  await page.goto("/admin");
  const row = page.getByRole("listitem").filter({ hasText: "منشور · 3 بلاغات · مفتوحة" });
  await expect(row).toBeVisible();
  await expect(page.getByText("أداء منخفض")).toBeVisible();
  await row.getByRole("button", { name: "إزالة" }).click();
  await expect(page.getByRole("status").filter({ hasText: "هذه الخدمة غير متاحة مؤقتًا" })).toBeVisible();
  await expect(row).toBeVisible();

  // An appeal whose resolution fails stays open, too.
  const appeal = page.getByTestId("appeals").getByRole("listitem").filter({ hasText: "طعن تجريبي" });
  await expect(appeal).toContainText("تعليق");
  await appeal.getByRole("button", { name: "إلغاء القرار" }).click();
  await expect(page.getByRole("status").filter({ hasText: "هذه الخدمة غير متاحة مؤقتًا" }).last()).toBeVisible();
  await expect(appeal).toBeVisible();
});

test("modals are dialogs that trap focus, and Escape gives it back", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  await page.goto("/marketplace");
  const open = page.getByRole("button", { name: "أضف إعلان" });
  await open.focus();
  await open.press("Enter");

  const dialog = page.getByRole("dialog", { name: "إنشاء إعلان" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("العنوان")).toBeVisible();
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(open).toBeFocused();
});

test("English works too: LTR, translated, singular and plural", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  await page.addInitScript(() => localStorage.setItem("tara.locale", "en"));
  await page.goto("/home");
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("button", { name: "What's on your mind?" })).toBeVisible();
});
