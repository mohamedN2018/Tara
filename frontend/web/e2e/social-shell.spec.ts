import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, type Page, expect, request, test } from "@playwright/test";

import {
  type Account,
  API,
  apiAs,
  befriend,
  pageAs,
  sharedAccounts,
  signupData,
  unfriend,
  unique,
  useLocale,
  verificationToken,
} from "./helpers";

// Wave 2, social shell: the top bar's Video tab is in shell-topbar.spec.ts.
// Here: Friends opens on Home (requests + People you may know photo cards),
// Friends > Birthdays and the right column's Birthdays card (identity's
// birthday audience respected), the groups Join / View group buttons and the
// side panel's search and "last active", and the notifications dropdown's
// All / Unread chips, New / Earlier sections and "See previous". Arabic (RTL)
// and English.

const DESKTOP = { width: 1440, height: 900 };

async function seriousA11y(page: Page, selector: string): Promise<string[]> {
  const result = await new AxeBuilder({ page }).include(selector).withTags(["wcag2a", "wcag2aa"]).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

/** Leave `from` with a pending request to `to` (clearing anything in the way first). */
async function pendingRequest(fromApi: APIRequestContext, toApi: APIRequestContext, from: Account, to: Account) {
  await unfriend(from, to);
  type Row = { id: string; requested_by: string };
  const fromIncoming = (await (await fromApi.get(`${API}/friends/requests/`)).json()).data as Row[];
  for (const row of fromIncoming.filter((r) => r.requested_by === to.id)) {
    await fromApi.post(`${API}/friends/requests/${row.id}/reject/`);
  }
  const toIncoming = (await (await toApi.get(`${API}/friends/requests/`)).json()).data as Row[];
  if (!toIncoming.some((r) => r.requested_by === from.id)) {
    const res = await fromApi.post(`${API}/friends/requests/`, { data: { to_user_id: from.id === to.id ? "" : to.id } });
    expect([200, 201, 409]).toContain(res.status());
  }
  return async () => {
    const rows = (await (await toApi.get(`${API}/friends/requests/`)).json()).data as Row[];
    for (const row of rows.filter((r) => r.requested_by === from.id)) await toApi.post(`${API}/friends/requests/${row.id}/reject/`);
  };
}

/** A new account born on today's day and month (a fresh one: the shared accounts' birthdays are fixed). */
async function birthdayAccount(): Promise<Account> {
  const api = await request.newContext();
  try {
    const tag = unique();
    const handle = `e2e_bday_${tag}`;
    const email = `${handle}@example.com`;
    const now = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    const dob = `1995-${pad(now.getMonth() + 1)}-${pad(now.getDate() === 29 && now.getMonth() === 1 ? 28 : now.getDate())}`;
    const res = await api.post(`${API}/auth/register/`, { data: signupData(email, handle, "Nour", tag, { date_of_birth: dob }) });
    expect(res.status(), await res.text()).toBe(201);
    const token = await verificationToken(api, email).catch(() => "");
    if (token) await api.post(`${API}/auth/verify-email/`, { data: { token } });
    return { email, handle, name: `Nour ${tag}`, id: (await res.json()).data.account_id };
  } finally {
    await api.dispose();
  }
}

for (const lang of ["ar", "en"] as const) {
  test(`Friends opens on Home with requests and People you may know (${lang})`, async ({ browser }) => {
    const { a, c } = await sharedAccounts();
    const aApi = await apiAs(a);
    const cApi = await apiAs(c);
    const cleanup = await pendingRequest(cApi, aApi, c, a);
    const page = await pageAs(browser, a);
    if (lang === "en") await useLocale(page, "en");
    await page.setViewportSize(DESKTOP);
    try {
      await page.goto("/friends");
      await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
      await expect(page.getByTestId("friends-tab-home")).toHaveAttribute("aria-current", "page");
      const requests = page.getByTestId("friends-home-requests");
      await expect(requests.getByRole("heading", { name: lang === "ar" ? /طلبات الصداقة/ : /Friend requests/ })).toBeVisible();
      const card = requests.getByTestId("friend-request-card").filter({ hasText: c.name });
      await expect(card).toBeVisible();
      // Photo cards: the picture spans the card's width.
      const photo = await card.getByTestId("person-photo").boundingBox();
      const box = await card.boundingBox();
      expect(Math.round(photo!.width)).toBeGreaterThanOrEqual(Math.round(box!.width) - 2);
      await expect(page.getByTestId("friends-home-pymk").getByRole("heading", { name: lang === "ar" ? "أشخاص قد تعرفهم" : "People you may know" })).toBeVisible();
      expect(await seriousA11y(page, "main")).toEqual([]);

      await page.getByTestId("friends-home-requests-all").click();
      await expect(page).toHaveURL(/tab=requests/);
      await expect(page.getByTestId("friends-tab-requests")).toHaveAttribute("aria-current", "page");
    } finally {
      await cleanup();
      await page.context().close();
    }
  });
}

test("Birthdays: a friend born today shows in the right column and in Friends > Birthdays, until they hide it", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const friend = await birthdayAccount();
  await befriend(friend, a);
  const friendApi = await apiAs(friend);
  const page = await pageAs(browser, a);
  await page.setViewportSize(DESKTOP);
  try {
    await page.goto("/home");
    const card = page.getByTestId("rail-birthdays");
    await expect(card).toBeVisible();
    await expect(card.getByTestId("rail-birthdays-link")).toContainText("عيد ميلاد");
    await card.getByTestId("rail-birthdays-link").click();
    await expect(page).toHaveURL(/\/friends\?tab=birthdays$/);
    const today = page.getByTestId("birthdays-today");
    const row = today.getByTestId("birthday-row").filter({ hasText: friend.name });
    await expect(row).toBeVisible();
    await expect(row).toContainText("اليوم");
    await expect(row.locator("bdi").first()).toHaveText(friend.name);
    expect(await seriousA11y(page, "[data-testid=friends-birthdays]")).toEqual([]);

    // English reads left to right with the same row.
    await useLocale(page, "en");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
    await expect(page.getByTestId("birthdays-today").getByRole("heading", { name: "Today's birthdays" })).toBeVisible();
    await expect(page.getByTestId("birthdays-today").getByTestId("birthday-row").filter({ hasText: friend.name })).toContainText("Today");

    // "Only me": the birthday is gone from both places (identity decides, not the page).
    expect((await friendApi.patch(`${API}/me/`, { data: { birthday_visibility: "only_me" } })).ok()).toBe(true);
    await page.reload();
    await expect(page.getByTestId("friends-birthdays")).toBeVisible();
    await expect(page.getByTestId("birthday-row").filter({ hasText: friend.name })).toHaveCount(0);
    const rows = (await (await (await apiAs(a)).get(`${API}/me/birthdays/`)).json()).data.results as { account_id: string }[];
    expect(rows.map((r) => r.account_id)).not.toContain(friend.id);
  } finally {
    await unfriend(friend, a);
    await page.context().close();
  }
});

