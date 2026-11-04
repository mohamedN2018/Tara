import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { API, apiAs, befriend, pageAs, sharedAccounts, unique, useLocale } from "./helpers";

// Plan 08, track 2B: hide a post from Home (X, reason, Undo, snooze), with the
// feed service's hide endpoints (2A) behind it.

const LABELS = {
  ar: { hide: "إخفاء المنشور", hidden: "تم إخفاء المنشور", spam: "احتيال أو رسائل مزعجة", undo: "تراجع", latest: "الأحدث" },
  en: { hide: "Hide post", hidden: "Post hidden", spam: "Spam or scam", undo: "Undo", latest: "Latest" },
} as const;

async function seriousViolations(page: Page, selector: string) {
  const result = await new AxeBuilder({ page }).include(selector).withTags(["wcag2a", "wcag2aa"]).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes[0]?.target}`);
}

/** The ids of the Home list's items, in order. */
const feedOrder = (page: Page) =>
  page.locator("[data-feed-item]").evaluateAll((nodes) => nodes.map((n) => (n as HTMLElement).dataset.feedItem));

for (const lang of ["ar", "en"] as const) {
  test(`hide a post with a reason, undo, hide again, and it stays hidden after a reload (${lang})`, async ({ browser }) => {
    test.setTimeout(120_000);
    const { a, b } = await sharedAccounts();
    await befriend(a, b);
    const marker = `hide-${lang}-${unique()}`;
    const author = await apiAs(b);
    const created = await author.post(`${API}/posts/`, { data: { body: `منشور ${marker}`, audience: "public", type: "text" } });
    expect(created.ok()).toBe(true);
    const postId = (await created.json()).data.id as string;
    await author.dispose();

    const l = LABELS[lang];
    const page = await pageAs(browser, a);
    await useLocale(page, lang);
    const card = page.locator("article").filter({ hasText: marker });
    // Fan-out to the reader's feed is asynchronous.
    await expect
      .poll(
        async () => {
          await page.goto("/home");
          await page.locator("[data-feed-item]").first().waitFor();
          return card.count();
        },
        { timeout: 60_000 },
      )
      .toBe(1);
    await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
    // The server applies modes (2A), so the switcher shows, on Latest by default.
    await expect(page.getByTestId("feed-modes").getByRole("button", { name: l.latest })).toHaveAttribute("aria-pressed", "true");

    const before = await feedOrder(page);
    const hide = page.waitForResponse((r) => r.url().endsWith("/feed/hide/") && r.request().method() === "POST");
    await card.getByRole("button", { name: l.hide }).click();
    expect((await hide).status()).toBe(201);

    const feedback = page.locator(`[data-testid="hide-feedback"][data-post-id="${postId}"]`);
    await expect(feedback).toBeVisible();
    await expect(feedback.getByRole("heading", { name: l.hidden })).toBeVisible();
    await expect(card).toBeHidden();
    // Same slot in the list.
    expect(await feedOrder(page)).toEqual(before);
    expect(await seriousViolations(page, '[data-testid="hide-feedback"]')).toEqual([]);

    // Undo's arrow points back in the reading direction.
    const transform = await feedback.getByTestId("undo-icon").evaluate((el) => getComputedStyle(el).transform);
    if (lang === "ar") expect(transform).toBe("matrix(-1, 0, 0, 1, 0, 0)");
    else expect(transform).toBe("none");

    const reason = page.waitForResponse((r) => r.url().endsWith("/feed/hide/") && r.request().method() === "POST");
    await feedback.getByRole("button", { name: l.spam }).click();
    const reasonRes = await reason;
    expect(reasonRes.status()).toBe(201);
    expect(reasonRes.request().postDataJSON()).toEqual({ post_id: postId, reason: "spam" });
    await expect(feedback.getByRole("button", { name: l.spam })).toHaveAttribute("aria-pressed", "true");

    const undo = page.waitForResponse((r) => r.url().endsWith(`/feed/hide/${postId}/`) && r.request().method() === "DELETE");
    await feedback.getByRole("button", { name: l.undo, exact: true }).first().click();
    expect((await undo).status()).toBe(204);
    await expect(card).toBeVisible();
    await expect(feedback).toHaveCount(0);
    expect(await feedOrder(page)).toEqual(before);

    // Undo really undid it on the server: the post comes back after a reload.
    await page.reload();
    await expect(card).toBeVisible();

    // Hide again, then reload: it stays hidden.
    const again = page.waitForResponse((r) => r.url().endsWith("/feed/hide/") && r.request().method() === "POST");
    await card.getByRole("button", { name: l.hide }).click();
    expect((await again).status()).toBe(201);
    await expect(feedback).toBeVisible();
    await page.reload();
    await page.locator("[data-feed-item]").first().waitFor();
    await expect(card).toHaveCount(0);
    await expect(feedback).toHaveCount(0);
    expect(await seriousViolations(page, "main")).toEqual([]);

    const reader = await apiAs(a);
    await reader.delete(`${API}/feed/hide/${postId}/`);
    await reader.dispose();
    await page.context().close();
  });
}

test("the comment box's emoji picker inserts at the cursor", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const marker = `emoji-${unique()}`;
  const api = await apiAs(a);
  const created = await api.post(`${API}/posts/`, { data: { body: marker, audience: "public", type: "text" } });
  const postId = (await created.json()).data.id as string;
  await api.dispose();

  const page = await pageAs(browser, a);
  await page.goto(`/posts/${postId}`);
  const box = page.locator("article").getByRole("textbox", { name: "اكتب تعليقًا…" });
  await box.fill("مرحبا بكم");
  await box.evaluate((el: HTMLInputElement) => el.setSelectionRange(5, 5));
  await page.locator("article").getByRole("button", { name: "إدراج رمز تعبيري" }).click();
  await page.getByTestId("emoji-picker").getByRole("button", { name: "🔥" }).click();
  await expect(box).toHaveValue("مرحبا🔥 بكم");
  await page.context().close();
});
