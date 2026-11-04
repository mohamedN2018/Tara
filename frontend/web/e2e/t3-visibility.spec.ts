import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { crc32, deflateSync } from "node:zlib";

import { API, apiAs, befriend, pageAs, sharedAccounts, unique, useLocale } from "./helpers";

// Track T3: the Pages manager, a page's public header (follow, save, report,
// contact info, photos for the team), posting as a page, and the groups hubs
// (groups I manage, pending invitations, my sent requests) are all reached
// from navigation, in Arabic and English.

const DESKTOP = { width: 1440, height: 900 };
// A 256x256 brand-purple PNG, built here so the media worker gets a real image.
function solidPng(size = 256): Buffer {
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
  const row = Buffer.concat([Buffer.from([0]), Buffer.alloc(size * 3, Buffer.from([0x6a, 0x00, 0xf4]))]);
  const raw = Buffer.concat(Array.from({ length: size }, () => row));
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}
const PNG = solidPng();

async function axe(page: Page, selector: string): Promise<string[]> {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).include(selector).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

async function openMenuItem(page: Page, id: string) {
  await page.getByTestId("main-menu-button").click();
  await expect(page.getByTestId(`menu-item-${id}`)).toBeVisible();
  await page.getByTestId(`menu-item-${id}`).click();
}

async function asLang(page: Page, lang: "ar" | "en") {
  await useLocale(page, lang); // the shared accounts stay Arabic
  await page.setViewportSize(DESKTOP);
  await page.goto("/home");
  await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
}

