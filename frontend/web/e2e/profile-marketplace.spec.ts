import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { API, type Account, apiAs, pageAs, sharedAccounts, unique, useLocale } from "./helpers";

// T6 on the profile: a seller's public listings show under a "Marketplace" tab
// on their profile. The tab follows marketplace's seller-page rule (404 when
// blocked, unknown, or nothing public), so the UI is checked against the API.

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

async function publishedListing(seller: Account, title: string): Promise<string> {
  const api = await apiAs(seller);
  const cats = (await (await api.get(`${API}/marketplace/categories/`)).json()).data;
  const res = await api.post(`${API}/marketplace/listings/`, {
    data: { category_id: cats[0].id, title, price: "150", currency: "EGP", condition: "good" },
  });
  expect(res.ok(), await res.text()).toBe(true);
  const id = (await res.json()).data.id as string;
  expect((await api.post(`${API}/marketplace/listings/${id}/publish/`)).ok()).toBe(true);
  await api.dispose();
  return id;
}

const TAB = { ar: "السوق", en: "Marketplace" };

for (const lang of ["ar", "en"] as const) {
  test(`profile Marketplace tab shows the seller's listings (${lang})`, async ({ browser }) => {
    test.setTimeout(120_000);
    const { a, b, c } = await sharedAccounts();
    const title = `Lamp ${unique()}`;
    const listingId = await publishedListing(a, title);

    const page = await pageAs(browser, b);
    await useLocale(page, lang);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/u/id/${a.id}`);
    const tab = page.getByTestId("profile-tab-marketplace");
    await expect(tab).toBeVisible();
    await expect(tab).toHaveText(TAB[lang]);
    await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
    await tab.click();
    await expect(page).toHaveURL(/tab=marketplace/);
    const shop = page.getByTestId("profile-marketplace");
    await expect(shop).toBeVisible();
    await expect(shop.getByTestId("listing-card").filter({ hasText: title })).toBeVisible();
    expect(await axe(page, "[data-testid=profile-marketplace]")).toEqual([]);
    // A card opens the listing.
    await shop.getByTestId("listing-card").filter({ hasText: title }).click();
    await expect(page).toHaveURL(new RegExp(`/marketplace/(listings/)?${listingId}`));

    // Phones: the tab folds into "More".
    await page.goto(`/u/id/${a.id}`);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByTestId("profile-tab-marketplace")).toBeHidden();
    await page.getByTestId("profile-tab-more").click();
    await page.getByTestId("profile-tab-more-marketplace").click();
    await expect(page.getByTestId("profile-marketplace")).toBeVisible();

    // Visibility follows the server: where marketplace's seller page is a 404
    // for this viewer, there is no tab and a deep link lands on Posts. The
    // profile asks `shop/`, which answers 200 {has_shop} in every case.
    const viewerApi = await apiAs(b);
    const status = (await viewerApi.get(`${API}/marketplace/sellers/${c.id}/`)).status();
    const shopCheck = await viewerApi.get(`${API}/marketplace/sellers/${c.id}/shop/`);
    expect(shopCheck.status()).toBe(200);
    expect((await shopCheck.json()).data.has_shop).toBe(status === 200);
    await viewerApi.dispose();
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/u/id/${c.id}?tab=marketplace`);
    await expect(page.getByTestId("profile-tab-posts")).toBeVisible();
    if (status === 404) {
      await expect(page).not.toHaveURL(/tab=marketplace/);
      await expect(page.getByTestId("profile-tab-posts")).toHaveAttribute("aria-selected", "true");
      await expect(page.getByTestId("profile-tab-marketplace")).toHaveCount(0);
      await expect(page.getByTestId("profile-marketplace")).toHaveCount(0);
    } else {
      expect(status).toBe(200);
      await expect(page.getByTestId("profile-marketplace")).toBeVisible();
    }
    await page.context().close();
  });
}
