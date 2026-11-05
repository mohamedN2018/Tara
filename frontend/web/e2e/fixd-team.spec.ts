// Fix track D: "who can message you" (Settings > Privacy, enforced by chat),
// Contact support -> the support inbox in the admin console, and Message on a
// Page -> the page's inbox, in Arabic and English, with no serious axe issues.
import { execSync } from "node:child_process";

import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, type Browser, expect, type Page, request, test } from "@playwright/test";

import { type Account, API, apiAs, befriend, pageAs, sharedAccounts, signupData, unique, useLocale, verificationToken } from "./helpers";

const LANGS = ["ar", "en"] as const;
type Lang = (typeof LANGS)[number];
const SUPPORT = { ar: "دعم تارا", en: "Tara Support" };

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

/** A brand-new account nobody is friends with. */
async function stranger(api: APIRequestContext): Promise<Account | null> {
  const tag = unique();
  const handle = `e2e_fd_${tag}`;
  const email = `${handle}@example.com`;
  const res = await api.post(`${API}/auth/register/`, { data: signupData(email, handle, "Nour", tag) });
  if (res.status() !== 201) return null; // registration is rate limited per hour
  const token = await verificationToken(api, email);
  await api.post(`${API}/auth/verify-email/`, { data: { token } });
  const { data } = await res.json();
  return { email, handle, name: `Nour ${tag}`, id: data.account_id };
}

async function setting(api: APIRequestContext): Promise<string> {
  return (await (await api.get(`${API}/conversations/settings/`)).json()).data.message_from;
}

