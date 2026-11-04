import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, type Page, expect, test } from "@playwright/test";

import { type Account, API, apiAs, expectNoUuid, pageAs, sharedAccounts, unique, useLocale } from "./helpers";

// Unified search v2 (roadmap 1.15): Arabic normalisation, the top-bar dropdown
// (keyboard, recent searches), the results page tabs, people actions, axe.
// Arabic (RTL) is the default locale; the last test runs the page in English.

/** Indexing goes through the event bus, so wait until search returns the hit. */
async function waitForHit(api: APIRequestContext, q: string, type: string, id: string) {
  await expect
    .poll(
      async () => {
        const res = await api.get(`${API}/search/`, { params: { q, type } });
        if (!res.ok()) return "";
        const rows = (await res.json()).data.results as { id: string }[];
        return rows.some((r) => r.id === id) ? "found" : "";
      },
      { timeout: 30_000 },
    )
    .toBe("found");
}

/** No friendship and no pending request between the two, either way. */
async function strangers(one: Account, other: Account) {
  const a = await apiAs(one);
  const b = await apiAs(other);
  await a.delete(`${API}/friends/${other.id}/`);
  for (const [client, them] of [[a, other], [b, one]] as const) {
    for (const direction of ["incoming", "outgoing"]) {
      const res = await client.get(`${API}/friends/requests/`, { params: { direction } });
      const rows = ((await res.json()).data ?? []) as { id: string; account_low_id: string; account_high_id: string }[];
      for (const row of rows.filter((r) => r.account_low_id === them.id || r.account_high_id === them.id)) {
        await client.post(`${API}/friends/requests/${row.id}/reject/`);
      }
    }
  }
  await a.dispose();
  await b.dispose();
}

async function seriousViolations(page: Page, selector: string) {
  const result = await new AxeBuilder({ page }).include(selector).withTags(["wcag2a", "wcag2aa"]).analyze();
  return result.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id);
}

async function publicPost(account: Account, body: string): Promise<string> {
  const api = await apiAs(account);
  const res = await api.post(`${API}/posts/`, { data: { body, audience: "public", type: "text" } });
  expect(res.ok(), await res.text()).toBe(true);
  const id = (await res.json()).data.id as string;
  await api.dispose();
  return id;
}

test("Arabic spelling variants find the post, and the results page tabs work", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const marker = unique();
  const postId = await publicPost(a, `رحلة إلى الإسكندرية ${marker}`);
  // The query is typed without hamza and with ha for ta-marbuta.
  const query = `اسكندريه ${marker}`;
  const viewer = await apiAs(b);
  await waitForHit(viewer, query, "posts", postId);

  // A friends-only post with the same marker is never found.
  const hidden = await apiAs(a);
  await hidden.post(`${API}/posts/`, { data: { body: `سرّي ${marker}`, audience: "friends", type: "text" } });
  await hidden.dispose();

  const page = await pageAs(browser, b);
  await page.goto(`/search?q=${encodeURIComponent(query)}`);
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { name: `نتائج البحث عن "${query}"` })).toBeVisible();

  const tabs = page.getByRole("navigation", { name: "فئات البحث" });
  await expect(tabs.getByRole("link", { name: "الكل" })).toHaveAttribute("aria-current", "page");
  for (const missing of ["فيديو", "ريلز", "وظائف", "شركات"]) {
    await expect(tabs.getByRole("link", { name: missing })).toHaveCount(0);
  }
  await tabs.getByRole("link", { name: "منشورات" }).click();
  await expect(page).toHaveURL(/type=posts/);
  await expect(page.locator("article").filter({ hasText: marker })).toHaveCount(1);
  await expect(page.locator("article").filter({ hasText: "سرّي" })).toHaveCount(0);

  // Contextual filters: the posts tab offers a date filter, people do not.
  await expect(page.getByLabel("التاريخ")).toBeVisible();
  await tabs.getByRole("link", { name: "أشخاص" }).click();
  await expect(page).toHaveURL(/type=people/);
  await expect(page.getByLabel("التاريخ")).toHaveCount(0);

  await tabs.getByRole("link", { name: "منشورات" }).click();
  await expect(page.locator("article").filter({ hasText: marker })).toBeVisible();
  expect(await seriousViolations(page, "main")).toEqual([]);
  await expectNoUuid(page);
  await viewer.dispose();
});

