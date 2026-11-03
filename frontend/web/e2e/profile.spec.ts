import { expect, test } from "@playwright/test";

import { API, apiAs, expectNoUuid, pageAs, sharedAccounts, unique } from "./helpers";

test("another user's profile loads by account id with their name and posts", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const marker = unique();
  const author = await apiAs(a);
  await author.post(`${API}/posts/`, { data: { body: `visible ${marker}`, audience: "public", type: "text" } });
  await author.dispose();

  const page = await pageAs(browser, b);
  const loaded = page.waitForResponse(`**/users/id/${a.id}/`);
  await page.goto(`/u/id/${a.id}`);
  expect((await loaded).ok()).toBe(true);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText(a.name);
  await expect(page.getByText(`@${a.handle}`)).toBeVisible();
  await expect(page.locator("article").filter({ hasText: marker })).toBeVisible();
  await expect(page.getByRole("button", { name: "مراسلة" })).toBeVisible();
  await expectNoUuid(page);
});

test("the ?name= and ?rel= URL params are not trusted", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const page = await pageAs(browser, b);
  await page.goto(`/u/id/${a.id}?name=Spoofed%20Admin&rel=friends`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(a.name);
  await expect(page.getByText("Spoofed Admin")).toHaveCount(0);
  await page.waitForTimeout(800);
  const directory = await page.evaluate(() => localStorage.getItem("tara.directory.v2"));
  expect(directory ?? "").not.toContain("Spoofed");
});

test("the timeline keeps paging past pages that filtering left empty", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const page = await pageAs(browser, b);
  const urls: string[] = [];
  await page.route("**/api/v1/posts/?*", async (route) => {
    const url = new URL(route.request().url());
    urls.push(url.search);
    if (urls.length === 1) {
      return route.fulfill({
        json: { data: [], page: { next_cursor: "skipped", prev_cursor: null, has_more: true } },
      });
    }
    url.searchParams.delete("cursor");
    return route.continue({ url: url.toString() });
  });
  await page.goto(`/u/id/${a.id}`);
  await expect(page.locator("article").first()).toBeVisible();
  expect(urls[1]).toContain("cursor=skipped");
});

test("an unknown profile shows an error, not an empty shell", async ({ browser }) => {
  const { b } = await sharedAccounts();
  const page = await pageAs(browser, b);
  await page.goto("/u/id/01a19ed4-0000-7000-8000-000000000000");
  await expect(page.getByText("لم يعد هذا العنصر موجودًا.")).toBeVisible();
  await expect(page.getByRole("button", { name: "إعادة المحاولة" })).toBeVisible();
});

test("notification preferences save the nested shape and persist", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  await page.goto("/settings");
  const box = page.getByRole("checkbox", { name: "المتابعون الجدد" });
  await expect(box).toBeVisible();
  const wasChecked = await box.isChecked();

  const saved = page.waitForRequest(
    (r) => r.url().includes("/notifications/preferences/") && r.method() === "PATCH",
  );
  await box.setChecked(!wasChecked);
  expect((await saved).postDataJSON().prefs.follow).toEqual({ in_app: !wasChecked });

  await page.waitForResponse((r) => r.url().includes("/notifications/preferences/"));
  await page.reload();
  await expect(page.getByRole("checkbox", { name: "المتابعون الجدد" })).toBeChecked({
    checked: !wasChecked,
  });
});

test("my own profile: tabs, editing, and the sections work after the split", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  await page.goto(`/u/${a.handle}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(a.name);

  await page.getByRole("button", { name: "الصور", exact: true }).click();
  await expect(page.getByRole("heading", { name: "الصور" })).toBeVisible();
  await page.getByRole("button", { name: "الأصدقاء", exact: true }).click();
  await expect(page.getByRole("heading", { name: "الأصدقاء" }).first()).toBeVisible();
  await page.getByRole("button", { name: "المنشورات", exact: true }).click();

  const intro = `مرحبا ${unique()}`;
  await page.getByRole("button", { name: "تعديل الملف" }).first().click();
  const dialog = page.getByRole("dialog", { name: "تعديل الملف الشخصي" });
  await dialog.getByLabel("تعريف").fill(intro);
  await dialog.getByRole("button", { name: "حفظ", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText(intro).first()).toBeVisible();
});

test("search results show the profile's name, and link without a name param", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const page = await pageAs(browser, b);
  await page.route("**/api/v1/search/?*", (route) =>
    route.fulfill({
      json: {
        data: {
          results: [{ type: "user", id: a.id, title: `${a.handle} ${a.name}`, snippet: "", owner_id: a.id }],
        },
      },
    }),
  );
  await page.goto(`/search?q=${a.handle}`);
  const link = page.getByRole("main").getByRole("link", { name: a.name });
  await expect(link).toHaveAttribute("href", `/u/id/${a.id}`);
  await expectNoUuid(page);

  await page.route("**/api/v1/search/?*", (route) => route.fulfill({ status: 503, body: "down" }));
  await page.reload();
  await expect(page.getByRole("button", { name: "إعادة المحاولة" })).toBeVisible();
});
