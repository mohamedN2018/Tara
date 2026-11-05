import { deflateSync } from "node:zlib";

import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, type Page, expect, request, test } from "@playwright/test";

import { API, BASE_URL, apiAs, befriend, pageAs, sharedAccounts, unique, useLocale } from "./helpers";

// Plan 08, profile track (audit gaps 6, 7, 8, 10), in Arabic and English, with
// axe: the photo theater's side panel (author, text, reactions, comments, zoom),
// the Photos sub-tabs (yours, of you, albums), the cover's "Choose from your
// photos" and drag-to-reposition, the avatar crop, the Posts filters and grid,
// "Saved reels", and the Page owner tools (Manage Page rail, Page transparency
// with the name history, Photos and Links cards). Everything is real API data.

const DESKTOP = { width: 1440, height: 900 };

async function axe(page: Page, selector: string): Promise<string[]> {
  await page.waitForFunction(() =>
    document.getAnimations().every((a) => a.playState !== "running" || a.effect?.getComputedTiming().endTime === Infinity),
  );
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).include(selector).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

// A real PNG (a brand gradient), so the media pipeline has something to process.
function png(width = 360, height = 640, tint = 0): Buffer {
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
    for (let x = 0; x < width; x++) rows.push((106 + tint + Math.round((149 * y) / height)) % 256, Math.round((85 * x) / width), 244 - Math.round((28 * y) / height));
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.from(rows))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

/** Sign, PUT through the storage proxy, complete and wait until the image is ready. */
async function uploadImage(api: APIRequestContext, tint = 0): Promise<string> {
  const bytes = png(360, 640, tint);
  const signed = await api.post(`${API}/media/uploads/sign/`, { data: { kind: "image", mime: "image/png", size: bytes.length } });
  expect(signed.status(), await signed.text()).toBe(201);
  const { media_id: mediaId, upload_url: uploadUrl } = (await signed.json()).data;
  const target = new URL(uploadUrl);
  const storage = await request.newContext();
  const put = await storage.put(`${BASE_URL}/__s3${target.pathname}${target.search}`, { headers: { "Content-Type": "image/png" }, data: bytes });
  expect(put.ok(), `PUT ${put.status()}`).toBe(true);
  await storage.dispose();
  expect((await api.post(`${API}/media/uploads/${mediaId}/complete/`)).ok()).toBe(true);
  await expect
    .poll(async () => (await (await api.get(`${API}/media/${mediaId}/`)).json()).data?.status, { timeout: 120_000 })
    .toMatch(/ready|processed/);
  return mediaId;
}

async function photoPost(api: APIRequestContext, body: string, count: number, extra: object = {}): Promise<string> {
  const media_ids: string[] = [];
  for (let i = 0; i < count; i++) media_ids.push(await uploadImage(api, i * 40));
  const res = await api.post(`${API}/posts/`, { data: { type: "image", audience: "public", body, media_ids, ...extra } });
  expect(res.status(), await res.text()).toBe(201);
  return (await res.json()).data.id as string;
}

