import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, type Browser, type Page, expect, request, test } from "@playwright/test";

import { type Account, API, apiAs, befriend, pageAs, signupData, unique, useLocale, verificationToken } from "./helpers";

// Wave 2D: "People you may know" and "Suggested pages" in the right column, and
// mute (graph emits relationship.muted, feed drops the author's posts).
// Every test uses fresh accounts, so dismissals and requests never leak into
// the shared accounts other specs rely on.

const DESKTOP = { width: 1440, height: 900 };

const LABELS = {
  ar: { people: "أشخاص قد تعرفهم", pages: "صفحات مقترحة", add: "إضافة صديق", sent: "تم إرسال الطلب", follow: /^متابعة /, followed: "تتابعها" },
  en: { people: "People you may know", pages: "Suggested pages", add: "Add friend", sent: "Request sent", follow: /^Follow /, followed: "Following" },
} as const;

async function freshAccount(first: string): Promise<Account> {
  const api = await request.newContext();
  try {
    const tag = unique();
    const handle = `e2e_2d_${tag}`;
    const email = `${handle}@example.com`;
    const res = await api.post(`${API}/auth/register/`, { data: signupData(email, handle, first, tag) });
    expect(res.status(), await res.text()).toBe(201);
    const token = await verificationToken(api, email);
    expect((await api.post(`${API}/auth/verify-email/`, { data: { token } })).ok()).toBe(true);
    const account = { email, handle, name: `${first} ${tag}`, id: (await res.json()).data.account_id };
    // Profile creates the profile from account.registered: wait for it, so the
    // widget's names resolve on the first lookup.
    const signedIn = await apiAs(account);
    await expect
      .poll(async () => (await signedIn.get(`${API}/users/id/${account.id}/`)).status(), { timeout: 30_000 })
      .toBe(200);
    await signedIn.dispose();
    return account;
  } finally {
    await api.dispose();
  }
}

async function openHome(browser: Browser, account: Account, lang: "ar" | "en"): Promise<Page> {
  const page = await pageAs(browser, account);
  await useLocale(page, lang);
  await page.setViewportSize(DESKTOP);
  await page.goto("/home");
  await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
  return page;
}

async function seriousA11y(page: Page, selector: string): Promise<string[]> {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).include(selector).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

async function incomingFrom(api: APIRequestContext, senderId: string): Promise<boolean> {
  const rows = (await (await api.get(`${API}/friends/requests/`)).json()).data as { requested_by: string }[];
  return rows.some((r) => r.requested_by === senderId);
}

