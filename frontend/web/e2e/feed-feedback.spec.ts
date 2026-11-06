import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, expect, type Page, test } from "@playwright/test";

import { API, apiAs, befriend, pageAs, sharedAccounts, unique, useLocale } from "./helpers";

// Tara Intelligence R4 (04 WP 7.3, 07 WP 7.5-B2): the post menu's feedback actions with
// the 06 §10 undo toasts, Mute topic (0 recommended items carrying it afterwards) and
// "Don't recommend this creator" (their followed posts still reach the viewer).

const L = {
  ar: {
    interested: "مهتم",
    notInterested: "مش مهتم",
    more: "ورّيني أكتر زي ده",
    less: "ورّيني أقل زي ده",
    toastInterested: "هنورّيك بوستات زي دي أكتر",
    toastNot: "هنقلل البوستات اللي زي دي",
    toastMute: "مش هنرشّح لك محتوى عن",
    toastHide: "مش هنرشّح لك",
    undo: "تراجع",
  },
  en: {
    interested: "Interested",
    notInterested: "Not interested",
    more: "Show more like this",
    less: "Show less like this",
    toastInterested: "We'll show you more posts like this.",
    toastNot: "We'll show fewer posts like this.",
    toastMute: "We won't recommend",
    toastHide: "We won't recommend",
    undo: "Undo",
  },
} as const;

type FeedItem = { post_id: string; author_id: string; reason: string; topics?: { slug: string }[] };

/** A first page through the API. First pages are throttled (30 a minute, R3): wait out a 429. */
async function feed(api: APIRequestContext, mode: string): Promise<FeedItem[]> {
  for (let attempt = 0; attempt < 4; attempt++) {
    const res = await api.get(`${API}/feed/`, { params: { mode, limit: 100 } });
    if (res.status() === 429) {
      await new Promise((r) => setTimeout(r, (Number(res.headers()["retry-after"]) || 20) * 1000));
      continue;
    }
    expect(res.status()).toBe(200);
    return ((await res.json()) as { data: FeedItem[] }).data;
  }
  throw new Error("first pages still throttled");
}

async function seriousViolations(page: Page, selector: string): Promise<string[]> {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).include(selector).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

async function menuOf(page: Page, postId: string) {
  const card = page.locator(`[data-feed-item="${postId}"]`);
  await expect(card).toBeVisible({ timeout: 30_000 });
  await card.getByTestId("post-menu").click();
  return card.getByTestId("post-menu-panel");
}

/** Click the toast's Undo and wait for the DELETE of that feedback row. */
async function undo(page: Page, label: string) {
  const deleted = page.waitForResponse((r) => /\/feed\/feedback\/[0-9a-f-]{36}\/$/.test(r.url()) && r.request().method() === "DELETE");
  await page.getByTestId("feedback-undo").filter({ hasText: label }).first().click();
  expect((await deleted).status()).toBe(204);
}

