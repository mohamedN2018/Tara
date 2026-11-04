import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { API, apiAs, befriend, dmWith, pageAs, sharedAccounts, unique, useLocale } from "./helpers";

// Fix B: Unfollow in the Friends menu, Block in the post "..." menu, one active
// left-rail entry, the profile "More" tab on phones and bidi-safe handles.
// Shared accounts: anything changed is put back.

async function axe(page: Page, selector: string): Promise<string[]> {
  // Let fades and colour transitions settle: mid-transition colours read as contrast failures
  // (finite animations only: a loading pulse never finishes).
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getComputedTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => null)),
    ),
  );
  await page.waitForTimeout(250);
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).include(selector).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

for (const lang of ["ar", "en"] as const) {
  test(`people actions and rail state (${lang})`, async ({ browser }) => {
    test.setTimeout(180_000);
    const { a, b } = await sharedAccounts();
    await befriend(a, b);
    // Friends follow each other by default; make sure b follows a before the test.
    await (await apiAs(b)).post(`${API}/follows/${a.id}/`);

    const page = await pageAs(browser, b);
    await useLocale(page, lang);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/home");

    // One active rail entry: Home on /home, Feeds once a mode is chosen.
    await expect(page.getByTestId("sidebar-home")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("sidebar-feeds")).not.toHaveAttribute("aria-current", "page");
    await page.getByTestId("sidebar-feeds").click();
    await expect(page).toHaveURL(/mode=for_you/);
    await expect(page.getByTestId("sidebar-feeds")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("sidebar-home")).not.toHaveAttribute("aria-current", "page");

    // Block from a post menu asks first; cancelling leaves everything as it was.
    // A post by a (never the viewer's own, which has no Block), deleted after.
    const aApi = await apiAs(a);
    const created = await aApi.post(`${API}/posts/`, {
      data: { body: `fixb block ${unique()}`, audience: "public", type: "text" },
    });
    expect(created.ok()).toBe(true);
    const postId = ((await created.json()) as { data: { id: string } }).data.id;
    try {
      await page.goto(`/posts/${postId}`);
      const card = page.locator(`article[data-post-id="${postId}"]`);
      const postMenu = card.getByTestId("post-menu");
      await expect(postMenu).toBeVisible();
      await postMenu.click();
      // The people items wait for their lists, so wait for them too.
      await expect(page.getByTestId("menu-favorite")).toBeVisible();
      await expect(page.getByTestId("menu-mute")).toBeVisible();
      const block = page.getByTestId("menu-block");
      await expect(block).toBeVisible();
      await block.click();
      const confirm = page.getByTestId("confirm-action");
      await expect(confirm).toBeVisible();
      expect(await axe(page, "[data-testid=confirm-action]")).toEqual([]);
      await page.keyboard.press("Escape");
      await expect(confirm).toBeHidden();
      // Cancelled: still not blocked.
      const blocks = (await (await (await apiAs(b)).get(`${API}/blocks/`)).json()) as { data: { blocked: string[] } };
      expect(blocks.data.blocked).not.toContain(a.id);
    } finally {
      await aApi.delete(`${API}/posts/${postId}/`);
    }

    // The DM header's Block asks in the same dialog (not the browser's confirm).
    const nativeDialogs: string[] = [];
    page.on("dialog", (d) => {
      nativeDialogs.push(d.message());
      void d.dismiss();
    });
    const conv = await dmWith(await apiAs(b), a.id);
    await page.goto(`/messages/${conv}`);
    await page.getByTestId("conversation-menu").click();
    await page.getByTestId("conversation-block").click();
    const dmConfirm = page.getByTestId("confirm-action");
    await expect(dmConfirm).toBeVisible();
    expect(await axe(page, "[data-testid=confirm-action]")).toEqual([]);
    await dmConfirm.getByRole("button", { name: lang === "ar" ? "إلغاء" : "Cancel" }).click();
    await expect(dmConfirm).toBeHidden();
    await expect(page).toHaveURL(new RegExp(`/messages/${conv}$`));
    expect(nativeDialogs).toEqual([]);
    {
      const res = (await (await (await apiAs(b)).get(`${API}/blocks/`)).json()) as { data: { blocked: string[] } };
      expect(res.data.blocked).not.toContain(a.id);
    }

    // Friend's profile: the Friends menu holds Unfollow (and Follow to undo it).
    await page.goto(`/u/id/${a.id}`);
    await expect(page.getByTestId("friend-button")).toHaveAttribute("data-state", "friends");
    await page.getByTestId("friend-button").locator("button").first().click();
    const follow = page.getByTestId("friend-menu-follow");
    await expect(follow).toBeVisible();
    expect(await axe(page, "[data-testid=profile-hero]")).toEqual([]);
    await follow.click();
    await page.getByTestId("friend-button").locator("button").first().click();
    await expect(page.getByTestId("friend-menu-follow")).toBeVisible();
    await page.getByTestId("friend-menu-follow").click(); // follow again
    await expect(page.getByTestId("friend-button")).toHaveAttribute("data-state", "friends");

    // The handle sits under the name, in the same alignment.
    const name = await page.locator("[data-testid=profile-hero] h1").boundingBox();
    const handle = await page.getByTestId("hero-handle").locator("bdi").boundingBox();
    expect(name && handle).toBeTruthy();
    if (lang === "ar") expect(Math.abs(name!.x + name!.width - (handle!.x + handle!.width))).toBeLessThan(24);
    else expect(Math.abs(name!.x - handle!.x)).toBeLessThan(24);

    // Phones: Photos folds into "More".
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByTestId("profile-tab-photos")).toBeHidden();
    await page.getByTestId("profile-tab-more").click();
    await page.getByTestId("profile-tab-more-photos").click();
    await expect(page).toHaveURL(/tab=photos/);
    await expect(page.getByTestId("profile-tab-more")).toContainText(lang === "ar" ? "الصور" : "Photos");
    await page.context().close();
  });
}
