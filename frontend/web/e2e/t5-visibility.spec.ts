// T5: every Messenger and notification feature is reachable from navigation
// (clicks, not typed URLs), in Arabic and English, with no serious axe issues.
import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, type Browser, expect, type Page, request, test } from "@playwright/test";

import { type Account, API, apiAs, befriend, dmWith, pageAs, sharedAccounts, signupData, unique, useLocale, verificationToken } from "./helpers";

const SHOTS = process.env.T5_SHOTS ?? "";
const LANGS = ["ar", "en"] as const;
type Lang = (typeof LANGS)[number];

const L = {
  ar: { messages: "الرسائل", newMessage: "رسالة جديدة", archived: "المحادثات المؤرشفة", requests: "طلبات المراسلة", accept: "قبول", info: "معلومات المحادثة", reportMessage: "الإبلاغ عن الرسالة", notifications: "الإشعارات" },
  en: { messages: "Messages", newMessage: "New message", archived: "Archived chats", requests: "Message requests", accept: "Accept", info: "Chat info", reportMessage: "Report message", notifications: "Notifications" },
};

async function open(browser: Browser, who: Account, lang: Lang, mobile = false): Promise<Page> {
  const page = await pageAs(browser, who);
  await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 });
  await useLocale(page, lang);
  return page;
}