test("the top-bar dropdown: keyboard to a person, Add friend, recent searches and clear", async ({ browser }) => {
  const { b, c } = await sharedAccounts();
  await strangers(b, c);
  const viewer = await apiAs(b);
  await waitForHit(viewer, c.handle, "people", c.id);

  const page = await pageAs(browser, b);
  await page.goto("/home");
  const field = page.getByRole("combobox", { name: "بحث" });
  await field.fill(c.handle);
  const panel = page.getByTestId("global-search-panel");
  const person = panel.getByRole("option").filter({ hasText: c.name });
  await expect(person).toBeVisible();
  await expect(panel.getByRole("group", { name: "أشخاص" })).toBeVisible();
  expect(await seriousViolations(page, "[data-testid=global-search-panel]")).toEqual([]);

  // ArrowDown selects the first row (people come first); Escape closes and keeps focus.
  await field.press("ArrowDown");
  await expect(panel.getByRole("option").first()).toHaveAttribute("aria-selected", "true");
  await expect(field).toHaveAttribute("aria-activedescendant", "gs-option-0");
  await field.press("Escape");
  await expect(field).toHaveAttribute("aria-expanded", "false");
  await expect(field).toBeFocused();

  // Open again, pick the person with the keyboard.
  await field.press("ArrowDown");
  await expect(person).toBeVisible();
  await field.press("ArrowDown");
  await field.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/u/id/${c.id}$`));

  // A submitted query lands on the results page, and the person card adds a friend.
  await field.fill(c.handle);
  await field.press("Enter");
  await expect(page).toHaveURL(/\/search\?q=/);
  const card = page.getByTestId("person-result").filter({ hasText: c.name });
  await expect(card).toBeVisible();
  await expect(card.getByText(`@${c.handle}`)).toBeVisible();
  await card.getByRole("button", { name: "إضافة صديق" }).click();
  await expect(card.getByRole("button", { name: "تم إرسال الطلب" })).toBeDisabled();
  await expect
    .poll(async () => {
      const rows = (await (await viewer.get(`${API}/friends/requests/`, { params: { direction: "outgoing" } })).json()).data as {
        account_low_id: string;
        account_high_id: string;
      }[];
      return rows.some((r) => r.account_low_id === c.id || r.account_high_id === c.id);
    })
    .toBe(true);

  // Recent searches live on the server: the person and the query are listed, then cleared.
  await field.fill("");
  await field.focus();
  await expect(panel.getByRole("option").filter({ hasText: c.name }).first()).toBeVisible();
  // A fresh page load (away from /search, whose query fills the field) reads the
  // history back from the server.
  await page.goto("/home");
  await expect(page.getByRole("combobox", { name: "بحث" })).toHaveValue("");
  await page.getByRole("combobox", { name: "بحث" }).click();
  await expect(panel.getByRole("option").filter({ hasText: c.name }).first()).toBeVisible();
  await panel.getByRole("button", { name: "مسح السجل" }).click();
  await expect(panel.getByText("لا عمليات بحث أخيرة.")).toBeVisible();
  const recent = (await (await viewer.get(`${API}/search/recent/`)).json()).data as unknown[];
  expect(recent).toEqual([]);

  await strangers(b, c);
  await viewer.dispose();
});

test("the results page in English is left-to-right with English tabs", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const marker = unique();
  const postId = await publicPost(a, `Visiting Alexandria ${marker}`);
  const viewer = await apiAs(b);
  await waitForHit(viewer, `alexandria ${marker}`, "posts", postId);
  await viewer.dispose();

  const page = await pageAs(browser, b);
  await useLocale(page, "en");
  await page.goto(`/search?q=${encodeURIComponent(`ALEXANDRIA ${marker}`)}&type=posts`);
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  const tabs = page.getByRole("navigation", { name: "Search categories" });
  await expect(tabs.getByRole("link", { name: "Posts" })).toHaveAttribute("aria-current", "page");
  await expect(page.locator("article").filter({ hasText: marker })).toBeVisible();
  const width = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(width).toBeLessThanOrEqual(0);
  expect(await seriousViolations(page, "main")).toEqual([]);
});

test("no horizontal overflow on a phone, and search opens from the bar icon", async ({ browser }) => {
  const { b } = await sharedAccounts();
  const page = await pageAs(browser, b);
  await page.setViewportSize({ width: 375, height: 760 });
  await page.goto("/home");
  await page.getByRole("link", { name: "فتح البحث" }).click();
  await expect(page).toHaveURL(/\/search$/);
  // The phone's search screen uses the same live field as the top bar (T4).
  await page.getByTestId("search-mobile-field").getByRole("combobox", { name: "بحث" }).fill("تارا");
  await page.getByTestId("search-mobile-field").getByRole("combobox", { name: "بحث" }).press("Enter");
  await expect(page).toHaveURL(/q=/);
  await expect(page.getByRole("navigation", { name: "فئات البحث" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
