// Fix track D, round 3: a group is no way around "who can message you"; a
// message to a Page reaches its team (notification + badge); marketplace rows
// name their listing; message excerpts in notifications are isolated; and the
// chat dock stays out of the admin console. Arabic and English.
import { execSync } from "node:child_process";

import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, type Browser, expect, type Page, request, test } from "@playwright/test";

import { type Account, API, apiAs, befriend, pageAs, sharedAccounts, signupData, unique, useLocale, verificationToken } from "./helpers";

const LANGS = ["ar", "en"] as const;
type Lang = (typeof LANGS)[number];

async function open(browser: Browser, who: Account, lang: Lang, mobile = false): Promise<Page> {
  const page = await pageAs(browser, who);
  await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 });
  await useLocale(page, lang);
  return page;
}

async function axe(page: Page, selector: string) {
  await page.waitForTimeout(300);
  const result = await new AxeBuilder({ page }).include(selector).withTags(["wcag2a", "wcag2aa"]).analyze();
  const bad = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${v.id}: ${v.nodes[0]?.target}`)).toEqual([]);
}

async function stranger(api: APIRequestContext): Promise<Account | null> {
  const tag = unique();
  const handle = `e2e_fd3_${tag}`;
  const email = `${handle}@example.com`;
  const res = await api.post(`${API}/auth/register/`, { data: signupData(email, handle, "Nour", tag) });
  if (res.status() !== 201) return null; // registration is rate limited per hour
  const token = await verificationToken(api, email);
  await api.post(`${API}/auth/verify-email/`, { data: { token } });
  const { data } = await res.json();
  return { email, handle, name: `Nour ${tag}`, id: data.account_id };
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
  return id;
}

test("a stranger's group follows 'who can message you' (API)", async () => {
  test.setTimeout(120_000);
  const { b } = await sharedAccounts();
  const anon = await request.newContext();
  const newcomer = await stranger(anon);
  await anon.dispose();
  test.skip(!newcomer, "registration rate limit reached");
  const bApi = await apiAs(b);
  const nApi = await apiAs(newcomer!);
  try {
    await bApi.patch(`${API}/conversations/settings/`, { data: { message_from: "friends" } });
    const refused = await nApi.post(`${API}/conversations/`, { data: { type: "group", title: "x", member_ids: [b.id] } });
    expect(refused.status()).toBe(403);
    expect((await refused.json()).error.code).toBe("messaging_restricted");

    await bApi.patch(`${API}/conversations/settings/`, { data: { message_from: "everyone" } });
    const made = await nApi.post(`${API}/conversations/`, { data: { type: "group", title: `g ${unique()}`, member_ids: [b.id] } });
    expect(made.status()).toBe(201);
    const group = (await made.json()).data.id as string;
    expect((await nApi.post(`${API}/conversations/${group}/messages/`, { data: { body: "hi" } })).ok()).toBe(true);
    const folder = async (name: string) =>
      ((await (await bApi.get(`${API}/conversations/`, { params: { folder: name } })).json()).data as { id: string }[]).map((c) => c.id);
    expect(await folder("requests")).toContain(group);
    expect(await folder("inbox")).not.toContain(group);
  } finally {
    await bApi.patch(`${API}/conversations/settings/`, { data: { message_from: "everyone" } });
  }
});

for (const lang of LANGS) {
  test.describe(`chat team notices and marketplace rows (${lang})`, () => {
    test("a message to a Page notifies its team, badges the inbox and opens the thread", async ({ browser }) => {
      test.setTimeout(180_000);
      const { a, b } = await sharedAccounts();
      const tag = `${lang}${unique()}`;
      const handle = `fd3_${tag}`;
      const name = `Nile Bakery ${tag}`;
      const ownerApi = await apiAs(a);
      const created = await ownerApi.post(`${API}/pages/`, { data: { handle, name, category: "Bakery" } });
      expect(created.ok(), await created.text()).toBe(true);
      const pageId = (await created.json()).data.id as string;

      const bApi = await apiAs(b);
      const conv = await bApi.post(`${API}/conversations/`, { data: { type: "page", page_id: pageId } });
      expect(conv.ok(), await conv.text()).toBe(true);
      const conversationId = (await conv.json()).data.id as string;
      const question = `cake ${tag}`;
      expect((await bApi.post(`${API}/conversations/${conversationId}/messages/`, { data: { body: question } })).ok()).toBe(true);

      // The badge on the Page's inbox link.
      await expect
        .poll(async () => (await (await ownerApi.get(`${API}/conversations/team/unread/`, { params: { page_id: pageId } })).json()).data?.conversations)
        .toBe(1);
      expect((await bApi.get(`${API}/conversations/team/unread/`, { params: { page_id: pageId } })).status()).toBe(404);
      const owner = await open(browser, a, lang);
      await owner.goto(`/pages/${handle}`);
      await expect(owner.getByTestId("page-inbox-unread")).toHaveText("1");

      // The notification names the sender and the Page, and opens that thread.
      await owner.goto("/notifications");
      const row = owner.locator('[data-testid="notification-item"][data-kind="message.page"]').filter({ hasText: question }).first();
      await expect(row).toBeVisible({ timeout: 20_000 });
      await expect(row).toContainText(name);
      await expect(row.getByTestId("notification-excerpt")).toHaveText(question);
      await axe(owner, '[data-testid="notification-item"][data-kind="message.page"]');
      await row.locator("a").first().click();
      await expect(owner).toHaveURL(new RegExp(`/pages/id/${pageId}/inbox\\?conversation=${conversationId}`));
      await expect(owner.getByTestId("team-thread")).toContainText(question);
      await owner.goto(`/pages/${handle}`);
      await expect(owner.getByTestId("page-inbox-link")).toBeVisible();
      await expect(owner.getByTestId("page-inbox-unread")).toHaveCount(0);
    });

    test("Marketplace folder rows name their listing and show its photo slot", async ({ browser }) => {
      test.setTimeout(180_000);
      const { a, b } = await sharedAccounts();
      const titles = [`Oak desk ${lang}${unique()}`, `Red bike ${lang}${unique()}`];
      const buyer = await apiAs(b);
      for (const title of titles) {
        const id = await publishedListing(a, title);
        expect((await buyer.post(`${API}/marketplace/listings/${id}/contact/`, { data: { message: "Still available?" } })).ok()).toBe(true);
      }
      const seller = await open(browser, a, lang);
      await seller.goto("/messages?folder=marketplace");
      for (const title of titles) {
        const row = seller.getByTestId("conversation-row").filter({ has: seller.getByTestId("conversation-listing").filter({ hasText: title }) });
        await expect(row).toBeVisible({ timeout: 20_000 });
        await expect(row.getByTestId("listing-avatar")).toBeVisible();
      }
      await axe(seller, '[data-testid="conversation-row"]');
    });

    test("a message excerpt in the other script keeps its own direction", async ({ browser }) => {
      test.setTimeout(120_000);
      const { a, b } = await sharedAccounts();
      await befriend(a, b);
      const aApi = await apiAs(a);
      const dm = (await (await aApi.post(`${API}/conversations/`, { data: { type: "dm", other_id: b.id } })).json()).data.id as string;
      const body = lang === "ar" ? `seen? ${unique()}` : `شفت؟ ${unique()}`;
      expect((await aApi.post(`${API}/conversations/${dm}/messages/`, { data: { body } })).ok()).toBe(true);
      const reader = await open(browser, b, lang);
      await reader.goto("/notifications");
      const excerpt = reader.getByTestId("notification-excerpt").filter({ hasText: body }).first();
      await expect(excerpt).toBeVisible({ timeout: 20_000 });
      await expect(excerpt).toHaveAttribute("dir", "auto");
      expect(await excerpt.evaluate((el) => el.tagName)).toBe("BDI");
    });

    test("the chat dock stays out of the admin console", async ({ browser }) => {
      test.setTimeout(120_000);
      const { c } = await sharedAccounts();
      execSync(`docker exec tara-identity-1 python manage.py create_admin ${c.email}`, { stdio: "pipe" });
      const staff = await open(browser, c, lang);
      await staff.goto("/home");
      await expect(staff.getByTestId("chat-dock")).toHaveCount(1);
      for (const path of ["/admin", "/admin/support", "/admin/moderation"]) {
        await staff.goto(path);
        await expect(staff.getByTestId("admin-console").first()).toBeVisible();
        await expect(staff.getByTestId("chat-dock")).toHaveCount(0);
      }
    });
  });
}