for (const lang of LANGS) {
  test.describe(`chat teams and privacy (${lang})`, () => {
    test("who can message you: Settings > Privacy, enforced on a stranger's first message", async ({ browser }) => {
      test.setTimeout(180_000);
      const { a, b } = await sharedAccounts();
      await befriend(a, b);
      const anon = await request.newContext();
      const newcomer = await stranger(anon);
      await anon.dispose();
      const bApi = await apiAs(b);
      const page = await open(browser, b, lang);
      try {
        await page.goto("/settings");
        await page.locator('a[href="/settings/privacy"]').first().click();
        const box = page.getByTestId("message-privacy");
        await expect(box).toBeVisible();
        await expect(box.getByTestId("message-from-everyone").locator("input")).toBeChecked();
        await axe(page, '[data-testid="message-privacy"]');

        await box.getByTestId("message-from-friends").click();
        await expect(box.getByTestId("message-from-friends").locator("input")).toBeChecked();
        await expect.poll(() => setting(bApi)).toBe("friends");

        // A friend still reaches the inbox.
        const aApi = await apiAs(a);
        expect((await aApi.post(`${API}/conversations/`, { data: { type: "dm", other_id: b.id } })).ok()).toBe(true);
        if (newcomer) {
          const nApi = await apiAs(newcomer);
          const refused = await nApi.post(`${API}/conversations/`, { data: { type: "dm", other_id: b.id } });
          expect(refused.status()).toBe(403);
          expect((await refused.json()).error.code).toBe("messaging_restricted");

          // Back to everyone: the stranger's first message waits in message requests.
          await box.getByTestId("message-from-everyone").click();
          await expect.poll(() => setting(bApi)).toBe("everyone");
          const asked = await nApi.post(`${API}/conversations/`, { data: { type: "dm", other_id: b.id } });
          expect(asked.status()).toBe(201);
        }
      } finally {
        await bApi.patch(`${API}/conversations/settings/`, { data: { message_from: "everyone" } });
      }
    });

    test("Contact support -> the support inbox answers as Tara Support", async ({ browser }) => {
      test.setTimeout(180_000);
      const { a, c } = await sharedAccounts();
      execSync(`docker exec tara-identity-1 python manage.py create_admin ${c.email}`, { stdio: "pipe" });

      // The member: Support inbox -> Contact support -> a thread with Tara Support.
      const member = await open(browser, a, lang);
      await member.goto("/home");
      await member.getByTestId("main-menu-button").click();
      await member.getByTestId("menu-item-support").click();
      await expect(member.getByTestId("support-contact")).toBeVisible();
      await axe(member, '[data-testid="support-contact"]');
      await member.getByTestId("support-contact-open").click();
      await expect(member).toHaveURL(/\/messages\/[0-9a-f-]{36}/);
      await expect(member.getByTestId("conversation-title")).toHaveText(SUPPORT[lang]);
      await expect(member.getByTestId("team-thread-hint")).toBeVisible();
      const conversationId = member.url().split("/messages/")[1].split("?")[0];
      const question = `help ${lang} ${unique()}`;
      const aApi = await apiAs(a);
      expect((await aApi.post(`${API}/conversations/${conversationId}/messages/`, { data: { body: question } })).ok()).toBe(true);

      // The member may not read the support inbox: 404.
      expect((await aApi.get(`${API}/conversations/team/`)).status()).toBe(404);

      // Staff: admin console -> Support inbox -> the thread -> reply.
      const staff = await open(browser, c, lang);
      await staff.goto("/admin");
      await staff.getByTestId("admin-console").getByTestId("admin-nav-support").first().click();
      await expect(staff).toHaveURL(/\/admin\/support/);
      const row = staff.getByTestId("team-row").filter({ hasText: a.name.split(" ")[0] }).first();
      await expect(row).toBeVisible();
      await row.click();
      await expect(staff.getByTestId("team-thread")).toContainText(question);
      await axe(staff, '[data-testid="team-inbox"]');
      const answer = `answer ${lang} ${unique()}`;
      await staff.getByTestId("team-reply").fill(answer);
      await staff.getByTestId("team-send").click();
      await expect(staff.getByTestId("team-message").filter({ hasText: answer })).toBeVisible();

      // The member sees the reply from Tara Support, not from a person.
      const replies = (await (await aApi.get(`${API}/conversations/${conversationId}/messages/`)).json()).data as { body: string; sender_id: string }[];
      const reply = replies.find((m) => m.body === answer);
      expect(reply?.sender_id).not.toBe(c.id);
      await member.reload();
      await expect(member.getByTestId("message-scroller").getByText(answer)).toBeVisible();
    });

    test("Message on a Page -> the page's inbox answers as the Page", async ({ browser }) => {
      test.setTimeout(180_000);
      const { a, b } = await sharedAccounts();
      const tag = `${lang}${unique()}`;
      const handle = `fd_${tag}`;
      const name = `Nile Bakery ${tag}`;
      const ownerApi = await apiAs(a);
      const created = await ownerApi.post(`${API}/pages/`, { data: { handle, name, category: "Bakery" } });
      expect(created.ok(), await created.text()).toBe(true);
      const pageId = (await created.json()).data.id as string;

      // The owner has no "Message" (it is their page) but the page inbox.
      const visitor = await open(browser, b, lang);
      await visitor.goto(`/pages/${handle}`);
      await visitor.getByTestId("page-message").click();
      await expect(visitor).toHaveURL(/\/messages\/[0-9a-f-]{36}/);
      await expect(visitor.getByTestId("conversation-title")).toHaveText(name);
      const conversationId = visitor.url().split("/messages/")[1].split("?")[0];
      const question = `cake ${tag}`;
      const bApi = await apiAs(b);
      expect((await bApi.post(`${API}/conversations/${conversationId}/messages/`, { data: { body: question } })).ok()).toBe(true);
      // Someone off the team gets 404 for the page inbox.
      expect((await bApi.get(`${API}/conversations/team/`, { params: { page_id: pageId } })).status()).toBe(404);

      const owner = await open(browser, a, lang, true);
      await owner.goto(`/pages/${handle}`);
      await expect(owner.getByTestId("page-message")).toHaveCount(0);
      await owner.getByTestId("page-inbox-link").click();
      await expect(owner).toHaveURL(new RegExp(`/pages/id/${pageId}/inbox`));
      await owner.getByTestId("team-row").first().click();
      await expect(owner.getByTestId("team-thread")).toContainText(question);
      await axe(owner, '[data-testid="team-inbox"]');
      const answer = `fresh today ${tag}`;
      await owner.getByTestId("team-reply").fill(answer);
      await owner.getByTestId("team-send").click();
      await expect(owner.getByTestId("team-message").filter({ hasText: answer })).toBeVisible();

      const replies = (await (await bApi.get(`${API}/conversations/${conversationId}/messages/`)).json()).data as { body: string; sender_id: string }[];
      expect(replies.find((m) => m.body === answer)?.sender_id).toBe(pageId);
      await visitor.reload();
      await expect(visitor.getByTestId("message-scroller").getByText(answer)).toBeVisible();
    });
  });
}
