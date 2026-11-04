import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { pageAs, sharedAccounts } from "./helpers";

// Wave 1A: the top bar's centre tabs (active underline, RTL order), the main
// menu (categories, permissions, Create column, search, keyboard), the
// profile menu, phone width and axe. Arabic (RTL) is the default locale.

async function seriousViolations(page: Page, selector: string) {
  const result = await new AxeBuilder({ page }).include(selector).withTags(["wcag2a", "wcag2aa"]).analyze();
  return result.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes[0]?.target}`);
}

const underline = (page: Page, tab: string) => page.getByTestId(`top-tab-${tab}`).getByTestId("top-tab-underline");

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test("the active tab is underlined after navigating, in Arabic, and the tabs run right to left", async ({ browser }) => {
  const { b } = await sharedAccounts();
  const page = await pageAs(browser, b);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/home");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");

  const tabs = page.getByRole("navigation", { name: "التنقّل الرئيسي" });
  for (const name of ["الرئيسية", "الأصدقاء", "السوق", "المجموعات", "الفعاليات"]) {
    await expect(tabs.getByRole("link", { name, exact: true })).toBeVisible();
  }
  await expect(tabs.getByRole("link")).toHaveCount(5);
  await expect(underline(page, "home")).toBeVisible();

  await tabs.getByRole("link", { name: "الأصدقاء", exact: true }).click();
  await expect(page).toHaveURL(/\/friends$/);
  await expect(underline(page, "friends")).toBeVisible();
  await expect(underline(page, "home")).toHaveCount(0);
  await expect(page.getByTestId("top-tab-friends")).toHaveAttribute("aria-current", "page");

  await tabs.getByRole("link", { name: "الفعاليات", exact: true }).click();
  await expect(page).toHaveURL(/\/events$/);
  await expect(underline(page, "events")).toBeVisible();
  await expect(underline(page, "friends")).toHaveCount(0);

  // RTL: Home is the first tab, so it sits to the right of Friends.
  const home = await page.getByTestId("top-tab-home").boundingBox();
  const friends = await page.getByTestId("top-tab-friends").boundingBox();
  expect(home!.x).toBeGreaterThan(friends!.x);

  // A tooltip names the tab on hover.
  await page.getByTestId("top-tab-marketplace").hover();
  await expect(page.getByTestId("top-tab-marketplace").getByTestId("top-tab-tooltip")).toHaveText("السوق");
  await expect(page.getByTestId("top-tab-marketplace").getByTestId("top-tab-tooltip")).toHaveCSS("opacity", "1");

  // The tabs stay on the bar at the large breakpoints too (they used to vanish from lg up).
  for (const width of [1024, 1280, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByTestId("top-tab-groups")).toBeVisible();
  }
});

test("the active tab is underlined after navigating, in English, left to right", async ({ browser }) => {
  const { b } = await sharedAccounts();
  const page = await pageAs(browser, b);
  await page.addInitScript(() => localStorage.setItem("tara.locale", "en"));
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/home");
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");

  const tabs = page.getByRole("navigation", { name: "Primary navigation" });
  await expect(underline(page, "home")).toBeVisible();
  await tabs.getByRole("link", { name: "Marketplace", exact: true }).click();
  await expect(page).toHaveURL(/\/marketplace/);
  await expect(underline(page, "marketplace")).toBeVisible();
  await expect(underline(page, "home")).toHaveCount(0);

  await tabs.getByRole("link", { name: "Groups", exact: true }).click();
  await expect(page).toHaveURL(/\/groups$/);
  await expect(underline(page, "groups")).toBeVisible();

  const home = await page.getByTestId("top-tab-home").boundingBox();
  const friends = await page.getByTestId("top-tab-friends").boundingBox();
  expect(home!.x).toBeLessThan(friends!.x);

  // The main menu reads in English too.
  await page.getByRole("button", { name: "Menu", exact: true }).click();
  const menu = page.getByTestId("main-menu");
  await expect(menu.getByRole("heading", { name: "Menu" })).toBeVisible();
  await expect(menu.getByRole("group", { name: "Your account" })).toBeVisible();
  await expect(menu.getByRole("menu", { name: "Create" }).getByRole("menuitem", { name: "Marketplace listing" })).toBeVisible();
});

test("a plain member sees the built services by category, no admin item and no unbuilt module", async ({ browser }) => {
  const { b } = await sharedAccounts();
  const page = await pageAs(browser, b);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/home");

  await page.getByRole("button", { name: "القائمة", exact: true }).click();
  const menu = page.getByTestId("main-menu");
  await expect(menu).toBeVisible();
  await expect(page.getByTestId("main-menu-search")).toBeFocused();

  for (const section of ["حسابك", "اجتماعي", "تجاري", "التواصل", "إدارة الصفحات والمجموعات", "النظام"]) {
    await expect(menu.getByRole("group", { name: section })).toBeVisible();
  }
  // Nothing is built for these two categories yet, so they are not shown at all.
  await expect(menu.getByRole("group", { name: "صانع المحتوى" })).toHaveCount(0);
  await expect(menu.getByRole("group", { name: "احترافي" })).toHaveCount(0);

  // No staff entries for a member without capabilities.
  await expect(menu.getByRole("menuitem", { name: "الإدارة" })).toHaveCount(0);
  await expect(menu.getByRole("menuitem", { name: "مراجعة الإعلانات" })).toHaveCount(0);
  await expect(page.getByTestId("menu-item-admin")).toHaveCount(0);
  // Unbuilt modules are hidden, never shown disabled.
  for (const name of ["الذكريات", "الريلز", "البث المباشر", "مركز المساعدة", "طلبات الرسائل"]) {
    await expect(menu.getByRole("menuitem", { name })).toHaveCount(0);
  }
  await expect(menu.locator('[aria-disabled="true"], [disabled]')).toHaveCount(0);

  // The Create column offers only flows that exist.
  const create = menu.getByRole("menu", { name: "إنشاء" });
  await expect(create.getByRole("menuitem")).toHaveText(["منشور", "صفحة", "مجموعة", "فعالية", "منتج في السوق"]);

  // Search in the menu narrows it (Arabic spelling variants fold together).
  await page.getByTestId("main-menu-search").fill("الاعدادات");
  await expect(menu.getByRole("menuitem")).toHaveCount(1);
  await expect(menu.getByRole("menuitem", { name: "الإعدادات" })).toBeVisible();
  await page.getByTestId("main-menu-search").fill("zzzz");
  await expect(menu.getByRole("status")).toBeVisible();
  await page.getByTestId("main-menu-search").fill("");

  // An entry navigates and closes the menu.
  await menu.getByRole("menuitem", { name: "المحفوظات" }).click();
  await expect(page).toHaveURL(/\/saved$/);
  await expect(menu).toHaveCount(0);

  // Create > Page opens the page form where pages are made.
  await page.getByRole("button", { name: "القائمة", exact: true }).click();
  await page.getByTestId("menu-create-page").click();
  await expect(page).toHaveURL(/\/pages$/);
  await expect(page.getByRole("dialog", { name: "إنشاء صفحة" })).toBeVisible();
});

test("arrow keys move through the main menu and the profile menu, Escape returns focus", async ({ browser }) => {
  const { b } = await sharedAccounts();
  const page = await pageAs(browser, b);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/home");

  const trigger = page.getByRole("button", { name: "القائمة", exact: true });
  await trigger.click();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("main-menu-search")).toBeFocused();

  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("menu-item-profile")).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("menu-item-friends")).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("menu-item-profile")).toBeFocused();
  await page.keyboard.press("ArrowUp"); // wraps to the last entry: the Create column's last flow
  await expect(page.getByTestId("menu-create-listing")).toBeFocused();
  await page.keyboard.press("Home");
  await expect(page.getByTestId("menu-item-profile")).toBeFocused();
  // Only the focused entry is in the Tab order.
  await expect(page.getByTestId("main-menu").locator('[role="menuitem"][tabindex="0"]')).toHaveCount(1);

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("main-menu")).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await expect(trigger).toHaveAttribute("aria-expanded", "false");

  // ArrowDown on the closed trigger opens it too.
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("main-menu")).toBeVisible();
  await page.keyboard.press("Escape");

  // Profile menu: see profile, settings & privacy, display & accessibility, log out.
  const profile = page.getByRole("button", { name: "الملف الشخصي" });
  await profile.click();
  const menu = page.getByRole("menu", { name: "الملف الشخصي" });
  await expect(page.getByTestId("profile-menu-profile")).toBeFocused();
  await expect(menu.getByRole("menuitem", { name: "الإعدادات والخصوصية" })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: "تسجيل الخروج" })).toBeVisible();
  // No help centre exists yet, so the entry is hidden.
  await expect(menu.getByRole("menuitem", { name: "المساعدة والدعم" })).toHaveCount(0);
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("profile-menu-settings")).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("profile-menu-display")).toBeFocused();
  await page.keyboard.press("Enter");
  const display = page.getByRole("menu", { name: "العرض وإمكانية الوصول" });
  await expect(display.getByRole("menuitemradio", { name: "English" })).toBeVisible();
  await expect(page.getByTestId("profile-menu-back")).toBeFocused();
  // Escape in the sub-view goes back to the list, then closes the menu.
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("profile-menu-display")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("profile-menu")).toHaveCount(0);
  await expect(profile).toBeFocused();
});

test("display & accessibility switches the language and the theme", async ({ browser }) => {
  const { b } = await sharedAccounts();
  const page = await pageAs(browser, b);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/home");

  await page.getByRole("button", { name: "الملف الشخصي" }).click();
  await page.getByTestId("profile-menu-display").click();
  await page.getByTestId("profile-menu-theme-light").click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await expect(page.getByTestId("profile-menu-theme-light")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("profile-menu-theme-dark").click();
  await expect(page.locator("html")).toHaveClass(/dark/);

  await page.getByTestId("profile-menu-locale-en").click();
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  await expect(page.getByTestId("profile-menu-locale-en")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("profile-menu-locale-ar").click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
});

test("no horizontal overflow at 390px, with the menus open", async ({ browser }) => {
  const { b } = await sharedAccounts();
  const page = await pageAs(browser, b);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/home");
  await expect(page.getByTestId("top-bar")).toBeVisible();
  // Phones get the bottom bar instead of centre tabs.
  await expect(page.getByTestId("top-tabs")).toBeHidden();
  await expectNoHorizontalOverflow(page);

  await page.getByRole("button", { name: "القائمة", exact: true }).click();
  const menu = page.getByTestId("main-menu");
  await expect(menu).toBeVisible();
  const box = await menu.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  await expectNoHorizontalOverflow(page);
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "الملف الشخصي" }).click();
  const profile = await page.getByTestId("profile-menu").boundingBox();
  expect(profile!.x).toBeGreaterThanOrEqual(0);
  expect(profile!.x + profile!.width).toBeLessThanOrEqual(390);
  await expectNoHorizontalOverflow(page);
});

test("axe finds no serious issue in the top bar, the main menu or the profile menu", async ({ browser }) => {
  const { b } = await sharedAccounts();
  const page = await pageAs(browser, b);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/home");
  await expect(page.getByTestId("top-tabs")).toBeVisible();
  expect(await seriousViolations(page, '[data-testid="top-bar"]')).toEqual([]);

  await page.getByRole("button", { name: "القائمة", exact: true }).click();
  await expect(page.getByTestId("main-menu")).toBeVisible();
  expect(await seriousViolations(page, '[data-testid="main-menu"]')).toEqual([]);
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "الملف الشخصي" }).click();
  await expect(page.getByTestId("profile-menu")).toBeVisible();
  expect(await seriousViolations(page, '[data-testid="profile-menu"]')).toEqual([]);
  await page.getByTestId("profile-menu-display").click();
  expect(await seriousViolations(page, '[data-testid="profile-menu"]')).toEqual([]);
});
