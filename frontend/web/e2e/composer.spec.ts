import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { API, apiAs, befriend, expectNoUuid, pageAs, sharedAccounts, unique, useLocale } from "./helpers";

// Wave 2C: one composer dialog (audience, text, photos, tags, feeling, location,
// schedule, drafts), drafts and scheduled posts, people tags and their
// notification. Arabic (RTL) is the default locale.

async function seriousViolations(page: Page, selector: string) {
  const result = await new AxeBuilder({ page }).include(selector).withTags(["wcag2a", "wcag2aa"]).analyze();
  return result.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes[0]?.target}`);
}

const pad = (n: number) => String(n).padStart(2, "0");
/** A `datetime-local` value in the browser's own time zone. */
async function localInput(page: Page, msAhead: number): Promise<string> {
  const parts = await page.evaluate((ahead) => {
    const d = new Date(Date.now() + ahead);
    return [d.getFullYear(), d.getMonth() + 1, d.getDate(), d.getHours(), d.getMinutes()];
  }, msAhead);
  const [y, mo, d, h, mi] = parts;
  return `${y}-${pad(mo)}-${pad(d)}T${pad(h)}:${pad(mi)}`;
}

test("a scheduled post stays hidden, then appears in the feed once its time comes", async ({ browser }) => {
  test.setTimeout(240_000);
  const { a, b } = await sharedAccounts();
  await befriend(a, b);
  const page = await pageAs(browser, a);
  await page.goto("/home");
  const text = `مجدول ${unique()}`;

  await page.getByRole("button", { name: "بماذا تفكر؟" }).click();
  // The dialog's name follows its view (its heading), so it is found by role alone.
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "إنشاء منشور" })).toBeVisible();
  await dialog.getByRole("textbox", { name: "بماذا تفكر؟" }).fill(text);
  await dialog.getByRole("button", { name: "جدولة", exact: true }).click();
  // About 70 s ahead, rounded up to the next minute by the picker (no seconds).
  await dialog.getByLabel("موعد النشر").fill(await localInput(page, 70_000 + 60_000));
  await expect(dialog.getByText(/المنطقة الزمنية/)).toBeVisible();
  await dialog.getByTestId("composer-schedule-done").click();
  await expect(dialog.getByTestId("composer-schedule-summary")).toBeVisible();
  const created = page.waitForResponse((r) => r.url().endsWith("/posts/") && r.request().method() === "POST");
  await dialog.getByRole("button", { name: "جدولة المنشور" }).click();
  const { data: post } = await (await created).json();
  expect(post.state).toBe("scheduled");
  await expect(dialog).toBeHidden();
  await expect(page.locator("article", { hasText: text })).toHaveCount(0);

  // Hidden from everyone else until then, and listed in the author's drafts & scheduled.
  const friend = await apiAs(b);
  expect((await friend.get(`${API}/posts/${post.id}/`)).status()).toBe(404);
  await page.getByRole("button", { name: "بماذا تفكر؟" }).click();
  await dialog.getByTestId("composer-drafts").click();
  await expect(dialog.getByTestId("composer-drafts-list").locator(`[data-draft-id="${post.id}"]`)).toContainText("مجدول");
  await dialog.getByRole("button", { name: "إغلاق" }).click();

  // The beat task runs every minute: the post goes out, and fans out to the friend's feed.
  const reader = await pageAs(browser, b);
  await expect
    .poll(
      async () => {
        await reader.goto("/home");
        await reader.locator("article").first().waitFor({ timeout: 10_000 }).catch(() => {});
        return reader.locator("article", { hasText: text }).count();
      },
      { timeout: 200_000, intervals: [10_000] },
    )
    .toBe(1);
  expect((await friend.get(`${API}/posts/${post.id}/`)).status()).toBe(200);
  await expectNoUuid(reader);
});

test("save a draft, then publish it from Drafts & scheduled", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  await page.goto("/home");
  const text = `مسودة ${unique()}`;

  await page.getByRole("button", { name: "بماذا تفكر؟" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox", { name: "بماذا تفكر؟" }).fill(text);
  await dialog.getByRole("button", { name: "شعور أو نشاط" }).click();
  await dialog.getByRole("button", { name: /يشعر بالامتنان/ }).click();
  await dialog.getByRole("button", { name: "المكان" }).click();
  await dialog.getByRole("textbox", { name: "المكان" }).fill("الإسكندرية");
  await dialog.getByRole("button", { name: "حفظ كمسودة" }).click();
  await expect(page.getByText("تم الحفظ في مسوداتك.")).toBeVisible();
  await expect(page.locator("article", { hasText: text })).toHaveCount(0);

  await page.getByRole("button", { name: "بماذا تفكر؟" }).click();
  await dialog.getByRole("button", { name: "المسودات والمجدولة" }).click();
  const row = dialog.getByTestId("composer-drafts-list").locator("li", { hasText: text });
  await expect(row).toContainText("مسودة");
  await row.getByRole("button", { name: "تعديل" }).click();
  await expect(dialog.getByRole("heading", { name: "تعديل المسودة" })).toBeVisible();
  await expect(dialog.getByRole("textbox", { name: "بماذا تفكر؟" })).toHaveValue(text);
  await dialog.getByRole("button", { name: "نشر", exact: true }).click();

  const post = page.locator("article", { hasText: text });
  await expect(post).toBeVisible();
  await expect(post.getByTestId("post-composer-meta")).toContainText("يشعر بالامتنان");
  await expect(post.getByTestId("post-composer-meta")).toContainText("في الإسكندرية");
  await expectNoUuid(page);
});

test("tag a friend: the friend is notified, and 'nobody' refuses the tag", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  await befriend(a, b);
  const bob = await apiAs(b);
  await bob.patch(`${API}/posts/settings/`, { data: { who_can_tag: "friends" } });

  const page = await pageAs(browser, a);
  await page.goto("/home");
  const text = `إشارة ${unique()}`;
  await page.getByRole("button", { name: "بماذا تفكر؟" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox", { name: "بماذا تفكر؟" }).fill(text);
  await dialog.getByRole("button", { name: "الإشارة إلى أشخاص" }).click();
  await dialog.getByRole("searchbox", { name: "ابحث عن صديق" }).fill(b.name.split(" ")[0]);
  await dialog.getByTestId("composer-friends").locator("label", { hasText: b.name }).getByRole("checkbox").check();
  await dialog.getByRole("button", { name: "تم" }).click();
  await expect(dialog.getByTestId("composer-summary")).toContainText(`مع ${b.name}`);
  await dialog.getByRole("button", { name: "نشر", exact: true }).click();

  const post = page.locator("article", { hasText: text });
  await expect(post.getByTestId("post-composer-meta")).toContainText(b.name);

  await expect
    .poll(async () => {
      const list = await (await bob.get(`${API}/notifications/`)).json();
      return list.data.some((n: { kind: string; actor_id: string }) => n.kind === "post.tag" && n.actor_id === a.id);
    }, { timeout: 30_000 })
    .toBe(true);
  const friend = await pageAs(browser, b);
  await friend.goto("/notifications");
  await expect(friend.getByText(`أشار إليك ${a.name} في منشور`).first()).toBeVisible();

  // "Who can tag me" in Settings, then the composer explains the refusal.
  await friend.goto("/settings/privacy");
  const setting = friend.getByTestId("tag-privacy");
  await setting.getByText("لا أحد").click();
  await expect(friend.getByText("تم الحفظ.")).toBeVisible();
  const alice = await apiAs(a);
  const refused = await alice.post(`${API}/posts/`, { data: { body: "x", tagged_ids: [b.id] } });
  expect(refused.status()).toBe(400);
  expect((await refused.json()).error.code).toBe("tag_not_allowed");
  await bob.patch(`${API}/posts/settings/`, { data: { who_can_tag: "friends" } });
  await expectNoUuid(friend);
});

for (const lang of ["ar", "en"] as const) {
  test(`the composer in ${lang}: direction, labels and axe`, async ({ browser }) => {
    const { a } = await sharedAccounts();
    const page = await pageAs(browser, a);
    if (lang === "en") await useLocale(page, "en");
    await page.goto("/home");
    await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
    const L =
      lang === "ar"
        ? { open: "بماذا تفكر؟", title: "إنشاء منشور", tag: "الإشارة إلى أشخاص", feeling: "شعور أو نشاط", schedule: "جدولة", back: "رجوع" }
        : { open: "What's on your mind?", title: "Create post", tag: "Tag people", feeling: "Feeling/activity", schedule: "Schedule", back: "Back" };
    await page.getByRole("button", { name: L.open }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: L.title })).toBeVisible();
    expect(await seriousViolations(page, "[data-testid=composer-dialog]")).toEqual([]);

    // The back arrow sits on the start side: right in Arabic, left in English.
    await dialog.getByRole("button", { name: L.feeling }).click();
    const back = dialog.getByRole("button", { name: L.back });
    const box = (await back.boundingBox())!;
    const panel = (await dialog.boundingBox())!;
    const onRight = box.x + box.width / 2 > panel.x + panel.width / 2;
    expect(onRight).toBe(lang === "ar");
    expect(await seriousViolations(page, "[data-testid=composer-dialog]")).toEqual([]);
    await back.click();

    await dialog.getByRole("button", { name: L.tag }).click();
    expect(await seriousViolations(page, "[data-testid=composer-dialog]")).toEqual([]);
    await page.keyboard.press("Escape");
    await dialog.getByRole("button", { name: L.schedule, exact: true }).click();
    expect(await seriousViolations(page, "[data-testid=composer-dialog]")).toEqual([]);
    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();

    // "Create > Post" in the main menu opens the same dialog.
    await page.getByTestId("main-menu-button").click();
    await page.getByTestId("menu-create-post").click();
    await expect(page.getByRole("dialog").getByRole("heading", { name: L.title })).toBeVisible();
  });
}
