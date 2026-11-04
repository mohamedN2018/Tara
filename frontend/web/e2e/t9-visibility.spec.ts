import { deflateSync } from "node:zlib";

import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { API, apiAs, befriend, dmWith, pageAs, sharedAccounts, unfriend, useLocale } from "./helpers";

// Track T9: stories are reached by clicking through navigation (never a typed
// URL) in Arabic and English, and pass axe: the Home rail and its "Create
// story" card, the viewer (keys follow the reading direction, react, report),
// creating a text story for close friends, the close friends list, the
// author's viewer list, the stories hub and the archive from the main menu,
// a photo story through the media flow, and deleting a story.

const DESKTOP = { width: 1440, height: 900 };

async function axe(page: Page, selector: string): Promise<string[]> {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).include(selector).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

// A real PNG (a brand gradient), so the media pipeline has something to process.
function png(width = 360, height = 640): Buffer {
  const table = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc = (buf: Buffer) => {
    let c = 0xffffffff;
    for (const b of buf) c = table[(c ^ b) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (type: string, data: Buffer) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(type), data]);
    const sum = Buffer.alloc(4);
    sum.writeUInt32BE(crc(body));
    return Buffer.concat([len, body, sum]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 2;
  const rows: number[] = [];
  for (let y = 0; y < height; y++) {
    rows.push(0);
    for (let x = 0; x < width; x++) rows.push(106 + Math.round((149 * y) / height), Math.round((85 * x) / width), 244 - Math.round((28 * y) / height));
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.from(rows))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

for (const lang of ["ar", "en"] as const) {
  test(`stories from navigation (${lang})`, async ({ browser }) => {
    test.setTimeout(240_000);
    const { a, b } = await sharedAccounts();
    await befriend(a, b);
    const apiA = await apiAs(a);
    const apiB = await apiAs(b);
    // b shares a story for friends, so it is in a's rail.
    const text = `T9 ${lang} ${Date.now()}`;
    const made = await apiB.post(`${API}/stories/`, { data: { kind: "text", audience: "friends", text, background: "magenta" } });
    expect(made.status()).toBe(201);
    const bStory = (await made.json()).data.id as string;

    const page = await pageAs(browser, a);
    await useLocale(page, lang);
    await page.setViewportSize(DESKTOP);
    await page.goto("/home");
    await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");

    // 1. The rail on Home: create card first, then b's story.
    const rail = page.getByTestId("stories-rail");
    await expect(rail).toBeVisible();
    await expect(rail.getByTestId("story-create")).toBeVisible();
    const bCard = rail.locator(`[data-testid=story-tray-card][data-author="${b.id}"]`);
    await expect(bCard).toBeVisible();
    expect(await axe(page, "[data-testid=stories-rail]")).toEqual([]);

    // 2. The viewer: b's story plays, a reacts and finds Report.
    await bCard.click();
    const viewer = page.getByTestId("story-viewer");
    await expect(viewer).toBeVisible();
    await page.getByTestId("story-pause").click();
    // Walk to b's new story (b may have older ones from earlier runs) with the reading-direction key.
    const forward = lang === "ar" ? "ArrowLeft" : "ArrowRight";
    for (let i = 0; i < 20 && (await viewer.locator("[data-story]").getAttribute("data-story")) !== bStory; i++) {
      await page.keyboard.press(forward);
    }
    await expect(viewer.locator(`[data-story="${bStory}"]`)).toBeVisible();
    await expect(viewer.getByTestId("story-text-body")).toHaveText(text);
    await viewer.locator("[data-reaction=love]").click();
    await expect(viewer.locator("[data-reaction=love]")).toHaveAttribute("aria-pressed", "true");
    await viewer.getByTestId("story-more").click();
    await expect(viewer.getByTestId("story-report")).toBeVisible();
    await viewer.getByTestId("story-report").click();
    await expect(page.getByTestId("story-report-send")).toBeVisible();
    await page.waitForTimeout(400); // the dialog's pop-in fades its text in: let it settle before axe
    expect(await axe(page, "[data-testid=story-viewer]")).toEqual([]);
    await page.keyboard.press("Escape"); // the report dialog
    await page.keyboard.press("Escape"); // the viewer
    await expect(viewer).toBeHidden();
    // The server counted a's view and a's reaction for b.
    const viewers = (await (await apiB.get(`${API}/stories/${bStory}/viewers/`)).json()).data as { account_id: string; reaction: string }[];
    expect(viewers.find((v) => v.account_id === a.id)?.reaction).toBe("love");

    // 3. Create a close friends text story from the rail, adding b on the way.
    await rail.getByTestId("story-create").click();
    await page.getByTestId("story-kind-text").click();
    const mine = `${text} mine`;
    await page.getByTestId("story-text").fill(mine);
    await page.getByTestId("story-audience-close_friends").check();
    await page.getByTestId("story-manage-close-friends").click();
    const cf = page.getByTestId("close-friends-dialog");
    await expect(cf).toBeVisible();
    const candidate = cf.getByTestId("close-friend-candidate").filter({ hasText: b.name });
    if (await candidate.count()) await candidate.getByRole("button").click();
    await expect(cf.getByTestId("close-friend-row").filter({ hasText: b.name })).toBeVisible();
    expect(await axe(page, "[data-testid=close-friends-dialog]")).toEqual([]);
    await page.keyboard.press("Escape");
    await expect(cf).toBeHidden();
    await expect(page.getByTestId("story-preview")).toContainText(mine);
    await page.getByTestId("story-share").click();
    await expect(page.getByTestId("story-share")).toBeHidden();

    // b, on the list, sees it; the server says so too.
    const bTray = (await (await apiB.get(`${API}/stories/?author_id=${a.id}`)).json()).data as { id: string; text: string }[];
    const created = bTray.find((s) => s.text === mine);
    expect(created).toBeTruthy();

    // 4. My story in the rail: the viewer list and delete.
    await rail.locator(`[data-testid=story-tray-card][data-author="${a.id}"]`).click();
    await expect(viewer).toBeVisible();
    await page.getByTestId("story-pause").click();
    for (let i = 0; i < 60 && (await viewer.locator("[data-story]").getAttribute("data-story")) !== created!.id; i++) {
      await page.keyboard.press(forward);
    }
    await expect(viewer.getByTestId("story-viewers")).toBeVisible();
    await viewer.getByTestId("story-viewers").click();
    await expect(page.getByTestId("story-viewers-list")).toBeVisible();
    await page.keyboard.press("Escape");
    await viewer.getByTestId("story-more").click();
    await viewer.getByTestId("story-delete").click();
    await page.getByTestId("story-delete-confirm").click();
    await expect.poll(async () => (await apiB.get(`${API}/stories/${created!.id}/`)).status()).toBe(404);
    if (await viewer.isVisible()) await page.keyboard.press("Escape");

    // 5. Stories hub and archive from the main menu.
    await page.getByTestId("main-menu-button").click();
    await page.getByTestId("menu-item-stories").click();
    await expect(page).toHaveURL(/\/stories$/);
    await expect(page.getByTestId("stories-nav")).toBeVisible();
    await expect(page.locator(`[data-testid=stories-grid] [data-author="${b.id}"]`)).toBeVisible();
    expect(await axe(page, "main")).toEqual([]);
    await page.getByTestId("stories-archive-link").click();
    await expect(page).toHaveURL(/\/stories\/archive$/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(await axe(page, "main")).toEqual([]);
    await page.getByTestId("main-menu-button").click();
    await expect(page.getByTestId("menu-item-storyArchive")).toBeVisible();
    await expect(page.getByTestId("menu-create-story")).toBeVisible();
    await page.getByTestId("menu-create-story").click();
    await expect(page).toHaveURL(/\/stories/);
    await expect(page.getByTestId("story-kind-picker")).toBeVisible();
    expect(await axe(page, "[role=dialog]")).toEqual([]);
    await page.keyboard.press("Escape");

    // Cleanup (shared accounts): b's story and the close friends entry.
    await apiB.delete(`${API}/stories/${bStory}/`);
    await apiA.delete(`${API}/stories/close-friends/${b.id}/`);
    await page.context().close();
  });
}

test("a photo story goes through media and only its audience can open it", async ({ browser }) => {
  test.setTimeout(180_000);
  const { a, b, c } = await sharedAccounts();
  await befriend(a, b);
  const page = await pageAs(browser, a);
  await useLocale(page, "en");
  await page.setViewportSize(DESKTOP);
  await page.goto("/home");

  await page.getByTestId("story-create").click();
  await page.getByTestId("story-kind-picker").waitFor();
  const chooser = page.waitForEvent("filechooser");
  await page.getByTestId("story-kind-photo").click();
  await (await chooser).setFiles({ name: "story.png", mimeType: "image/png", buffer: png() });
  await page.getByTestId("story-audience-friends").check();
  await page.getByTestId("story-caption").fill("T9 photo");
  await page.getByTestId("story-share").click();
  await expect(page.getByTestId("story-share")).toBeHidden({ timeout: 30_000 });

  const apiB = await apiAs(b);
  const list = (await (await apiB.get(`${API}/stories/?author_id=${a.id}`)).json()).data as { id: string; kind: string; media_id: string; text: string }[];
  const photo = list.find((s) => s.kind === "photo" && s.text === "T9 photo");
  expect(photo).toBeTruthy();
  // b (a friend) may fetch the photo; c (not a friend) gets 404 for the story and its photo.
  await expect.poll(async () => (await apiB.get(`${API}/media/${photo!.media_id}/`)).status(), { timeout: 30_000 }).toBe(200);
  const apiC = await apiAs(c);
  const friendsOfC = (await (await apiC.get(`${API}/friends/`)).json()).data.friends as string[];
  if (!friendsOfC.includes(a.id)) {
    expect((await apiC.get(`${API}/stories/${photo!.id}/`)).status()).toBe(404);
    expect((await apiC.get(`${API}/media/${photo!.media_id}/`)).status()).toBe(404);
  }

  // b opens it from the rail and the photo renders.
  const pageB = await pageAs(browser, b);
  await useLocale(pageB, "en");
  await pageB.setViewportSize(DESKTOP);
  await pageB.goto("/home");
  await pageB.locator(`[data-testid=story-tray-card][data-author="${a.id}"]`).click();
  const viewer = pageB.getByTestId("story-viewer");
  await pageB.getByTestId("story-pause").click();
  for (let i = 0; i < 60 && (await viewer.locator("[data-story]").getAttribute("data-story")) !== photo!.id; i++) {
    await pageB.keyboard.press("ArrowRight");
  }
  await expect(viewer.locator(`[data-story="${photo!.id}"] img`)).toBeVisible();
  await expect
    .poll(async () => viewer.locator(`[data-story="${photo!.id}"] img`).evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0);

  await (await apiAs(a)).delete(`${API}/stories/${photo!.id}/`);
  await pageB.context().close();
  await page.context().close();
});

for (const lang of ["ar", "en"] as const) {
  test(`reply in Messages, followed public stories, archive tiles (${lang})`, async ({ browser }) => {
    test.setTimeout(180_000);
    const { a, b, c } = await sharedAccounts();
    await befriend(a, b);
    const apiA = await apiAs(a);
    const apiB = await apiAs(b);
    const apiC = await apiAs(c);
    const text = `T9 reply ${lang} ${Date.now()}`;
    const bStory = (await (await apiB.post(`${API}/stories/`, { data: { kind: "text", audience: "friends", text, background: "aurora" } })).json()).data.id as string;

    // c is not a friend but a follows c: c's public story reaches a's tray, c's friends-only one does not.
    const wereFriends = ((await (await apiA.get(`${API}/friends/`)).json()).data.friends as string[]).includes(c.id);
    if (wereFriends) await unfriend(a, c);
    await apiA.post(`${API}/follows/${c.id}/`);
    const cPublic = (await (await apiC.post(`${API}/stories/`, { data: { kind: "text", audience: "public", text: `${text} public`, background: "dusk" } })).json()).data.id as string;
    const cFriends = (await (await apiC.post(`${API}/stories/`, { data: { kind: "text", audience: "friends", text: `${text} friends`, background: "violet" } })).json()).data.id as string;

    const page = await pageAs(browser, a);
    await useLocale(page, lang);
    await page.setViewportSize(DESKTOP);
    await page.goto("/home");
    const rail = page.getByTestId("stories-rail");
    const cCard = rail.locator(`[data-testid=story-tray-card][data-author="${c.id}"]`);
    await expect(cCard).toBeVisible();
    const tray = (await (await apiA.get(`${API}/stories/tray/`)).json()).data as { author_id: string; stories: { id: string }[] }[];
    const cIds = tray.find((g) => g.author_id === c.id)?.stories.map((s) => s.id) ?? [];
    expect(cIds).toContain(cPublic);
    expect(cIds).not.toContain(cFriends);
    expect((await apiA.get(`${API}/stories/${cFriends}/`)).status()).toBe(404);

    // Reply to b's story: it lands in the a-b conversation with a link back.
    await rail.locator(`[data-testid=story-tray-card][data-author="${b.id}"]`).click();
    const viewer = page.getByTestId("story-viewer");
    await expect(viewer).toBeVisible();
    await page.getByTestId("story-pause").click();
    const forward = lang === "ar" ? "ArrowLeft" : "ArrowRight";
    for (let i = 0; i < 20 && (await viewer.locator("[data-story]").getAttribute("data-story")) !== bStory; i++) {
      await page.keyboard.press(forward);
    }
    await expect(viewer.locator(`[data-story="${bStory}"]`)).toBeVisible();
    const reply = `reply ${Date.now()}`;
    await viewer.getByTestId("story-reply-input").fill(reply);
    await viewer.getByTestId("story-reply-send").click();
    await expect(viewer.getByTestId("story-reply-input")).toHaveValue("");
    const conversation = await dmWith(apiA, b.id);
    await expect
      .poll(async () => {
        const rows = (await (await apiB.get(`${API}/conversations/${conversation}/messages/`)).json()).data as { body: string }[];
        return rows.find((m) => m.body.startsWith(reply))?.body ?? "";
      })
      .toContain(`/stories/${bStory}`);
    expect(await axe(page, "[data-testid=story-viewer]")).toEqual([]);
    await page.keyboard.press("Escape");

    // My archive: an active story carries the "active" badge.
    const mine = (await (await apiA.post(`${API}/stories/`, { data: { kind: "text", audience: "friends", text: `${text} mine`, background: "magenta" } })).json()).data.id as string;
    await page.getByTestId("main-menu-button").click();
    await page.getByTestId("menu-item-storyArchive").click();
    await expect(page).toHaveURL(/\/stories\/archive$/);
    const tile = page.getByTestId("story-archive-tile").filter({ hasText: `${text} mine` });
    await expect(tile).toBeVisible();
    await expect(tile).toContainText(lang === "ar" ? "نشطة" : "Active");
    expect(await axe(page, "main")).toEqual([]);

    for (const [api, id] of [[apiB, bStory], [apiC, cPublic], [apiC, cFriends], [apiA, mine]] as const) {
      await api.delete(`${API}/stories/${id}/`);
    }
    await apiA.delete(`${API}/follows/${c.id}/`);
    if (wereFriends) await befriend(a, c);
    await page.context().close();
  });
}
