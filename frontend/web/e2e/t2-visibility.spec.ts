import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { befriend, pageAs, sharedAccounts, useLocale } from "./helpers";

// Track T2: profile header actions, About tab, people "..." menu, Friends hub
// sections, Connections lists and the privacy center are reached by clicking
// through navigation (never a typed URL) in Arabic and English, and pass axe.
// Every preference this test changes is changed back (shared accounts).

const DESKTOP = { width: 1440, height: 900 };

async function axe(page: Page, selector: string): Promise<string[]> {
  // Let fades and colour transitions settle: mid-transition colours read as contrast failures.
  await page.evaluate(() => Promise.all(document.getAnimations().map((a) => a.finished.catch(() => null))));
  await page.waitForTimeout(250);
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).include(selector).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

for (const lang of ["ar", "en"] as const) {
  test(`profile, friends, connections and privacy from navigation (${lang})`, async ({ browser }) => {
    test.setTimeout(180_000);
    const { a, b } = await sharedAccounts();
    await befriend(a, b);

    const page = await pageAs(browser, a);
    await useLocale(page, lang);
    await page.setViewportSize(DESKTOP);
    await page.goto("/home");
    await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");

    // 1. Own profile from the sidebar: photo controls, tabs row, About tab.
    await page.getByTestId("sidebar-profile").click();
    await expect(page.getByTestId("profile-hero")).toBeVisible();
    await expect(page.getByTestId("edit-cover")).toBeVisible();
    await page.getByTestId("edit-avatar").click();
    await expect(page.getByRole("menu")).toBeVisible();
    await page.keyboard.press("Escape");
    for (const tb of ["posts", "about", "friends", "photos"]) await expect(page.getByTestId(`profile-tab-${tb}`)).toBeVisible();
    await page.getByTestId("profile-tab-about").click();
    await expect(page).toHaveURL(/tab=about/);
    expect(await axe(page, "[data-testid=profile-hero]")).toEqual([]);

    // 2. Privacy center from the profile "..." menu.
    await page.getByTestId("person-actions").click();
    await page.getByTestId("person-actions-menu").getByRole("menuitem").last().click();
    await expect(page).toHaveURL(/\/settings\/privacy$/);
    await expect(page.getByTestId("privacy-profile")).toBeVisible();
    await expect(page.getByTestId("privacy-connections")).toBeVisible();
    await expect(page.getByTestId("privacy-friends_list_visibility")).toBeVisible();
    expect(await axe(page, "main")).toEqual([]);

    // 3. Friends hub from the main menu: sections are deep-linked tabs.
    await page.getByTestId("main-menu-button").click();
    await page.getByTestId("menu-item-friends").click();
    await expect(page).toHaveURL(/\/friends/);
    await page.getByTestId("friends-tab-suggestions").click();
    await expect(page).toHaveURL(/tab=suggestions/);
    await page.getByTestId("friends-tab-all").click();
    await expect(page).toHaveURL(/tab=all/);
    const card = page.locator(`[data-testid=friend-card][data-account-id="${b.id}"]`);
    await expect(card).toBeVisible();
    expect(await axe(page, "main")).toEqual([]);

    // 4. Friend card -> their profile -> "..." menu: mute (then undo), report dialog.
    await card.getByRole("link").last().click();
    await expect(page.getByTestId("profile-hero")).toBeVisible();
    await expect(page.getByTestId("friend-button")).toHaveAttribute("data-state", "friends");
    await page.getByTestId("person-actions").click();
    const menu = page.getByTestId("person-actions-menu");
    await expect(menu.getByRole("menuitem")).toHaveCount(7); // copy link, favorites, mute, restrict, unfriend, block, report
    await menu.getByRole("menuitem").nth(2).click(); // mute
    await page.getByTestId("person-actions").click();
    await menu.getByRole("menuitem").last().click(); // report
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    expect(await axe(page, "[role=dialog]")).toEqual([]);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();

    // 5. Followers list from the header count.
    await page.getByTestId("hero-followers").click();
    await expect(page).toHaveURL(/tab=friends/);

    // 6. Connections -> Muted shows them; unmute restores the shared account.
    await page.getByTestId("main-menu-button").click();
    await page.getByTestId("menu-item-connections").click();
    await page.getByTestId("connections-tab-muted").click();
    await expect(page).toHaveURL(/tab=muted/);
    const muted = page.getByTestId("connections-list-muted");
    await expect(muted).toBeVisible();
    const row = muted.locator("li").filter({ has: page.locator(`a[href$="${b.id}"]`) });
    await expect(row).toHaveCount(1);
    await row.getByRole("button").click();
    await expect(row).toHaveCount(0);
    expect(await axe(page, "main")).toEqual([]);
    await page.context().close();
  });
}