test("Birthdays never reach a stranger, and the endpoint needs sign-in", async () => {
  const { c } = await sharedAccounts();
  const stranger = await birthdayAccount();
  const rows = (await (await (await apiAs(c)).get(`${API}/me/birthdays/`)).json()).data.results as { account_id: string }[];
  expect(rows.map((r) => r.account_id)).not.toContain(stranger.id);
  const anon = await request.newContext();
  expect((await anon.get(`${API}/me/birthdays/`)).status()).toBe(401);
  await anon.dispose();
});

for (const lang of ["ar", "en"] as const) {
  test(`groups: Join from Discover, View group from Your groups, rail search and last active (${lang})`, async ({ browser }) => {
    const { a, c } = await sharedAccounts();
    const ownerApi = await apiAs(a);
    const memberApi = await apiAs(c);
    const tag = unique();
    const handle = `shell_${tag}`;
    const name = `Shell ${tag}`;
    const made = await ownerApi.post(`${API}/groups/`, {
      data: { name, handle, description: "", category: "general", privacy: "public", membership_approval: false, post_approval: false },
    });
    expect(made.status(), await made.text()).toBe(201);
    const groupId = (await made.json()).data.id as string;
    expect((await ownerApi.post(`${API}/posts/`, { data: { body: `hello ${tag}`, group_id: groupId, type: "text" } })).ok()).toBe(true);

    const owner = await pageAs(browser, a);
    const member = await pageAs(browser, c);
    for (const p of [owner, member]) {
      if (lang === "en") await useLocale(p, "en");
      await p.setViewportSize(DESKTOP);
    }
    try {
      // The owner's side panel: searchable, with the group's last post time.
      await owner.goto("/groups");
      const rail = owner.getByTestId("groups-rail");
      await rail.getByTestId("groups-rail-search").fill(tag);
      const item = rail.getByTestId("groups-rail-item");
      await expect(item).toHaveCount(1);
      await expect(item).toContainText(name);
      await expect(item.getByTestId("groups-rail-activity")).toContainText(lang === "ar" ? "آخر نشاط" : "Last active");
      await rail.getByTestId("groups-rail-search").fill(`zz${tag}`);
      await expect(rail.getByRole("status")).toBeVisible();

      // The member finds it in Discover and joins from the card.
      const browsed = member.waitForResponse((r) => r.url().includes("scope=discover"));
      await member.goto("/groups?tab=discover");
      await browsed;
      const searched = member.waitForResponse((r) => r.url().includes("scope=discover") && r.url().includes(`q=${tag}`));
      await member.locator("#groups-panel").getByRole("searchbox").fill(tag);
      await searched;
      const card = member.getByTestId("groups-list-discover").locator("article").filter({ hasText: name });
      await expect(card).toBeVisible();
      await card.getByRole("button", { name: lang === "ar" ? "انضم إلى المجموعة" : "Join group" }).click();
      // The card turns into the member's menu in place (no reload of the list).
      await expect(card.getByRole("button", { name: lang === "ar" ? /عضو/ : /Joined/ })).toBeVisible();
      expect(await seriousA11y(member, "#groups-panel")).toEqual([]);

      // Your groups: each card opens its group.
      await member.locator("#groups-tab-mine").click();
      const mine = member.getByTestId("groups-list-mine").locator("article").filter({ hasText: name });
      await mine.getByTestId("group-view-link").click();
      await expect(member).toHaveURL(new RegExp(`/groups/${handle}$`));
    } finally {
      await memberApi.post(`${API}/groups/${handle}/leave/`);
      await ownerApi.delete(`${API}/groups/${handle}/`);
      await owner.context().close();
      await member.context().close();
    }
  });
}