async function axe(page: Page, selector: string) {
  await page.waitForTimeout(300); // let pop-in animations finish (contrast is measured on the final colours)
  const result = await new AxeBuilder({ page }).include(selector).withTags(["wcag2a", "wcag2aa"]).analyze();
  const bad = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${v.id}: ${v.nodes[0]?.target}`)).toEqual([]);
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  await page.waitForTimeout(400); // pop-in animations
  await page.screenshot({ path: `${SHOTS}/${name}.png` });
}

/** A brand-new account nobody is friends with (its DM is a message request). */
async function stranger(api: APIRequestContext): Promise<Account | null> {
  const tag = unique();
  const handle = `e2e_t5_${tag}`;
  const email = `${handle}@example.com`;
  const res = await api.post(`${API}/auth/register/`, { data: signupData(email, handle, "Nour", tag) });
  if (res.status() !== 201) return null; // registration is rate limited per hour
  const token = await verificationToken(api, email);
  await api.post(`${API}/auth/verify-email/`, { data: { token } });
  const { data } = await res.json();
  return { email, handle, name: `Nour ${tag}`, id: data.account_id };
}

for (const lang of LANGS) {
  test.describe(`messenger (${lang})`, () => {
    test("top-bar dropdown: list, folders, new message and search", async ({ browser }) => {
      const { a, b } = await sharedAccounts();
      await befriend(a, b);
      const api = await apiAs(a);
      const conv = await dmWith(api, b.id);
      await api.post(`${API}/conversations/${conv}/messages/`, { data: { body: `dropdown ${unique()}` } });

      const page = await open(browser, b, lang);
      await page.goto("/home");
      await page.getByTestId("messenger-button").click();
      const dropdown = page.getByTestId("messenger-dropdown");
      await expect(dropdown).toBeVisible();
      await expect(dropdown.getByTestId("messenger-dropdown-row").first()).toBeVisible();
      await expect(dropdown.getByTestId("conversation-preview").first()).not.toBeEmpty();
      await shot(page, `desktop-${lang}-dropdown`);
      await axe(page, '[data-testid="messenger-dropdown"]');

      // Unread filter (server-side) and back.
      await dropdown.getByTestId("messenger-filter-unread").click();
      await expect(dropdown.getByTestId("messenger-filter-unread")).toHaveAttribute("aria-pressed", "true");
      await dropdown.getByTestId("messenger-filter-all").click();

      // Options -> Archived chats -> the archived folder of the inbox.
      await dropdown.getByTestId("messenger-options").click();
      await dropdown.getByRole("menuitem", { name: L[lang].archived }).click();
      await expect(page).toHaveURL(/\/messages\?folder=archived$/);
      await expect(page.getByTestId("folder-archived")).toHaveAttribute("aria-selected", "true");

      // ...and Message requests.
      await page.getByTestId("messenger-button").click();
      await page.getByTestId("messenger-options").click();
      await page.getByRole("menuitem", { name: L[lang].requests }).click();
      await expect(page).toHaveURL(/folder=requests/);
      await expect(page.getByTestId("folder-requests")).toHaveAttribute("aria-selected", "true");
      await expect(page.getByTestId("folder-hint")).toBeVisible();

      // New message from the dropdown.
      await page.getByTestId("messenger-button").click();
      await page.getByTestId("messenger-new").click();
      const dialog = page.getByTestId("new-message-dialog");
      await expect(dialog).toBeVisible();
      await expect(dialog.getByTestId("new-message-friend").filter({ hasText: a.name })).toBeVisible();
      await axe(page, '[data-testid="new-message-dialog"]');
      await dialog.getByTestId("new-message-friend").filter({ hasText: a.name }).click();
      await dialog.getByTestId("new-message-start").click();
      await expect(page).toHaveURL(new RegExp(`/messages/${conv}$`));

      // Search Messenger opens the inbox search.
      await page.getByTestId("messenger-button").click();
      await page.getByTestId("messenger-search").fill("dropdown");
      await page.getByTestId("messenger-search").press("Enter");
      await expect(page).toHaveURL(/search=1/);
      await expect(page.getByTestId("chat-search")).toBeVisible();
    });

    test("chat info column, row menu, block/report entries and message report", async ({ browser }) => {
      const { a, b } = await sharedAccounts();
      await befriend(a, b);
      const api = await apiAs(a);
      const conv = await dmWith(api, b.id);
      const body = `report me ${unique()}`;
      await api.post(`${API}/conversations/${conv}/messages/`, { data: { body } });

      const page = await open(browser, b, lang);
      await page.goto("/home");
      await page.getByTestId("messenger-button").click();
      await page.getByTestId("messenger-see-all").click();
      await expect(page).toHaveURL(/\/messages$/);
      const row = page.getByTestId("conversation-row").filter({ hasText: a.name }).first();
      await row.getByRole("button").first().click();
      await expect(page).toHaveURL(new RegExp(`/messages/${conv}$`));

      // The info column is open on wide screens.
      const info = page.getByTestId("conversation-info");
      await expect(info).toBeVisible();
      await expect(info.getByTestId("info-block")).toBeVisible();
      await expect(info.getByTestId("info-report")).toBeVisible();
      await info.getByTestId("info-media").click();
      await shot(page, `desktop-${lang}-messages-info`);
      await axe(page, '[data-testid="conversation-info"]');

      // Row menu: block and report the other person are offered.
      await row.hover();
      await row.getByTestId("conversation-row-menu").click();
      await expect(page.getByTestId("row-block")).toBeVisible();
      await page.getByTestId("row-report").click();
      await expect(page.getByTestId("report-dialog")).toBeVisible();
      await page.keyboard.press("Escape");

      // Report a message from its menu.
      const bubble = page.locator("[data-message-id]").filter({ hasText: body }).first();
      await bubble.hover();
      await bubble.getByTestId("message-menu").click();
      await page.getByRole("menuitem", { name: L[lang].reportMessage }).click();
      const dialog = page.getByTestId("message-report-dialog");
      await expect(dialog).toBeVisible();
      await axe(page, '[data-testid="message-report-dialog"]');
      await dialog.locator('input[value="spam"]').check();
      await dialog.getByTestId("message-report-send").click();
      await expect(dialog).toBeHidden();

      // The toggle hides and shows the column.
      await page.getByTestId("conversation-info-toggle").click();
      await expect(info).toBeHidden();
    });

    test("a stranger's first message waits in Message requests until accepted", async ({ browser }) => {
      const { b } = await sharedAccounts();
      const anon = await request.newContext();
      const s = await stranger(anon);
      await anon.dispose();
      test.skip(!s, "registration rate limit reached");
      const api = await apiAs(s!);
      const conv = await dmWith(api, b.id);
      const hello = `hello from a stranger ${unique()}`;
      await api.post(`${API}/conversations/${conv}/messages/`, { data: { body: hello } });

      const page = await open(browser, b, lang);
      await page.goto("/home");
      await page.getByTestId("messenger-button").click();
      await page.getByTestId("messenger-requests-banner").click();
      await expect(page).toHaveURL(/folder=requests/);
      // By the message preview: a brand-new account's name may not be in the directory yet.
      await page.getByTestId("conversation-row").filter({ hasText: hello }).getByRole("button").first().click();
      const banner = page.getByTestId("request-banner");
      await expect(banner).toBeVisible();
      await shot(page, `desktop-${lang}-request`);
      await axe(page, '[data-testid="request-banner"]');
      await banner.getByTestId("request-accept").click();
      await expect(banner).toBeHidden();
      await page.getByTestId("folder-inbox").click();
      await expect(page.getByTestId("conversation-row").filter({ hasText: hello })).toBeVisible();
    });

    test("group chats show who has seen a message", async ({ browser }) => {
      const { a, b, c } = await sharedAccounts();
      await befriend(a, b);
      await befriend(a, c);
      const api = await apiAs(a);
      const res = await api.post(`${API}/conversations/`, { data: { type: "group", title: `T5 ${unique()}`, member_ids: [b.id, c.id] } });
      expect(res.ok()).toBe(true);
      const group = (await res.json()).data.id as string;
      const msg = (await (await api.post(`${API}/conversations/${group}/messages/`, { data: { body: "seen?" } })).json()).data;
      const reader = await apiAs(b);
      await reader.post(`${API}/conversations/${group}/read/`, { data: { up_to_message_id: msg.id } });

      const page = await open(browser, a, lang);
      await page.goto("/home");
      await page.getByTestId("messenger-button").click();
      await page.getByTestId("messenger-see-all").click();
      await page.getByTestId("conversation-row").filter({ hasText: (await res.json()).data.title }).getByRole("button").first().click();
      await expect(page.getByTestId("seen-by").last()).toBeVisible();
      await expect(page.getByTestId("seen-by").last()).toHaveAttribute("aria-label", new RegExp(b.name));
    });

    test("mini chat windows open from the contacts rail and the New message button", async ({ browser }) => {
      const { a, b } = await sharedAccounts();
      await befriend(a, b);
      const page = await open(browser, b, lang);
      await page.goto("/home");
      const contact = page.getByTestId("rail-contact").filter({ hasText: a.name });
      await contact.click();
      const win = page.getByTestId("chat-window");
      await expect(win).toBeVisible();
      await expect(page).toHaveURL(/\/home$/);
      await shot(page, `desktop-${lang}-dock`);
      await axe(page, '[data-testid="chat-dock"]');
      await win.getByTestId("chat-window-minimise").click();
      await expect(page.getByTestId("chat-head")).toBeVisible();
      await page.getByTestId("chat-head").click();
      await expect(win).toBeVisible();
      await win.getByTestId("chat-window-open").click();
      await expect(page).toHaveURL(/\/messages\/[\w-]+$/);
      await page.goBack();
      await page.getByTestId("messenger-fab").click();
      await expect(page.getByTestId("new-message-dialog")).toBeVisible();
    });

    test("notifications: category chips, row menu", async ({ browser }) => {
      const { b } = await sharedAccounts();
      const page = await open(browser, b, lang);
      await page.goto("/home");
      await page.getByRole("button", { name: new RegExp(L[lang].notifications) }).first().click();
      await page.locator(".popover").getByRole("link", { name: lang === "ar" ? "عرض الكل" : "See all" }).click();
      await expect(page).toHaveURL(/\/notifications$/);
      const chips = page.getByTestId("notification-categories");
      await expect(chips).toBeVisible();
      await chips.getByTestId("notification-category-groups").click();
      await expect(chips.getByTestId("notification-category-groups")).toHaveAttribute("aria-pressed", "true");
      await chips.getByTestId("notification-category-groups").click();
      await page.getByTestId("notifications-filter-unread").click();
      await expect(page.getByTestId("notifications-filter-unread")).toHaveAttribute("aria-pressed", "true");
      await page.getByTestId("notifications-filter-all").click();
      const item = page.getByTestId("notification-item").first();
      if (await item.count()) {
        await item.hover();
        await item.getByTestId("notification-menu").click();
        await expect(item.getByTestId("notification-turn-off")).toBeVisible();
        await page.keyboard.press("Escape");
      }
      await shot(page, `desktop-${lang}-notifications`);
      await axe(page, "main");
    });

    test("phones: Messenger in the top bar, folders in the menu", async ({ browser }) => {
      const { b } = await sharedAccounts();
      const page = await open(browser, b, lang, true);
      await page.goto("/home");
      await page.getByTestId("messenger-mobile").click();
      await expect(page).toHaveURL(/\/messages$/);
      await shot(page, `mobile-${lang}-messages`);
      await axe(page, "main");
      await page.goto("/home");
      await page.getByRole("link", { name: lang === "ar" ? "القائمة" : "Menu" }).last().click();
      await expect(page.getByTestId("menu-item-archived")).toBeVisible();
      await page.getByTestId("menu-item-messageRequests").click();
      await expect(page).toHaveURL(/folder=requests/);
      await shot(page, `mobile-${lang}-requests`);
      await page.goto("/home");
      await page.getByRole("link", { name: lang === "ar" ? "القائمة" : "Menu" }).last().click();
      await page.getByTestId("menu-item-notifications").click();
      await expect(page.getByTestId("notification-categories")).toBeVisible();
      await shot(page, `mobile-${lang}-notifications`);
    });
  });
}