for (const lang of ["ar", "en"] as const) {
  test.describe(`pages and groups hubs from navigation (${lang})`, () => {
    test(`pages manager -> post as page -> header actions (${lang})`, async ({ browser }) => {
      test.setTimeout(240_000);
      const { a, b } = await sharedAccounts();
      const ownerApi = await apiAs(a);
      const tag = `${lang}${unique()}`;
      const handle = `t3_${tag}`;
      const name = `Nile Books ${tag}`;
      const created = await ownerApi.post(`${API}/pages/`, {
        data: { handle, name, category: "Bookshop", description: "Books", location: "Cairo", contact: { website: "https://nile.example" } },
      });
      expect(created.ok(), await created.text()).toBe(true);
      await ownerApi.dispose();

      // Owner: main menu -> Page management -> the card -> Create post (as the page).
      const owner = await pageAs(browser, a);
      await asLang(owner, lang);
      await openMenuItem(owner, "pageManagement");
      await expect(owner).toHaveURL(/\/pages\?tab=manage|\/pages$/);
      const card = owner.getByTestId("page-manage-card").filter({ hasText: name });
      await expect(card).toBeVisible();
      expect(await axe(owner, "#pages-panel")).toEqual([]);
      await card.getByTestId("page-card-compose").click();
      await expect(owner.getByTestId("page-composer")).toBeVisible();
      const body = `first post as the page ${tag}`;
      await owner.getByTestId("page-composer-body").fill(body);
      await owner.getByTestId("page-composer-submit").click();
      await expect(owner.getByTestId("page-composer")).toBeHidden();

      // The card's name opens the page: team header, the post under the page's name.
      await card.getByRole("link", { name }).first().click();
      await expect(owner).toHaveURL(new RegExp(`/pages/${handle}`));
      await expect(owner.getByTestId("page-header")).toBeVisible();
      await expect(owner.getByTestId("page-edit")).toBeVisible();
      await expect(owner.getByTestId("page-edit-avatar")).toBeVisible();
      await expect(owner.getByTestId("page-edit-cover")).toBeVisible();
      await expect(owner.getByTestId("page-follow")).toHaveCount(0);
      const post = owner.locator("article", { hasText: body }).first();
      await expect(post).toBeVisible();
      await expect(post.getByText(name).first()).toBeVisible();
      expect(await axe(owner, "[data-testid=page-header]")).toEqual([]);

      // Camera on the avatar -> upload -> the page now carries the new avatar id.
      const patched = owner.waitForResponse((r) => /\/pages\/id\/[^/]+\/$/.test(r.url()) && r.request().method() === "PATCH");
      await owner.getByTestId("page-avatar-input").setInputFiles({ name: "avatar.png", mimeType: "image/png", buffer: PNG });
      const res = await patched;
      expect(res.ok(), await res.text()).toBe(true);
      expect((await res.json()).data.avatar_media_id).toBeTruthy();

      // Edit page -> contact email -> the About tab links it.
      await owner.getByTestId("page-edit").click();
      await expect(owner.getByTestId("page-edit-dialog")).toBeVisible();
      await owner.getByTestId("page-contact-email").fill(`hello_${tag}@example.com`);
      await owner.getByTestId("page-edit-save").click();
      await expect(owner.getByTestId("page-edit-dialog")).toBeHidden();
      await owner.getByTestId("page-tab-about").click();
      await expect(owner.getByTestId("page-contact").locator(`a[href="mailto:hello_${tag}@example.com"]`)).toBeVisible();
      await expect(owner.getByTestId("page-contact").locator('a[href="https://nile.example"]')).toBeVisible();
      await owner.getByTestId("page-tab-team").click();
      await expect(owner.getByTestId("page-members")).toBeVisible();
      await owner.context().close();

      // Visitor: menu -> Pages -> Discover -> the page -> Follow, Save, Report.
      const visitor = await pageAs(browser, b);
      await asLang(visitor, lang);
      await openMenuItem(visitor, "pages");
      await visitor.getByTestId("pages-tab-discover").click();
      await visitor.getByRole("searchbox").fill(name);
      const found = visitor.getByTestId("pages-list-discover").getByTestId("page-list-item").filter({ hasText: name });
      await expect(found).toBeVisible();
      await found.getByRole("link", { name }).first().click();
      await expect(visitor.getByTestId("page-header")).toBeVisible();
      await expect(visitor.getByTestId("page-edit")).toHaveCount(0);
      await expect(visitor.getByTestId("page-create-post")).toHaveCount(0);
      await expect(visitor.getByTestId("page-tab-team")).toHaveCount(0);
      await expect(visitor.locator("article", { hasText: body }).first()).toBeVisible();
      await visitor.getByTestId("page-follow").click();
      await expect(visitor.getByTestId("page-follow")).toHaveAttribute("aria-pressed", "true");
      await visitor.getByTestId("page-more").click();
      await visitor.getByTestId("page-save").click();
      await visitor.getByTestId("page-more").click();
      await expect(visitor.getByTestId("page-save")).toHaveText(lang === "ar" ? /إزالة/ : /Remove from saved/);
      await visitor.getByTestId("page-report").click();
      await expect(visitor.getByTestId("report-dialog")).toBeVisible();
      expect(await axe(visitor, "[data-testid=report-dialog]")).toEqual([]);
      await visitor.keyboard.press("Escape");
      await expect(visitor.getByTestId("report-dialog")).toBeHidden();

      // Main menu -> Followed pages lists it; the manager's Saved pages too.
      await openMenuItem(visitor, "followedPages");
      await expect(visitor.getByTestId("pages-list-followed").getByText(name)).toBeVisible();
      await visitor.getByTestId("pages-tab-saved").click();
      await expect(visitor.getByTestId("pages-list-saved").getByText(name)).toBeVisible();
      expect(await axe(visitor, "#pages-panel")).toEqual([]);
      await visitor.context().close();
    });

    test(`page posts: edit by role, hidden with the page; suggested pages; searchable (${lang})`, async ({ browser }) => {
      test.setTimeout(240_000);
      const { a, b, c } = await sharedAccounts();
      const ownerApi = await apiAs(a);
      const tag = `${lang}${unique()}`;
      const name = `Fix C ${tag}`;
      const created = await ownerApi.post(`${API}/pages/`, { data: { handle: `t3c_${tag}`, name, category: "Bookshop" } });
      expect(created.ok(), await created.text()).toBe(true);
      const pageId = (await created.json()).data.id as string;
      // A second, published page, so graph has at least one page to suggest to b.
      const other = await ownerApi.post(`${API}/pages/`, { data: { handle: `t3s_${tag}`, name: `Suggested ${tag}` } });
      expect(other.ok(), await other.text()).toBe(true);
      const posted = await ownerApi.post(`${API}/posts/`, { data: { body: `page post ${tag}`, page_id: pageId } });
      expect(posted.ok(), await posted.text()).toBe(true);
      const postId = (await posted.json()).data.id as string;
      const analyst = await ownerApi.post(`${API}/pages/id/${pageId}/members/`, { data: { account_id: c.id, role: "analyst" } });
      expect(analyst.ok(), await analyst.text()).toBe(true);

      // Owner: the page's timeline -> "..." on the page's post -> Edit -> save.
      const owner = await pageAs(browser, a);
      await asLang(owner, lang);
      await owner.goto(`/pages/t3c_${tag}`);
      const article = owner.locator("article", { hasText: `page post ${tag}` }).first();
      await expect(article).toBeVisible();
      await article.getByTestId("post-menu").click();
      await article.getByTestId("menu-edit").click();
      const dialog = owner.getByTestId("composer-dialog");
      await expect(dialog).toBeVisible();
      await dialog.locator("textarea").first().fill(`edited by the owner ${tag}`);
      const saved = owner.waitForResponse((r) => r.url().includes(`/posts/${postId}/`) && r.request().method() === "PATCH");
      await dialog.getByTestId("composer-submit").click();
      expect((await saved).status()).toBe(200);
      await expect(owner.locator("article", { hasText: `edited by the owner ${tag}` }).first()).toBeVisible();
      // The page name sits next to the avatar, in the page's direction.
      await expect(owner.getByTestId("page-name").locator("bdi")).toHaveText(name);
      await owner.context().close();

      // An analyst may not edit; a stranger is told the post does not exist.
      const analystApi = await apiAs(c);
      expect((await analystApi.patch(`${API}/posts/${postId}/`, { data: { body: "x" } })).status()).toBe(403);
      await analystApi.dispose();
      const visitorApi = await apiAs(b);
      expect((await visitorApi.patch(`${API}/posts/${postId}/`, { data: { body: "x" } })).status()).toBe(404);
      expect((await visitorApi.get(`${API}/posts/${postId}/`)).status()).toBe(200);

      // The page goes back to draft: its post 404s for outsiders on every read.
      const hidden = await ownerApi.patch(`${API}/pages/id/${pageId}/`, { data: { status: "draft" } });
      expect(hidden.ok(), await hidden.text()).toBe(true);
      await expect.poll(async () => (await visitorApi.get(`${API}/posts/${postId}/`)).status(), { timeout: 40_000 }).toBe(404);
      expect((await visitorApi.get(`${API}/posts/${postId}/comments/`)).status()).toBe(404);
      const timeline = await visitorApi.get(`${API}/posts/`, { params: { author_id: pageId } });
      expect((await timeline.json()).data).toEqual([]);
      const batch = await visitorApi.post(`${API}/posts/batch/`, { data: { ids: [postId] } });
      expect((await batch.json()).data).toEqual([]);
      // The team still sees it.
      expect((await ownerApi.get(`${API}/posts/${postId}/`)).status()).toBe(200);
      await ownerApi.dispose();

      // Visitor: Pages -> Discover -> "Suggested for you" with Follow and Remove.
      const visitor = await pageAs(browser, b);
      await asLang(visitor, lang);
      await openMenuItem(visitor, "pages");
      await visitor.getByTestId("pages-tab-discover").click();
      const row = visitor.getByTestId("pages-suggested");
      await expect(row).toBeVisible();
      await expect(row).toContainText(lang === "ar" ? "مقترحة لك" : "Suggested for you");
      expect(await axe(visitor, "[data-testid=pages-suggested]")).toEqual([]);
      const items = row.getByTestId("pages-suggested-item");
      const before = await items.count();
      const dismissed = visitor.waitForResponse((r) => r.url().includes("/social/suggestions/") && r.request().method() === "POST");
      await items.first().getByTestId("pages-suggested-remove").click();
      expect((await dismissed).ok()).toBe(true);
      await expect(items).toHaveCount(before - 1);
      await row.getByTestId("pages-suggested-undo").click();
      await expect(items).toHaveCount(before);
      if (before > 1) {
        const followed = visitor.waitForResponse((r) => r.url().includes("/follows/") && r.request().method() === "POST");
        await items.nth(1).getByTestId("pages-suggested-follow").click();
        expect((await followed).ok()).toBe(true);
        await expect(items.nth(1).getByTestId("pages-suggested-followed")).toBeVisible();
      }

      // Settings -> Privacy -> "Let people find me in search": off, then back on.
      await visitor.goto("/settings/privacy");
      const sw = visitor.getByTestId("privacy-searchable-switch");
      await expect(sw).toHaveAttribute("aria-checked", "true");
      expect(await axe(visitor, "[data-testid=privacy-searchable]")).toEqual([]);
      const off = visitor.waitForResponse((r) => r.url().endsWith("/profile/me/") && r.request().method() === "PATCH");
      await sw.click();
      expect((await off).ok()).toBe(true);
      await expect(sw).toHaveAttribute("aria-checked", "false");
      const searcherApi = await apiAs(a);
      const findB = async () => {
        const res = await searcherApi.get(`${API}/search/`, { params: { q: b.handle, type: "user" } });
        return ((await res.json()).data.results as { id?: string; doc_id?: string; owner_id?: string }[]).some(
          (r) => r.owner_id === b.id || r.id === b.id || r.doc_id === b.id,
        );
      };
      await expect.poll(findB, { timeout: 40_000 }).toBe(false);
      const on = visitor.waitForResponse((r) => r.url().endsWith("/profile/me/") && r.request().method() === "PATCH");
      await sw.click();
      expect((await on).ok()).toBe(true);
      await expect(sw).toHaveAttribute("aria-checked", "true");
      await expect.poll(findB, { timeout: 40_000 }).toBe(true);
      await searcherApi.dispose();
      await visitorApi.dispose();
      await visitor.context().close();
    });

    test(`groups I manage -> pending invitations; my sent requests (${lang})`, async ({ browser }) => {
      test.setTimeout(180_000);
      const { a, b, c } = await sharedAccounts();
      const ownerApi = await apiAs(a);
      const tag = `${lang}${unique()}`;
      const make = async (handle: string, extra: object = {}) => {
        const res = await ownerApi.post(`${API}/groups/`, { data: { handle, name: `Club ${handle}`, ...extra } });
        expect(res.ok(), await res.text()).toBe(true);
      };
      const managed = `t3m_${tag}`;
      const closed = `t3r_${tag}`;
      await make(managed);
      await make(closed, { privacy: "private", membership_approval: true });
      await befriend(a, c); // invitations go to friends only
      const invited = await ownerApi.post(`${API}/groups/${managed}/invite/`, { data: { account_ids: [c.id] } });
      expect(invited.ok(), await invited.text()).toBe(true);
      await ownerApi.dispose();
      const requesterApi = await apiAs(b);
      expect((await requesterApi.post(`${API}/groups/${closed}/join/`)).status()).toBe(201);
      await requesterApi.dispose();

      // Owner: main menu -> Group management -> the group's Manage -> Pending invitations.
      const owner = await pageAs(browser, a);
      await asLang(owner, lang);
      await openMenuItem(owner, "groupManagement");
      await expect(owner).toHaveURL(/\/groups\?tab=manage/);
      const card = owner.getByTestId("groups-list-manage").locator("article", { hasText: `Club ${managed}` });
      await expect(card).toBeVisible();
      expect(await axe(owner, "#groups-panel")).toEqual([]);
      await card.getByTestId("group-manage-link").click();
      await expect(owner).toHaveURL(new RegExp(`/groups/${managed}/manage`));
      await owner.getByRole("button", { name: lang === "ar" ? "الدعوات المعلّقة" : "Pending invitations" }).click();
      const row = owner.getByTestId("group-member").first();
      await expect(row).toBeVisible();
      await row.getByTestId("group-invite-revoke").click();
      await expect(owner.getByTestId("group-member")).toHaveCount(0);
      await owner.context().close();

      // Requester: Groups (left nav) -> Sent requests lists the private group with Cancel.
      const requester = await pageAs(browser, b);
      await asLang(requester, lang);
      await openMenuItem(requester, "groups");
      await requester.getByRole("tab", { name: lang === "ar" ? "الطلبات المُرسلة" : "Sent requests" }).click();
      await expect(requester.getByTestId("groups-list-requests").getByText(`Club ${closed}`)).toBeVisible();
      expect(await axe(requester, "#groups-panel")).toEqual([]);
      await requester.context().close();
    });
  });
}
