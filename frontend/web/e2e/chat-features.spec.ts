import { chromium, expect, type Page, test } from "@playwright/test";

import { API, apiAs, befriend, dmWith, expectNoUuid, pageAs, sharedAccounts, unique } from "./helpers";

const bubbleText = (page: Page, text: string) => page.getByTestId("message-scroller").getByText(text);

async function hoverTools(page: Page, text: string) {
  await bubbleText(page, text).hover();
}

test("message reactions appear live on the other side and can be removed", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const tag = unique();
  const api = await apiAs(a);
  const id = await dmWith(api, b.id);
  await api.post(`${API}/conversations/${id}/messages/`, { data: { body: `react ${tag}` } });

  const alice = await pageAs(browser, a);
  const bob = await pageAs(browser, b);
  await alice.goto(`/messages/${id}`);
  await bob.goto(`/messages/${id}`);
  await expect(bubbleText(bob, `react ${tag}`)).toBeVisible();
  await alice.waitForTimeout(800); // Let the socket connect.

  await hoverTools(bob, `react ${tag}`);
  await bob.getByRole("button", { name: "تفاعل" }).last().click();
  await bob.getByRole("button", { name: "أحببته" }).click();
  await expect(alice.getByTestId("message-reactions").last()).toContainText("❤️");

  await alice.reload();
  await expect(alice.getByTestId("message-reactions").last()).toContainText("❤️");
  await alice.waitForTimeout(800);

  await bob.getByTestId("message-reactions").last().getByRole("button").click();
  await expect(bob.getByTestId("message-reactions")).toHaveCount(0);
  await expect(alice.getByTestId("message-reactions")).toHaveCount(0);
});

test("pin and mute persist across a reload", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const tag = unique();
  const api = await apiAs(a);
  const id = await dmWith(api, b.id);
  await api.post(`${API}/conversations/${id}/messages/`, { data: { body: `pin ${tag}` } });

  const page = await pageAs(browser, a);
  await page.goto(`/messages/${id}`);
  await hoverTools(page, `pin ${tag}`);
  await page.getByRole("button", { name: "تثبيت", exact: true }).last().click();
  await expect(page.getByTestId("pinned-bar")).toContainText(`pin ${tag}`);

  await page.getByRole("button", { name: "كتم", exact: true }).click();
  await page.getByRole("menuitem", { name: "لمدة ساعة" }).click();
  await expect(page.getByRole("button", { name: "إلغاء الكتم" })).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("pinned-bar")).toContainText(`pin ${tag}`);
  await expect(page.getByRole("button", { name: "إلغاء الكتم" })).toBeVisible();

  await page.getByRole("button", { name: "إلغاء الكتم" }).click();
  await expect(page.getByRole("button", { name: "كتم", exact: true })).toBeVisible();
  await hoverTools(page, `pin ${tag}`);
  await page.getByTestId("message-scroller").getByRole("button", { name: "إلغاء التثبيت" }).last().click();
  await expect(page.getByTestId("pinned-bar")).toHaveCount(0);
});

test("a group is created from friends, chats, and manages members", async ({ browser }) => {
  const { a, b, c } = await sharedAccounts();
  await befriend(a, b);
  await befriend(a, c);
  const tag = unique();

  const alice = await pageAs(browser, a);
  await alice.goto("/messages");
  await alice.getByRole("button", { name: "مجموعة جديدة" }).click();
  await alice.getByLabel("اسم المجموعة").fill(`Team ${tag}`);
  await alice.getByRole("dialog").getByText(b.name).click();
  await alice.getByRole("button", { name: "إنشاء المجموعة" }).click();
  await expect(alice).toHaveURL(/\/messages\/[\w-]+$/);
  await expect(alice.getByTestId("conversation-title")).toHaveText(`Team ${tag}`);

  const bob = await pageAs(browser, b);
  await bob.goto(new URL(alice.url()).pathname);
  await expect(bob.getByTestId("conversation-title")).toHaveText(`Team ${tag}`);
  await bob.waitForTimeout(800);

  await alice.getByRole("textbox", { name: "اكتب رسالة…" }).fill(`hello ${tag}`);
  await alice.getByRole("button", { name: "إرسال" }).click();
  await expect(bubbleText(bob, `hello ${tag}`)).toBeVisible();

  // Add a third member from the group panel; Bob sees the count change live.
  await alice.getByRole("button", { name: "معلومات المجموعة" }).click();
  await alice.getByRole("button", { name: "إضافة أعضاء" }).click();
  await alice.getByRole("dialog").getByText(c.name).click();
  await alice.getByRole("button", { name: "إضافة", exact: true }).click();
  await expect(bob.locator("header").getByText("3")).toBeVisible();

  // A member has no admin controls; removing Bob kicks him out live.
  await bob.getByRole("button", { name: "معلومات المجموعة" }).click();
  await expect(bob.getByTestId("group-members")).toContainText(c.name);
  await expect(bob.getByRole("button", { name: "إزالة من المجموعة" })).toHaveCount(0);
  await bob.getByRole("dialog").getByRole("button", { name: "إغلاق" }).click();
  await expectNoUuid(bob);

  await alice.getByRole("button", { name: "معلومات المجموعة" }).click();
  await alice
    .getByTestId("group-members")
    .locator("li", { hasText: b.name })
    .getByRole("button", { name: "إزالة من المجموعة" })
    .click();
  await expect(bob).toHaveURL(/\/messages$/);
});

test("a recorded voice message uploads, sends and plays for the other member", async () => {
  const { a, b } = await sharedAccounts();
  const api = await apiAs(a);
  const id = await dmWith(api, b.id);

  // A fake microphone: this is the real MediaRecorder + upload path.
  const browser = await chromium.launch({
    executablePath: process.env.E2E_CHROMIUM_PATH || undefined,
    args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
  });
  try {
    const alice = await pageAs(browser, a);
    await alice.context().grantPermissions(["microphone"]);
    await alice.goto(`/messages/${id}`);
    await alice.getByRole("button", { name: "تسجيل رسالة صوتية" }).click();
    await expect(alice.getByText("جارٍ التسجيل…")).toBeVisible();
    await alice.waitForTimeout(1500);
    await alice.getByRole("button", { name: "إيقاف وإرسال" }).click();
    await expect(alice.getByTestId("voice-player").last()).toBeVisible();

    const bob = await pageAs(browser, b);
    await bob.goto(`/messages/${id}`);
    const player = bob.getByTestId("voice-player").last();
    await player.getByRole("button", { name: "تشغيل الرسالة الصوتية" }).click();
    await expect
      .poll(() => player.locator("audio").evaluate((el: HTMLAudioElement) => el.currentTime), { timeout: 10_000 })
      .toBeGreaterThan(0);
    await expect(player).not.toContainText("تعذّر");
  } finally {
    await browser.close();
  }
});