for (const lang of ["ar", "en"] as const) {
  test(`photo theater: post panel, zoom, react and comment from the Photos tab (${lang})`, async ({ browser }) => {
    test.setTimeout(300_000);
    const { a } = await sharedAccounts();
    const apiA = await apiAs(a);
    const body = `PT ${lang} ${unique()}`;
    const postId = await photoPost(apiA, body, 2);

    const page = await pageAs(browser, a);
    await useLocale(page, lang);
    await page.setViewportSize(DESKTOP);
    await page.goto(`/u/id/${a.id}`);
    await page.getByTestId("profile-tab-photos").click();
    await page.getByTestId("photos-list-by").click();
    await expect(page.getByTestId("photos-tile").first()).toBeVisible();
    await page.getByTestId("photos-tile").first().click();

    const theater = page.getByTestId("media-theater");
    await expect(theater).toBeVisible();
    const panel = theater.getByTestId("theater-panel");
    await expect(panel).toBeVisible();
    await expect(panel.getByTestId("theater-author")).toContainText(a.name);
    await expect(panel.getByTestId("theater-body")).toContainText(body);
    expect(await axe(page, "[data-testid='media-theater']")).toEqual([]);

    // Zoom in twice, out once; a new photo starts unzoomed.
    await theater.getByTestId("theater-zoom-in").click();
    await theater.getByTestId("theater-zoom-in").click();
    await expect(theater.getByTestId("theater-stage")).toHaveAttribute("data-zoom", "2");
    await theater.getByTestId("theater-zoom-out").click();
    await expect(theater.getByTestId("theater-stage")).toHaveAttribute("data-zoom", "1.5");
    await page.keyboard.press(lang === "ar" ? "ArrowLeft" : "ArrowRight");
    await expect(theater.getByTestId("theater-stage")).toHaveAttribute("data-zoom", "1");

    // Like and comment from the panel; the post service has both.
    await panel.getByRole("button", { name: lang === "ar" ? "إعجاب" : "Like", exact: true }).click();
    await expect.poll(async () => (await (await apiA.get(`${API}/posts/${postId}/`)).json()).data.my_reaction).toBe("like");
    const comment = `nice ${unique()}`;
    await panel.getByPlaceholder(lang === "ar" ? "اكتب تعليقًا…" : "Write a comment…").first().fill(comment);
    await panel.locator("form button[type=submit]").first().click();
    await expect(panel).toContainText(comment);
    await expect
      .poll(async () => ((await (await apiA.get(`${API}/posts/${postId}/comments/`)).json()).data as { body: string }[]).some((c) => c.body === comment))
      .toBe(true);

    // The panel hides and shows again.
    await theater.getByTestId("theater-panel-toggle").click();
    await expect(panel).toBeHidden();
    await theater.getByTestId("theater-panel-toggle").click();
    await expect(panel).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(theater).toBeHidden();

    // Albums: the two-photo post is one album card.
    await page.getByTestId("photos-list-albums").click();
    await expect(page.getByTestId("photos-album").first()).toBeVisible();
    await expect(page.getByTestId("photos-album").first()).toContainText(body);
    expect(await axe(page, "[data-testid='profile-photos']")).toEqual([]);
    await page.close();
  });

  test(`cover from your photos, drag to reposition, avatar crop (${lang})`, async ({ browser }) => {
    test.setTimeout(300_000);
    const { a } = await sharedAccounts();
    const apiA = await apiAs(a);
    await photoPost(apiA, `cover source ${unique()}`, 1);

    const page = await pageAs(browser, a);
    await useLocale(page, lang);
    await page.setViewportSize(DESKTOP);
    await page.goto(`/u/id/${a.id}`);

    // Choose from your photos -> the reposition bar opens on the new cover.
    await page.getByTestId("edit-cover").click();
    await page.getByTestId("cover-choose").click();
    const picker = page.getByTestId("photo-picker");
    await expect(picker.getByTestId("photo-picker-item").first()).toBeEnabled({ timeout: 30_000 });
    expect(await axe(page, "[data-testid='photo-picker']")).toEqual([]);
    await picker.getByTestId("photo-picker-item").first().click();
    await expect(page.getByTestId("cover-reposition-bar")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("cover-image")).toBeVisible();

    // Drag the cover up (shows more of the bottom) and nudge with the keyboard.
    const frame = page.getByTestId("cover-frame");
    const box = (await frame.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 - 120, { steps: 6 });
    await page.mouse.up();
    await frame.focus();
    await page.keyboard.press("ArrowDown");
    const dragged = Number(await frame.getAttribute("data-offset"));
    expect(dragged).toBeGreaterThan(50);
    await page.getByTestId("cover-reposition-save").click();
    await expect(page.getByTestId("cover-reposition-bar")).toBeHidden();
    await expect.poll(async () => (await (await apiA.get(`${API}/profile/me/`)).json()).data.cover_offset_y).toBe(dragged);

    // A visitor's view and a reload show the same position.
    await page.reload();
    await expect(page.getByTestId("cover-frame")).toHaveAttribute("data-offset", String(dragged));

    // Cancel leaves it where it was.
    await page.getByTestId("edit-cover").click();
    await page.getByTestId("cover-reposition").click();
    await page.getByTestId("cover-frame").focus();
    await page.keyboard.press("ArrowUp");
    await page.getByTestId("cover-reposition-cancel").click();
    await expect(page.getByTestId("cover-frame")).toHaveAttribute("data-offset", String(dragged));

    // Avatar: upload -> crop dialog with zoom -> a new, cropped upload.
    const before = (await (await apiA.get(`${API}/profile/me/`)).json()).data.avatar_media_id;
    await page.getByTestId("edit-avatar").click();
    await page.getByTestId("avatar-input").setInputFiles({ name: "me.png", mimeType: "image/png", buffer: png(800, 500) });
    const crop = page.getByTestId("avatar-crop");
    await expect(crop).toBeVisible();
    await expect(crop.getByTestId("avatar-crop-zoom")).toBeEnabled();
    expect(await axe(page, "[data-testid='avatar-crop']")).toEqual([]);
    await crop.getByTestId("avatar-crop-zoom").fill("2");
    await crop.getByTestId("avatar-crop-save").click();
    await expect(crop).toBeHidden({ timeout: 60_000 });
    const after = (await (await apiA.get(`${API}/profile/me/`)).json()).data.avatar_media_id;
    expect(after).toBeTruthy();
    expect(after).not.toBe(before);
    const asset = (await (await apiA.get(`${API}/media/${after}/`)).json()).data;
    expect(asset.mime ?? asset.kind).toMatch(/jpeg|image/);
    await page.close();
  });

  test(`posts header: filters by who posted and year, grid view (${lang})`, async ({ browser }) => {
    test.setTimeout(240_000);
    const { a, b } = await sharedAccounts();
    await befriend(a, b);
    const apiA = await apiAs(a);
    const apiB = await apiAs(b);
    const own = `own ${lang} ${unique()}`;
    expect((await apiA.post(`${API}/posts/`, { data: { type: "text", audience: "public", body: own } })).status()).toBe(201);
    const tagged = `tagged ${lang} ${unique()}`;
    const res = await apiB.post(`${API}/posts/`, { data: { type: "text", audience: "public", body: tagged, tagged_ids: [a.id] } });
    expect(res.status(), await res.text()).toBe(201);
    // The server filters: another year has none of these, and tagged_id lists b's post.
    const old = (await (await apiB.get(`${API}/posts/`, { params: { author_id: a.id, year: 2001 } })).json()).data;
    expect(old).toEqual([]);
    const others = (await (await apiB.get(`${API}/posts/`, { params: { tagged_id: a.id } })).json()).data as { body: string }[];
    expect(others.some((p) => p.body === tagged)).toBe(true);

    const page = await pageAs(browser, a);
    await useLocale(page, lang);
    await page.setViewportSize(DESKTOP);
    await page.goto(`/u/id/${a.id}`);
    await expect(page.locator("article", { hasText: own })).toBeVisible();

    await page.getByTestId("profile-posts-filters").click();
    const dialog = page.getByTestId("profile-posts-filters-dialog");
    await expect(dialog).toBeVisible();
    expect(await axe(page, "[data-testid='profile-posts-filters-dialog']")).toEqual([]);
    await dialog.getByTestId("profile-posts-filter-others").check();
    await dialog.getByTestId("profile-posts-filter-year").selectOption(String(new Date().getFullYear()));
    await dialog.getByTestId("profile-posts-filter-apply").click();
    await expect(page.locator("article", { hasText: tagged })).toBeVisible();
    await expect(page.locator("article", { hasText: own })).toHaveCount(0);
    await expect(page.getByTestId("profile-posts-filters")).toContainText("2");
    // b's post is labelled with b's name, not a's.
    await expect(page.locator("article", { hasText: tagged }).getByTestId("post-author-name")).toContainText(b.name);

    await page.getByTestId("profile-posts-filters").click();
    await page.getByTestId("profile-posts-filter-clear").click();
    await expect(page.locator("article", { hasText: own })).toBeVisible();

    await page.getByTestId("profile-posts-view-grid").click();
    await expect(page.getByTestId("profile-posts-grid")).toBeVisible();
    await expect(page.getByTestId("profile-posts-grid-item").first()).toBeVisible();
    expect(await axe(page, "[data-testid='profile-posts-grid']")).toEqual([]);
    await page.getByTestId("profile-posts-view-list").click();
    await expect(page.getByTestId("profile-posts-grid")).toHaveCount(0);
    await page.close();
  });

  test(`saved reels on your own profile (${lang})`, async ({ browser }) => {
    test.setTimeout(120_000);
    const { a, b } = await sharedAccounts();
    const apiA = await apiAs(a);
    const feed = (await (await apiA.get(`${API}/reels/`, { params: { tab: "for_you" } })).json()).data as { id: string; author_id: string }[];
    const reel = feed.find((r) => r.author_id !== a.id);
    test.skip(!reel, "no reel from someone else to save in this dataset");
    await apiA.post(`${API}/posts/${reel!.id}/save/`);

    const page = await pageAs(browser, a);
    await useLocale(page, lang);
    await page.setViewportSize(DESKTOP);
    await page.goto(`/u/id/${a.id}?tab=reels`);
    await page.getByTestId("reel-list-saved").click();
    await expect(page.locator(`[data-testid='reel-grid-item'][data-reel-id='${reel!.id}']`)).toBeVisible({ timeout: 30_000 });
    expect(await axe(page, "[data-testid='reel-grid']")).toEqual([]);

    // Someone else's profile has no "Saved reels".
    await page.goto(`/u/id/${b.id}?tab=reels`);
    await expect(page.getByTestId("reel-grid")).toBeVisible();
    await expect(page.getByTestId("reel-list-saved")).toHaveCount(0);
    await page.close();
  });

  test(`page owner tools: Manage Page rail, transparency with name history, photos and links (${lang})`, async ({ browser }) => {
    test.setTimeout(300_000);
    const { a, b } = await sharedAccounts();
    const apiA = await apiAs(a);
    const apiB = await apiAs(b);
    const handle = `pt${lang}${unique()}`;
    const made = await apiA.post(`${API}/pages/`, {
      data: { handle, name: `Old ${handle}`, category: "Books", contact: { website: "https://example.com/books" } },
    });
    expect(made.status(), await made.text()).toBe(201);
    const pageId = (await made.json()).data.id as string;
    const newName = `Nile ${handle}`;
    expect((await apiA.patch(`${API}/pages/id/${pageId}/`, { data: { name: newName } })).ok()).toBe(true);
    await photoPost(apiA, `page photo ${handle}`, 1, { page_id: pageId });

    const page = await pageAs(browser, a);
    await useLocale(page, lang);
    await page.setViewportSize(DESKTOP);
    await page.goto(`/pages/${handle}`);
    const rail = page.getByTestId("manage-page-rail");
    await expect(rail).toBeVisible();
    await expect(rail.getByTestId("manage-page-inbox")).toHaveAttribute("href", `/pages/id/${pageId}/inbox`);
    await expect(rail.getByTestId("manage-page-studio")).toHaveAttribute("href", "/studio");
    await expect(rail.getByTestId("manage-page-ads")).toHaveAttribute("href", "/ads");
    expect(await axe(page, "[data-testid='manage-page-rail']")).toEqual([]);
    await expect(page.getByTestId("page-links")).toContainText("example.com/books");
    await expect(page.getByTestId("page-photos-tile").first()).toBeVisible({ timeout: 30_000 });

    await rail.getByTestId("manage-page-transparency").click();
    const dialog = page.getByTestId("page-transparency");
    await expect(dialog.getByTestId("page-transparency-renames")).toContainText(`Old ${handle}`);
    await expect(dialog.getByTestId("page-transparency-renames")).toContainText(newName);
    expect(await axe(page, "[data-testid='page-transparency']")).toEqual([]);
    await page.keyboard.press("Escape");

    // The settings entry opens the page editor.
    await rail.getByTestId("manage-page-settings").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.close();

    // A visitor: no rail, but the transparency dialog from the "..." menu.
    const visitor = await pageAs(browser, b);
    await useLocale(visitor, lang);
    await visitor.setViewportSize(DESKTOP);
    await visitor.goto(`/pages/${handle}`);
    await expect(visitor.getByTestId("page-header")).toBeVisible();
    await expect(visitor.getByTestId("manage-page-rail")).toHaveCount(0);
    await visitor.getByTestId("page-more").click();
    await visitor.getByTestId("page-transparency-open").click();
    await expect(visitor.getByTestId("page-transparency-renames")).toContainText(newName);
    await visitor.close();

    // A draft page's transparency is 404 for outsiders, 200 for its team.
    expect((await apiA.patch(`${API}/pages/id/${pageId}/`, { data: { status: "draft" } })).ok()).toBe(true);
    expect((await apiB.get(`${API}/pages/id/${pageId}/transparency/`)).status()).toBe(404);
    expect((await apiA.get(`${API}/pages/id/${pageId}/transparency/`)).status()).toBe(200);
  });
}