for (const lang of ["ar", "en"] as const) {
  test(`[${lang}] send a friend request and dismiss from "People you may know"`, async ({ browser }) => {
    const l = LABELS[lang];
    const [me, bridge, wanted, unwanted] = await Promise.all([
      freshAccount("Mona"),
      freshAccount("Bassem"),
      freshAccount("Karim"),
      freshAccount("Hala"),
    ]);
    await befriend(me, bridge);
    await befriend(wanted, bridge);
    await befriend(unwanted, bridge);

    const page = await openHome(browser, me, lang);
    const widget = page.getByTestId("rail-people");
    await expect(widget.getByRole("heading", { name: l.people })).toBeVisible();
    const row = widget.locator(`[data-account-id="${wanted.id}"]`);
    await expect(row).toContainText(wanted.name);
    // Only the count of mutual friends, never who they are.
    await expect(row.getByTestId("rail-person-mutual")).toHaveText(lang === "ar" ? "صديق مشترك واحد" : "1 mutual friend");
    await expect(widget).not.toContainText(bridge.name);

    expect(await seriousA11y(page, '[data-testid="rail-people"]')).toEqual([]);

    await row.getByRole("button", { name: l.add }).click();
    await expect(row.getByRole("status")).toHaveText(l.sent);
    const wantedApi = await apiAs(wanted);
    expect(await incomingFrom(wantedApi, me.id)).toBe(true);

    const other = widget.locator(`[data-account-id="${unwanted.id}"]`);
    await other.getByTestId("rail-person-dismiss").click();
    await expect(other).toHaveCount(0);

    // After a reload: the requested one has a pending request and the
    // dismissed one stays dismissed, so neither is suggested again.
    await page.reload();
    await expect(page.getByTestId("right-rail")).toBeVisible();
    await page.waitForLoadState("networkidle").catch(() => {});
    await expect(page.locator(`[data-testid="rail-person"][data-account-id="${wanted.id}"]`)).toHaveCount(0);
    await expect(page.locator(`[data-testid="rail-person"][data-account-id="${unwanted.id}"]`)).toHaveCount(0);
    await wantedApi.dispose();
    await page.context().close();
  });

  test(`[${lang}] follow a suggested page from the right column`, async ({ browser }) => {
    test.setTimeout(120_000);
    const l = LABELS[lang];
    const [owner, me] = await Promise.all([freshAccount("Samir"), freshAccount("Nour")]);
    const ownerApi = await apiAs(owner);
    const handle = `e2e2d${unique()}`;
    const created = await ownerApi.post(`${API}/pages/`, { data: { handle, name: `Bakery ${handle}`, category: "Food" } });
    expect(created.ok(), await created.text()).toBe(true);
    const pageId = (await created.json()).data.id as string;
    // Popular enough to be suggested: a burst of followers (graph ranks by them).
    const fans = await Promise.all([freshAccount("Fan"), freshAccount("Fan"), freshAccount("Fan")]);
    for (const fan of fans) {
      const api = await apiAs(fan);
      expect((await api.post(`${API}/follows/${pageId}/`, { data: { target_type: "page" } })).ok()).toBe(true);
      await api.dispose();
    }
    const meApi = await apiAs(me);
    const suggested = async () =>
      ((await (await meApi.get(`${API}/social/suggestions/pages/?limit=30`)).json()).data.results as { page_id: string }[]).map(
        (r) => r.page_id,
      );
    const dismiss = async (id: string) =>
      expect((await meApi.post(`${API}/social/suggestions/${id}/dismiss/`, { data: { target_type: "page" } })).status()).toBe(204);
    // page.created reaches graph asynchronously, and the dev database can hold
    // more than 30 (the API's cap) pages with more followers: this fresh viewer
    // dismisses each page shown until ours is among them.
    await expect
      .poll(
        async () => {
          const ids = await suggested();
          if (ids.includes(pageId)) return true;
          for (const other of ids) await dismiss(other);
          return false;
        },
        { timeout: 45_000 },
      )
      .toBe(true);
    // The widget shows the three most followed: this fresh account dismisses
    // the dev database's more popular pages, so ours is among them.
    for (const other of (await suggested()).slice(0, (await suggested()).indexOf(pageId))) {
      expect((await meApi.post(`${API}/social/suggestions/${other}/dismiss/`, { data: { target_type: "page" } })).status()).toBe(204);
    }
    expect((await suggested())[0]).toBe(pageId);

    const page = await openHome(browser, me, lang);
    const widget = page.getByTestId("rail-pages");
    await expect(widget.getByRole("heading", { name: l.pages })).toBeVisible();
    const row = widget.getByTestId("rail-page").filter({ hasText: `Bakery ${handle}` });
    await expect(row).toContainText(lang === "ar" ? "3 متابِعين" : "3 followers");
    expect(await seriousA11y(page, '[data-testid="rail-pages"]')).toEqual([]);
    await row.getByRole("button", { name: l.follow }).click();
    await expect(row.getByRole("status")).toHaveText(l.followed);
    const following = (await (await meApi.get(`${API}/follows/following/`)).json()).data.following as { target_id: string }[];
    expect(following.some((f) => f.target_id === pageId)).toBe(true);
    await meApi.dispose();
    await ownerApi.dispose();
    await page.context().close();
  });

  test(`[${lang}] a muted friend's next post does not reach the muter's feed`, async ({ browser }) => {
    const [me, muted, control] = await Promise.all([freshAccount("Rania"), freshAccount("Tamer"), freshAccount("Ola")]);
    await befriend(me, muted);
    await befriend(me, control);
    const meApi = await apiAs(me);
    const mutedApi = await apiAs(muted);
    const unread = async () => (await (await mutedApi.get(`${API}/notifications/unread-count/`)).json()).data.unread as number;
    // Notifications from befriending arrive asynchronously: wait until the count settles.
    let unreadBefore = -1;
    for (let i = 0; i < 10; i++) {
      const now = await unread();
      if (now === unreadBefore) break;
      unreadBefore = now;
      await new Promise((r) => setTimeout(r, 1500));
    }
    expect((await meApi.post(`${API}/social/mutes/${muted.id}/`)).status()).toBe(204);
    const mutes = (await (await meApi.get(`${API}/social/mutes/`)).json()).data.muted as string[];
    expect(mutes).toEqual([muted.id]);

    const tag = unique();
    expect((await mutedApi.post(`${API}/posts/`, { data: { body: `muted ${tag}`, audience: "friends", type: "text" } })).ok()).toBe(true);
    expect((await (await apiAs(control)).post(`${API}/posts/`, { data: { body: `control ${tag}`, audience: "friends", type: "text" } })).ok()).toBe(true);

    const page = await openHome(browser, me, lang);
    // The control post, written after the muted one, proves fan-out has run.
    // The mute reaches feed through graph's outbox, a separate pipeline from the
    // posts' fan-out, so wait until both have landed: control shown, muted not.
    await expect
      .poll(
        async () => {
          await page.goto("/home");
          await page.locator("article").first().waitFor({ timeout: 10_000 }).catch(() => {});
          const control = await page.locator("article").filter({ hasText: `control ${tag}` }).count();
          const mutedShown = await page.locator("article").filter({ hasText: `muted ${tag}` }).count();
          return `${control}/${mutedShown}`;
        },
        { timeout: 45_000 },
      )
      .toBe("1/0");

    // The muted side is never told: nothing new arrived for them.
    expect(await unread()).toEqual(unreadBefore);

    // Unmuting brings their posts back.
    expect((await meApi.delete(`${API}/social/mutes/${muted.id}/`)).status()).toBe(204);
    await expect
      .poll(
        async () => {
          await page.goto("/home");
          await page.locator("article").first().waitFor({ timeout: 10_000 }).catch(() => {});
          return page.locator("article").filter({ hasText: `muted ${tag}` }).count();
        },
        { timeout: 45_000 },
      )
      .toBe(1);
    await meApi.dispose();
    await mutedApi.dispose();
    await page.context().close();
  });
}
