import { type APIRequestContext, type Locator, type Page, expect, test } from "@playwright/test";

import { API, apiAs, pageAs, sharedAccounts, unique, useLocale } from "./helpers";

// Fix round 3, track C.
// 1. Live search follows a page's lifecycle: a page that goes back to draft takes
//    its posts (and their hashtags) out of search for everyone, and publishing it
//    again brings them back.
// 2. A Latin page or group name in the Arabic UI stays at the start edge (right),
//    next to its avatar, in the manager cards, the Discover list, group cards and
//    the group header.

const DESKTOP = { width: 1440, height: 900 };

async function asLang(page: Page, lang: "ar" | "en") {
  await useLocale(page, lang);
  await page.setViewportSize(DESKTOP);
  await page.addInitScript(() => localStorage.setItem("tara.push.dismissed", "1"));
}

async function postHits(api: APIRequestContext, q: string): Promise<string[]> {
  const res = await api.get(`${API}/search/`, { params: { q, type: "posts" } });
  expect(res.ok(), await res.text()).toBe(true);
  return ((await res.json()).data.results as { id: string }[]).map((r) => r.id);
}

async function tagCount(api: APIRequestContext, tag: string): Promise<number> {
  const res = await api.get(`${API}/search/`, { params: { q: `#${tag}`, type: "hashtags" } });
  const rows = (await res.json()).data.results as { tag?: string; post_count?: number }[];
  return rows.find((r) => r.tag === tag)?.post_count ?? 0;
}

/** The name sits on the UI's start edge of its block: right in ar, left in en. */
async function expectStartAligned(block: Locator, lang: "ar" | "en") {
  const outer = (await block.boundingBox())!;
  const name = (await block.locator("bdi").first().boundingBox())!;
  expect(outer && name).toBeTruthy();
  if (lang === "ar") expect(Math.abs(outer.x + outer.width - (name.x + name.width))).toBeLessThanOrEqual(2);
  else expect(Math.abs(outer.x - name.x)).toBeLessThanOrEqual(2);
  expect(await block.getAttribute("dir")).toBeNull();
}

for (const lang of ["ar", "en"] as const) {
  test(`a draft page's posts leave live search and come back (${lang})`, async ({ browser }) => {
    test.setTimeout(180_000);
    const { a, b } = await sharedAccounts();
    const ownerApi = await apiAs(a);
    const visitorApi = await apiAs(b);
    const tag = `${lang}${unique()}`;
    const word = `pagesearch${tag}`;
    const hashtag = `pgtag${tag}`;
    const created = await ownerApi.post(`${API}/pages/`, { data: { handle: `c3s_${tag}`, name: `Search Page ${tag}` } });
    expect(created.ok(), await created.text()).toBe(true);
    const pageId = (await created.json()).data.id as string;
    const posted = await ownerApi.post(`${API}/posts/`, { data: { body: `${word} news #${hashtag}`, page_id: pageId } });
    expect(posted.ok(), await posted.text()).toBe(true);
    const postId = (await posted.json()).data.id as string;
    await expect.poll(() => postHits(visitorApi, word), { timeout: 40_000 }).toContain(postId);
    await expect.poll(() => tagCount(visitorApi, hashtag), { timeout: 40_000 }).toBe(1);

    const visitor = await pageAs(browser, b);
    await asLang(visitor, lang);
    const results = visitor.locator("main article").filter({ hasText: word });
    await visitor.goto(`/search?q=${encodeURIComponent(word)}&type=posts`);
    await expect(results).toBeVisible();

    // Draft: gone from live search (posts tab and hashtag count) for an outsider.
    const draft = await ownerApi.patch(`${API}/pages/id/${pageId}/`, { data: { status: "draft" } });
    expect(draft.ok(), await draft.text()).toBe(true);
    await expect.poll(() => postHits(visitorApi, word), { timeout: 40_000 }).not.toContain(postId);
    await expect.poll(() => tagCount(visitorApi, hashtag), { timeout: 40_000 }).toBe(0);
    await visitor.reload();
    await expect(visitor.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
    await expect(results).toHaveCount(0);

    // Published again: the post is found again.
    const back = await ownerApi.patch(`${API}/pages/id/${pageId}/`, { data: { status: "published" } });
    expect(back.ok(), await back.text()).toBe(true);
    await expect.poll(() => postHits(visitorApi, word), { timeout: 40_000 }).toContain(postId);
    await expect.poll(() => tagCount(visitorApi, hashtag), { timeout: 40_000 }).toBe(1);
    await visitor.reload();
    await expect(results).toBeVisible();

    await visitor.context().close();
    await ownerApi.dispose();
    await visitorApi.dispose();
  });

  test(`Latin page and group names stay on the start edge (${lang})`, async ({ browser }) => {
    test.setTimeout(180_000);
    const { a, b } = await sharedAccounts();
    const ownerApi = await apiAs(a);
    const tag = `${lang}${unique()}`;
    const pageName = `Cairo Jazz ${tag}`;
    const groupName = `Alex Makers ${tag}`;
    const groupHandle = `c3g_${tag}`;
    expect((await ownerApi.post(`${API}/pages/`, { data: { handle: `c3n_${tag}`, name: pageName } })).ok()).toBe(true);
    const made = await ownerApi.post(`${API}/groups/`, { data: { handle: groupHandle, name: groupName } });
    expect(made.ok(), await made.text()).toBe(true);
    await ownerApi.dispose();

    const owner = await pageAs(browser, a);
    await asLang(owner, lang);
    await owner.goto("/pages?tab=manage");
    await expect(owner.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
    const card = owner.getByTestId("page-manage-card").filter({ hasText: pageName });
    await expectStartAligned(card.getByTestId("page-card-name"), lang);

    await owner.goto("/groups?tab=manage");
    const groupCard = owner.getByTestId("groups-list-manage").locator("article", { hasText: groupName });
    await expectStartAligned(groupCard.getByTestId("group-card-name"), lang);

    await owner.goto(`/groups/${groupHandle}`);
    await expectStartAligned(owner.getByTestId("group-name"), lang);
    await owner.context().close();

    const visitor = await pageAs(browser, b);
    await asLang(visitor, lang);
    await visitor.goto("/pages?tab=discover");
    await visitor.getByRole("searchbox").fill(pageName);
    const item = visitor.getByTestId("pages-list-discover").getByTestId("page-list-item").filter({ hasText: pageName });
    await expectStartAligned(item.getByTestId("page-list-name"), lang);
    await visitor.context().close();
  });
}