for (const lang of ["ar", "en"] as const) {
  test(`feedback actions, undo, mute topic and hide creator (${lang})`, async ({ browser }) => {
    test.setTimeout(300_000);
    const l = L[lang];
    const { a, b } = await sharedAccounts();
    await befriend(a, b);
    const reader = await apiAs(a);
    const writer = await apiAs(b);
    // A post the classifier tags as cooking (lexicon: "recipe", "وصفة" are strong hits).
    const marker = `fb-${lang}-${unique()}`;
    const created = await writer.post(`${API}/posts/`, {
      data: { body: `My pasta recipe with fresh ingredients — وصفة مكرونة ${marker}`, audience: "public", type: "text" },
    });
    expect(created.ok()).toBe(true);
    const postId = ((await created.json()) as { data: { id: string } }).data.id;
    await expect
      .poll(async () => (await feed(reader, "recent")).find((i) => i.post_id === postId)?.topics?.map((t) => t.slug) ?? [], {
        timeout: 90_000,
        intervals: [5_000],
      })
      .toContain("cooking");
    // Earlier runs: the topic unmuted and the creator recommendable again.
    await reader.delete(`${API}/feed/preferences/profile/topic/cooking/`);
    await reader.delete(`${API}/feed/preferences/profile/creator/${b.id}/`);
    expect((await reader.patch(`${API}/feed/preferences/`, { data: { default_mode: "recent" } })).ok()).toBe(true);

    const page = await pageAs(browser, a);
    await useLocale(page, lang);
    await page.goto("/home?mode=recent");
    await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");

    // Interested: a toast with the copy, and Undo deletes that exact row.
    let panel = await menuOf(page, postId);
    await expect(panel.getByTestId("menu-feedback")).toBeVisible();
    // The panel scrolls inside itself (max 70vh): bring the new group on screen for axe.
    await panel.getByTestId("menu-feedback").scrollIntoViewIfNeeded();
    await page.waitForTimeout(400); // the pop-in animation has finished
    expect(await seriousViolations(page, '[data-testid="menu-feedback"]')).toEqual([]);
    // RTL: the panel opens from the end side and its rows start at the start side.
    const box = await panel.boundingBox();
    const cardBox = await page.locator(`[data-feed-item="${postId}"]`).boundingBox();
    if (lang === "ar") expect(box!.x).toBeLessThan(cardBox!.x + cardBox!.width / 2);
    else expect(box!.x + box!.width).toBeGreaterThan(cardBox!.x + cardBox!.width / 2);
    const posted = page.waitForResponse((r) => r.url().endsWith("/feed/feedback/") && r.request().method() === "POST");
    await panel.getByTestId("menu-interested").click();
    expect([200, 201]).toContain((await posted).status());
    await expect(page.getByText(l.toastInterested)).toBeVisible();
    await undo(page, l.undo);

    // More and Less: each confirmed and undoable.
    for (const id of ["menu-more-like", "menu-less-like"]) {
      panel = await menuOf(page, postId);
      await panel.getByTestId(id).click();
      await undo(page, l.undo);
    }

    // Not interested: the card leaves at once and comes back on Undo.
    panel = await menuOf(page, postId);
    await panel.getByTestId("menu-not-interested").click();
    await expect(page.getByText(l.toastNot)).toBeVisible();
    await expect(page.locator(`[data-feed-item="${postId}"]`)).toBeHidden();
    await undo(page, l.undo);
    await expect(page.locator(`[data-feed-item="${postId}"]`)).toBeVisible();

    // Mute topic: the item's topics are offered; afterwards no recommended item carries it.
    panel = await menuOf(page, postId);
    await panel.getByTestId("menu-mute-topic-cooking").click();
    await expect(page.getByText(l.toastMute).first()).toBeVisible();
    const profile = await reader.get(`${API}/feed/preferences/profile/`);
    const muted = ((await profile.json()) as { data: { muted_topics: { slug: string }[] } }).data.muted_topics.map((t) => t.slug);
    expect(muted).toContain("cooking");
    const recommended = (await feed(reader, "for_you")).filter((i) => i.reason.startsWith("rec_") && i.topics?.some((t) => t.slug === "cooking"));
    expect(recommended).toEqual([]);
    // The connection's own post is still there (demoted, never removed).
    expect((await feed(reader, "recent")).map((i) => i.post_id)).toContain(postId);
    await undo(page, l.undo);

    // Don't recommend this creator, from the profile menu: followed posts still arrive.
    await page.goto(`/u/id/${b.id}`);
    await page.getByTestId("person-actions").first().click();
    const hide = page.waitForResponse((r) => r.url().endsWith("/feed/feedback/") && r.request().method() === "POST");
    await page.getByTestId("person-hide-creator").click();
    expect([200, 201]).toContain((await hide).status());
    await expect(page.getByText(l.toastHide).first()).toBeVisible();
    const hiddenList = ((await (await reader.get(`${API}/feed/preferences/profile/`)).json()) as { data: { hidden_creators: { account_id: string }[] } }).data
      .hidden_creators.map((h) => h.account_id);
    expect(hiddenList).toContain(b.id);
    const items = await feed(reader, "recent");
    expect(items.map((i) => i.post_id)).toContain(postId);
    expect((await feed(reader, "for_you")).filter((i) => i.reason.startsWith("rec_") && i.author_id === b.id)).toEqual([]);
    // Graph drops them from people suggestions (they are a friend here, so never suggested anyway).
    const people = ((await (await reader.get(`${API}/social/suggestions/`, { params: { limit: 30 } })).json()) as { data: { results: { account_id: string }[] } }).data.results;
    expect(people.map((p) => p.account_id)).not.toContain(b.id);
    await undo(page, l.undo);
    await expect
      .poll(async () => (((await (await reader.get(`${API}/feed/preferences/profile/`)).json()) as { data: { hidden_creators: { account_id: string }[] } }).data.hidden_creators.map((h) => h.account_id)))
      .not.toContain(b.id);

    await reader.dispose();
    await writer.dispose();
    await page.context().close();
  });
}