for (const lang of ["ar", "en"] as const) {
  test(`notifications dropdown: All / Unread, New / Earlier and See previous (${lang})`, async ({ browser }) => {
    const { a, c } = await sharedAccounts();
    const aApi = await apiAs(a);
    const cApi = await apiAs(c);
    // A fresh friend request: a new, unread notification for a.
    const cleanup = await pendingRequest(cApi, aApi, c, a);
    const page = await pageAs(browser, a);
    if (lang === "en") await useLocale(page, "en");
    await page.setViewportSize(DESKTOP);
    try {
      await page.goto("/home");
      await page.getByRole("button", { name: lang === "ar" ? /الإشعارات/ : /Notifications/ }).first().click();
      const dropdown = page.getByTestId("notif-dropdown");
      await expect(dropdown).toBeVisible();
      const all = dropdown.getByTestId("notif-dropdown-filter-all");
      const unread = dropdown.getByTestId("notif-dropdown-filter-unread");
      await expect(all).toHaveAttribute("aria-pressed", "true");
      await expect(all).toHaveText(lang === "ar" ? "الكل" : "All");
      const fresh = dropdown.getByTestId("notif-dropdown-section-new");
      await expect(fresh.getByRole("heading", { name: lang === "ar" ? "جديدة" : "New" })).toBeVisible();
      await expect(fresh.locator("li").first()).toBeVisible();

      await unread.click();
      await expect(unread).toHaveAttribute("aria-pressed", "true");
      await expect(dropdown.locator("li").first()).toBeVisible();
      await all.click();

      const before = await dropdown.locator("li").count();
      const more = dropdown.getByTestId("notif-dropdown-see-previous");
      if (await more.count()) {
        await expect(more).toHaveText(lang === "ar" ? "عرض الإشعارات السابقة" : "See previous notifications");
        await more.click();
        await expect.poll(() => dropdown.locator("li").count()).toBeGreaterThan(before);
      }
      expect(await seriousA11y(page, "[data-testid=notif-dropdown]")).toEqual([]);
    } finally {
      await cleanup();
      await page.context().close();
    }
  });
}
