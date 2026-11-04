import AxeBuilder from "@axe-core/playwright";
import { type Browser, type Page, expect, test } from "@playwright/test";
import { execSync } from "node:child_process";
import { crc32, deflateSync } from "node:zlib";

import { type Account, API, apiAs, pageAs, sharedAccounts, unique, useLocale } from "./helpers";

// Track T6: the marketplace's own navigation column (browse, notifications,
// inbox, buying, selling, create, categories), listing photos, editing and
// archiving, the seller shop, and the ads manager (objective, schedule, ad set
// frequency cap and placements, ad image, rejection reason, edit and resubmit,
// marketplace sponsored slot) are all reached from navigation, in Arabic and English.

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };

function solidPng(size = 128): Buffer {
  const chunk = (type: string, data: Buffer) => {
    const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
    const out = Buffer.alloc(body.length + 8);
    out.writeUInt32BE(data.length, 0);
    body.copy(out, 4);
    out.writeUInt32BE(crc32(body) >>> 0, body.length + 4);
    return out;
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header.set([8, 2, 0, 0, 0], 8);
  const row = Buffer.concat([Buffer.from([0]), Buffer.alloc(size * 3, Buffer.from([0xa8, 0x55, 0xf7]))]);
  const raw = Buffer.concat(Array.from({ length: size }, () => row));
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}
const PNG = solidPng();

const promote = (email: string) =>
  execSync(`docker exec tara-identity-1 python manage.py create_admin ${email}`, { stdio: "pipe" });

async function axe(page: Page, selector: string): Promise<string[]> {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).include(selector).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

async function open(browser: Browser, account: Account, lang: "ar" | "en", size = DESKTOP): Promise<Page> {
  const page = await pageAs(browser, account);
  await useLocale(page, lang);
  await page.setViewportSize(size);
  await page.goto("/home");
  await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
  return page;
}

async function menu(page: Page, id: string) {
  await page.getByTestId("main-menu-button").click();
  await expect(page.getByTestId(`menu-item-${id}`)).toBeVisible();
  await page.getByTestId(`menu-item-${id}`).click();
}

async function publishedListing(account: Account, title: string): Promise<string> {
  const api = await apiAs(account);
  const cats = (await (await api.get(`${API}/marketplace/categories/`)).json()).data;
  const res = await api.post(`${API}/marketplace/listings/`, {
    data: { category_id: cats[0].id, title, price: "150", currency: "EGP", condition: "good" },
  });
  expect(res.ok(), await res.text()).toBe(true);
  const id = (await res.json()).data.id as string;
  const pub = await api.post(`${API}/marketplace/listings/${id}/publish/`);
  expect(pub.ok(), await pub.text()).toBe(true);
  await api.dispose();
  return id;
}

const L = {
  ar: {
    edit: "تعديل الإعلان",
    archive: "أرشفة الإعلان",
    archived: "مؤرشف",
    save: "حفظ",
    contact: "راسل البائع",
    send: "إرسال الرسالة",
    objective: "الزيارات",
    pending: "قيد المراجعة",
    rejected: "مرفوض",
    reject: "رفض",
    approve: "موافقة",
    newCampaign: "حملة جديدة",
  },
  en: {
    edit: "Edit listing",
    archive: "Archive listing",
    archived: "Archived",
    save: "Save",
    contact: "Message seller",
    send: "Send message",
    objective: "Traffic",
    pending: "In review",
    rejected: "Rejected",
    reject: "Reject",
    approve: "Approve",
    newCampaign: "New campaign",
  },
} as const;

for (const lang of ["ar", "en"] as const) {
  const l = L[lang];

  test.describe(`marketplace hubs from navigation (${lang})`, () => {
    test(`menu -> marketplace -> selling -> create with a photo, edit, archive (${lang})`, async ({ browser }) => {
      test.setTimeout(180_000);
      const { a } = await sharedAccounts();
      const page = await open(browser, a, lang);
      const title = `Lamp ${lang} ${unique()}`;

      await menu(page, "marketplace");
      await expect(page).toHaveURL(/\/marketplace$/);
      const nav = page.getByTestId("market-nav");
      await expect(nav).toBeVisible();
      for (const hub of ["browse", "notifications", "inbox", "buying", "selling"]) {
        await expect(nav.getByTestId(`market-nav-${hub}`)).toBeVisible();
      }
      expect(await axe(page, "[data-testid=market-nav]")).toEqual([]);
      // Seeded category names follow the UI language.
      await expect(nav).toContainText(lang === "ar" ? "إلكترونيات" : "Electronics");
      if (lang === "ar") await expect(nav).not.toContainText("Electronics");

      await nav.getByTestId("market-nav-selling").click();
      await expect(page).toHaveURL(/tab=selling/);
      await expect(page.getByTestId("selling-summary")).toBeVisible();

      // Create new listing, with a photo uploaded through the media service.
      await nav.getByTestId("market-create").click();
      const dialog = page.getByTestId("listing-dialog");
      await expect(dialog).toBeVisible();
      await dialog.getByTestId("listing-photo-input").setInputFiles({ name: "lamp.png", mimeType: "image/png", buffer: PNG });
      await expect(dialog.getByTestId("listing-photo")).toHaveCount(1, { timeout: 30_000 });
      await dialog.locator("#listing-title").fill(title);
      await dialog.locator("#listing-price").fill("120");
      await expect(dialog.getByTestId("listing-submit")).toBeEnabled();
      await page.waitForTimeout(500); // let the button's enabled transition settle before axe
      expect(await axe(page, "[data-testid=listing-dialog]")).toEqual([]);
      await dialog.getByTestId("listing-submit").click();
      await expect(dialog).toBeHidden();
      await expect(page).toHaveURL(/tab=selling/);
      const card = page.getByTestId("listing-card").filter({ hasText: title });
      await expect(card).toBeVisible();

      // The photo really is on the listing.
      const api = await apiAs(a);
      const mine = (await (await api.get(`${API}/marketplace/my-listings/`)).json()).data as { id: string; title: string; media: unknown[] }[];
      const created = mine.find((m) => m.title === title);
      expect(created?.media).toHaveLength(1);

      // Edit from the card's "..." menu.
      await card.getByTestId("listing-owner-menu").click();
      await page.getByRole("menuitem", { name: l.edit }).click();
      const edit = page.getByTestId("listing-dialog");
      await expect(edit.locator("#listing-title")).toHaveValue(title);
      await expect(edit.getByTestId("listing-photo")).toHaveCount(1);
      await edit.locator("#listing-title").fill(`${title} v2`);
      await edit.getByTestId("listing-submit").click();
      await expect(edit).toBeHidden();
      const edited = page.getByTestId("listing-card").filter({ hasText: `${title} v2` });
      await expect(edited).toBeVisible();

      // On the listing page the seller's actions and "..." share one row.
      await edited.locator(`a[href="/marketplace/${created!.id}"]`).first().click();
      await expect(page).toHaveURL(new RegExp(`/marketplace/${created!.id}`));
      const row = page.getByTestId("owner-action-row");
      await expect(row.getByTestId("listing-owner-menu")).toBeVisible();
      const rowBox = (await row.boundingBox())!;
      const moreBox = (await row.getByTestId("listing-owner-menu").boundingBox())!;
      const editBox = (await row.getByTestId("owner-edit").boundingBox())!;
      expect(Math.abs(moreBox.y + moreBox.height / 2 - (editBox.y + editBox.height / 2))).toBeLessThan(4);
      expect(rowBox.height).toBeLessThan(60);
      await page.goBack();
      await expect(page).toHaveURL(/tab=selling/);

      // Archive, behind a confirmation.
      await edited.getByTestId("listing-owner-menu").click();
      await page.getByRole("menuitem", { name: l.archive }).click();
      await page.getByTestId("confirm-action").getByRole("button", { name: l.archive }).click();
      await expect(edited).toContainText(l.archived);
      await page.mouse.move(0, 0);
      await page.waitForTimeout(500); // chips re-render with the new counts; let transitions settle
      expect(await axe(page, "[data-testid=selling-hub]")).toEqual([]);

      // The listing page says the same and offers no publish to buyers.
      const res = await api.get(`${API}/marketplace/listings/${created!.id}/`);
      expect((await res.json()).data.status).toBe("archived");
      await api.dispose();
    });

    test(`search -> listing -> message seller; buying, inbox, seller shop, notifications (${lang})`, async ({ browser }) => {
      test.setTimeout(180_000);
      const { a, b } = await sharedAccounts();
      const tag = `shop${lang}${unique()}`;
      await publishedListing(a, `Chair ${tag}`);

      // The buyer finds it from the column's search and messages the seller.
      const buyer = await open(browser, b, lang);
      await menu(buyer, "marketplace");
      const search = buyer.getByTestId("market-nav").getByRole("searchbox");
      await search.fill(tag);
      await search.press("Enter");
      await expect(buyer.getByTestId("browse-heading")).toContainText(tag);
      await buyer.getByTestId("listing-card").filter({ hasText: tag }).locator("a").first().click();
      await buyer.getByRole("button", { name: l.contact }).click();
      await buyer.getByRole("button", { name: l.send }).click();
      await expect(buyer).toHaveURL(/\/messages\//);

      // Buying -> Sellers you messaged lists it.
      await menu(buyer, "marketplace");
      await buyer.getByTestId("market-nav").getByTestId("market-nav-buying").click();
      await buyer.getByTestId("buying-messaged").click();
      await expect(buyer.getByTestId("inquiry-row").filter({ hasText: tag })).toBeVisible();
      expect(await axe(buyer, "[data-testid=market-inbox]")).toEqual([]);

      // The seller shop, from the listing's seller card.
      await buyer.getByTestId("inquiry-row").filter({ hasText: tag }).getByRole("link", { name: new RegExp(tag) }).first().click();
      await buyer.getByTestId("seller-link").click();
      await expect(buyer).toHaveURL(new RegExp(`/marketplace/sellers/${a.id}`));
      await expect(buyer.getByTestId("seller-shop").getByTestId("listing-card").filter({ hasText: tag })).toBeVisible();
      expect(await axe(buyer, "[data-testid=seller-shop]")).toEqual([]);

      // The seller sees the question in the marketplace inbox (main menu entry).
      const seller = await open(browser, a, lang);
      await menu(seller, "marketplaceInbox");
      await expect(seller).toHaveURL(/tab=inbox/);
      const row = seller.getByTestId("inquiry-row").filter({ hasText: tag });
      await expect(row).toBeVisible();
      await row.getByRole("button").click();
      await expect(seller).toHaveURL(/\/messages\//);

      // Marketplace notifications: the inquiry arrives there.
      await menu(seller, "marketplace");
      await seller.getByTestId("market-nav").getByTestId("market-nav-notifications").click();
      await expect(seller.getByTestId("market-notifications")).toBeVisible();
      await expect(seller.getByTestId("market-notifications").locator("article").first()).toBeVisible({ timeout: 20_000 });
      expect(await axe(seller, "[data-testid=market-notifications]")).toEqual([]);

      // Phones: the hubs are a row of pills.
      await seller.setViewportSize(MOBILE);
      await seller.getByTestId("market-pill-selling").click();
      await expect(seller.getByTestId("selling-hub")).toBeVisible();
    });
  });

  test.describe(`ads manager from navigation (${lang})`, () => {
    test(`objective, schedule, ad set, image, rejection reason, resubmit, marketplace slot (${lang})`, async ({ browser }) => {
      test.setTimeout(240_000);
      const { a, b, c } = await sharedAccounts();
      promote(c.email);
      const name = `Campaign ${lang} ${unique()}`;
      const headline = `Ad ${unique()}`;

      const page = await open(browser, a, lang);
      await menu(page, "adsManager");
      await expect(page).toHaveURL(/\/ads$/);
      await page.getByRole("button", { name: l.newCampaign }).click();
      const form = page.getByTestId("campaign-form");
      await form.getByTestId("objective-traffic").click();
      await form.locator("#campaign-name").fill(name);
      await form.locator("#campaign-budget").fill("50");
      const now = new Date();
      const local = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
      await form.locator("#campaign-start").fill(local(new Date(now.getTime() - 3_600_000)));
      await form.locator("#campaign-end").fill(local(new Date(now.getTime() + 86_400_000)));
      expect(await axe(page, "[data-testid=campaign-form]")).toEqual([]);
      await form.getByRole("button", { name: lang === "ar" ? "إنشاء الحملة" : "Create campaign" }).click();
      await expect(page).toHaveURL(/\/ads\/campaigns\//);
      await expect(page.getByTestId("campaign-meta")).toContainText(l.objective);

      // Ad set: only served placements, and a frequency cap.
      const setForm = page.getByTestId("ad-set-form");
      await expect(setForm.locator("#set-placement option")).toHaveCount(2);
      await setForm.locator("input").first().fill("Marketplace set");
      await setForm.locator("#set-placement").selectOption("marketplace");
      await setForm.locator("#set-cap").fill("3");
      await setForm.getByRole("button").click();
      const set = page.getByTestId("ad-set");
      await expect(set).toContainText("3");

      // Creative with an image.
      const creative = set.getByTestId("creative-form");
      await creative.locator("input[type=file]").setInputFiles({ name: "ad.png", mimeType: "image/png", buffer: PNG });
      await expect(creative.getByTestId("ad-image").locator("img")).toBeVisible({ timeout: 30_000 });
      await creative.getByPlaceholder(lang === "ar" ? "العنوان" : "Headline").fill(headline);
      await creative.locator("input[type=url]").fill("https://example.com/offer");
      await creative.getByRole("button", { name: lang === "ar" ? "إضافة إعلان" : "Add ad" }).click();
      const ad = set.getByTestId("creative").filter({ hasText: headline });
      await expect(ad.getByTestId("creative-review")).toHaveText(l.pending);
      await page.waitForTimeout(400); // the submit button fades back from its disabled state
      expect(await axe(page, "[data-testid=ad-set]")).toEqual([]);
      // A new campaign delivers straight away (it can be paused).
      await expect(page.getByRole("button", { name: lang === "ar" ? "إيقاف مؤقت" : "Pause" })).toBeVisible();

      // A reviewer must give a reason to reject.
      const reviewer = await open(browser, c, lang);
      await menu(reviewer, "adReview");
      const item = reviewer.getByTestId("review-item").filter({ hasText: headline });
      await expect(item).toBeVisible();
      await item.getByRole("button", { name: l.reject }).click();
      await expect(item.getByTestId("confirm-reject")).toBeDisabled();
      await item.locator("textarea").fill("The offer is not on the linked page");
      await item.getByTestId("confirm-reject").click();
      await expect(item).toBeHidden();

      // The advertiser reads the reason, edits and resubmits.
      await page.reload();
      const rejected = page.getByTestId("creative").filter({ hasText: headline });
      await expect(rejected.getByTestId("creative-review")).toHaveText(l.rejected);
      await expect(rejected.getByTestId("creative-rejection")).toContainText("The offer is not on the linked page");
      await rejected.getByTestId("creative-edit").click();
      await rejected.getByTestId("creative-edit-form").locator("input[dir=auto]").first().fill(`${headline} fixed`);
      await rejected.getByTestId("creative-edit-form").getByRole("button").last().click();
      const fixed = page.getByTestId("creative").filter({ hasText: `${headline} fixed` });
      await expect(fixed.getByTestId("creative-review")).toHaveText(l.pending);

      // Approved, it is served in the marketplace grid as a sponsored cell.
      await reviewer.reload();
      await reviewer.getByTestId("review-item").filter({ hasText: `${headline} fixed` }).getByRole("button", { name: l.approve }).click();
      const viewer = await open(browser, b, lang);
      await menu(viewer, "marketplace");
      await expect(viewer.getByTestId("listing-grid").getByTestId("sponsored")).toBeVisible({ timeout: 20_000 });
    });
  });
}
