import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, type Page, expect, request, test } from "@playwright/test";

import { API, apiAs, BASE_URL, befriend, expectNoUuid, pageAs, sharedAccounts, unique, useLocale } from "./helpers";

// Reels (roadmap 5.5 / 5.8), apart from video posts: a short vertical clip
// becomes a reel through "Create reel" in the Create menu, shows in a friend's
// Reels rail on Home, opens in the full-height pager, and is liked with a
// double tap. A landscape clip is refused as a reel by the server and offered
// as a normal video post instead.

const MEDIA_CONTAINER = process.env.E2E_MEDIA_CONTAINER ?? "tara-media-1";

/** A test-pattern clip made by the media image's own ffmpeg. */
function makeClip(size: string, seconds = 3): string {
  const dir = join(tmpdir(), "tara-e2e-reels");
  mkdirSync(dir, { recursive: true });
  const path = join(dir, `clip-${size}-${unique()}.mp4`);
  const bytes = execFileSync(
    "docker",
    [
      "exec", MEDIA_CONTAINER, "ffmpeg", "-hide_banner", "-loglevel", "error",
      "-f", "lavfi", "-i", `testsrc=size=${size}:rate=30:duration=${seconds}`,
      "-f", "lavfi", "-i", `sine=frequency=440:duration=${seconds}`,
      "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
      "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1",
    ],
    { maxBuffer: 64 * 1024 * 1024 },
  );
  writeFileSync(path, bytes);
  return path;
}

async function seriousViolations(page: Page, selector: string) {
  const result = await new AxeBuilder({ page }).include(selector).withTags(["wcag2a", "wcag2aa"]).analyze();
  return result.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes[0]?.target}`);
}

/** The app's presigned flow through the API: sign, PUT through the storage proxy, complete, wait. */
async function uploadVideo(api: APIRequestContext, path: string): Promise<string> {
  const bytes = readFileSync(path);
  const signed = await api.post(`${API}/media/uploads/sign/`, {
    data: { kind: "video", mime: "video/mp4", size: bytes.length, purpose: "post" },
  });
  expect(signed.status(), await signed.text()).toBe(201);
  const { media_id: mediaId, upload_url: uploadUrl } = (await signed.json()).data;
  const target = new URL(uploadUrl);
  const storage = await request.newContext();
  const put = await storage.put(`${BASE_URL}/__s3${target.pathname}${target.search}`, {
    headers: { "Content-Type": "video/mp4" },
    data: bytes,
  });
  expect(put.ok(), `PUT ${put.status()}`).toBe(true);
  await storage.dispose();
  expect((await api.post(`${API}/media/uploads/${mediaId}/complete/`)).ok()).toBe(true);
  await expect
    .poll(async () => (await (await api.get(`${API}/media/${mediaId}/`)).json()).data.status, { timeout: 120_000 })
    .toBe("ready");
  return mediaId;
}

const T = {
  ar: { menu: "القائمة", ready: "الريل جاهز للمشاركة.", notReel: "لا يمكن أن يكون هذا المقطع ريلًا" },
  en: { menu: "Menu", ready: "Your reel is ready to share.", notReel: "This clip can't be a reel" },
};

for (const lang of ["ar", "en"] as const) {
  test(`create a reel from a vertical clip, find it in a friend's rail, open the pager and like it (${lang})`, async ({ browser }) => {
    test.setTimeout(300_000);
    const { a, b } = await sharedAccounts();
    await befriend(a, b);
    const clip = makeClip("360x640", 3);

    // The author: Create menu → Create reel.
    const page = await pageAs(browser, a);
    if (lang === "en") await useLocale(page, "en");
    await page.goto("/home");
    await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
    await page.getByRole("button", { name: T[lang].menu, exact: true }).click();
    await page.getByTestId("menu-create-reel").click();
    await expect(page).toHaveURL(/\/reels\?create=1$/);
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByTestId("reel-create")).toHaveAttribute("data-phase", "pick");
    expect(await seriousViolations(page, "[role=dialog]")).toEqual([]);

    const chooser = page.waitForEvent("filechooser");
    await dialog.getByTestId("reel-pick").click();
    await (await chooser).setFiles(clip);
    await expect(dialog.getByTestId("reel-create")).toHaveAttribute("data-phase", /uploading|processing|checking/);
    await expect(dialog.getByTestId("reel-create")).toHaveAttribute("data-phase", "ready", { timeout: 150_000 });
    await expect(dialog.getByText(T[lang].ready)).toBeVisible();
    const caption = `ريل ${unique()} #tara`;
    await dialog.getByTestId("reel-caption-input").fill(caption);
    await dialog.getByTestId("reel-audience-public").check();
    expect(await seriousViolations(page, "[role=dialog]")).toEqual([]);
    const published = page.waitForResponse((r) => r.request().method() === "POST" && new URL(r.url()).pathname.endsWith("/reels/"));
    await dialog.getByTestId("reel-share-submit").click();

    // Published: the pager opens at the new reel (the id comes from the API: the
    // pager behind the dialog already shows other reels in the URL).
    const reelId = (await (await published).json()).data.id as string;
    await expect(page).toHaveURL(new RegExp(`/reels/${reelId}`), { timeout: 30_000 });
    const own = page.locator(`[data-testid=reel-slide][data-reel-id="${reelId}"]`);
    await expect(own.getByTestId("reel-caption")).toHaveText(caption);
    const api = await apiAs(a);
    const created = (await (await api.get(`${API}/reels/${reelId}/`)).json()).data;
    expect(created.type).toBe("reel");
    expect(created.reel.height).toBeGreaterThan(created.reel.width);
    // Not a video post: the Videos list (landscape / long videos) never has it.
    const videos = (await (await api.get(`${API}/posts/`, { params: { type: "video", author_id: a.id } })).json()).data as { id: string }[];
    expect(videos.map((v) => v.id)).not.toContain(reelId);
    await api.dispose();

    // A friend: the Reels rail on Home, apart from the Videos rail.
    const friend = await pageAs(browser, b);
    if (lang === "en") await useLocale(friend, "en");
    await friend.goto("/home");
    const rail = friend.getByTestId("reels-rail");
    await expect(rail).toBeVisible({ timeout: 30_000 });
    const tile = rail.locator(`[data-testid=reels-rail-item][data-reel-id="${reelId}"]`);
    await expect(tile).toBeVisible();
    expect(await seriousViolations(friend, "[data-testid=reels-rail]")).toEqual([]);
    await tile.click();

    // The pager: the reel on screen autoplays muted, at most three players exist.
    await expect(friend).toHaveURL(new RegExp(`/reels/${reelId}`));
    const slide = friend.locator(`[data-testid=reel-slide][data-reel-id="${reelId}"]`);
    await expect(slide).toHaveAttribute("aria-current", "true");
    const video = slide.getByTestId("reel-video");
    await expect(slide.getByTestId("reel-player")).toHaveAttribute("data-state", "ready", { timeout: 30_000 });
    await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.currentTime), { timeout: 30_000 }).toBeGreaterThan(0.3);
    expect(await video.evaluate((v: HTMLVideoElement) => v.muted)).toBe(true);
    expect(await friend.getByTestId("reel-player").count()).toBeLessThanOrEqual(3);

    // Double tap to like; the like is the post's own reaction.
    await slide.getByTestId("reel-tap").dblclick();
    await expect(slide.getByTestId("reel-like")).toHaveAttribute("aria-pressed", "true");
    const friendApi = await apiAs(b);
    await expect
      .poll(async () => (await (await friendApi.get(`${API}/reels/${reelId}/`)).json()).data.my_reaction)
      .toBe("like");

    // Comments open in a URL-backed sheet.
    await slide.getByTestId("reel-comment").click();
    await expect(friend).toHaveURL(/sheet=comments/);
    await expect(friend.getByTestId("reel-comments-sheet")).toBeVisible();
    await friend.keyboard.press("Escape");
    await expect(friend).not.toHaveURL(/sheet=comments/);

    // The view counted once for the friend today.
    await expect
      .poll(async () => (await (await friendApi.get(`${API}/reels/${reelId}/`)).json()).data.reel.viewed_today, { timeout: 15_000 })
      .toBe(true);
    await friendApi.dispose();

    expect(await seriousViolations(friend, "[data-testid=reel-pager]")).toEqual([]);
    await expectNoUuid(friend);

    // The author's profile has a Reels tab that opens the pager at that reel.
    await friend.goto(`/u/${a.handle}?tab=reels`);
    const gridItem = friend.locator(`[data-testid=reel-grid-item][data-reel-id="${reelId}"]`);
    await expect(gridItem).toBeVisible({ timeout: 20_000 });
    await gridItem.click();
    await expect(friend).toHaveURL(new RegExp(`/reels/${reelId}\\?author=`));
    await expect(friend.locator(`[data-testid=reel-slide][data-reel-id="${reelId}"]`)).toHaveAttribute("aria-current", "true");
  });

  test(`the reel's options: save, report, and Undo on "Not interested" (${lang})`, async ({ browser }) => {
    test.setTimeout(300_000);
    // c is the author here, so a's daily video quota is left to the other tests.
    const { b, c } = await sharedAccounts();
    await befriend(c, b);
    const author = await apiAs(c);
    const mediaId = await uploadVideo(author, makeClip("360x640", 2));
    const made = await author.post(`${API}/reels/`, { data: { media_id: mediaId, caption: `ريل ${unique()}`, audience: "public" } });
    expect(made.status(), await made.text()).toBe(201);
    const reelId = (await made.json()).data.id as string;
    await author.dispose();

    const page = await pageAs(browser, b);
    if (lang === "en") await useLocale(page, "en");
    const viewer = await apiAs(b);
    const sheet = () => page.getByTestId("reel-more-sheet");
    const openMore = async () => {
      await page.goto(`/reels/${reelId}?sheet=more`);
      await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
      await expect(sheet()).toBeVisible({ timeout: 20_000 });
    };

    // Save, then unsave: the post's saved items.
    await openMore();
    expect(await seriousViolations(page, "[role=dialog]")).toEqual([]);
    await sheet().getByTestId("reel-save").click();
    await expect(page).not.toHaveURL(/sheet=more/);
    await expect
      .poll(async () => (await (await viewer.get(`${API}/reels/${reelId}/`)).json()).data.is_saved)
      .toBe(true);
    await openMore();
    await expect(sheet().getByTestId("reel-save")).toHaveAttribute("aria-pressed", "true");
    await sheet().getByTestId("reel-save").click();
    await expect
      .poll(async () => (await (await viewer.get(`${API}/reels/${reelId}/`)).json()).data.is_saved)
      .toBe(false);

    // Report: the post's report flow.
    await openMore();
    await sheet().getByTestId("reel-report").click();
    const form = page.getByTestId("reel-report-form");
    await expect(form.getByTestId("reel-report-submit")).toBeDisabled();
    expect(await seriousViolations(page, "[role=dialog]")).toEqual([]);
    await form.getByTestId("reel-report-reason").fill(`سبام ${unique()}`);
    await form.getByTestId("reel-report-submit").click();
    await expect(form).toHaveCount(0);
    await expect(page).not.toHaveURL(/sheet=more/);

    // Not interested leaves the pager; Undo on the toast brings it back.
    await openMore();
    await sheet().getByTestId("reel-not-interested").click();
    const slide = page.locator(`[data-testid=reel-slide][data-reel-id="${reelId}"]`);
    await expect(slide).toHaveCount(0);
    await page.getByTestId("reel-undo-hide").click();
    await expect(slide).toHaveCount(1);
    const feed = (await (await viewer.get(`${API}/reels/`)).json()).data as { id: string }[];
    expect(feed.map((r) => r.id)).toContain(reelId);
    await viewer.dispose();
    await expectNoUuid(page);
  });

  test(`a landscape clip is offered as a video, not a reel (${lang})`, async ({ browser }) => {
    test.setTimeout(300_000);
    const { a } = await sharedAccounts();

    // The server refuses it as a reel, with a clear code.
    const api = await apiAs(a);
    const landscapeId = await uploadVideo(api, makeClip("640x360", 2));
    const refused = await api.post(`${API}/reels/`, { data: { media_id: landscapeId, caption: "x" } });
    expect(refused.status()).toBe(400);
    expect((await refused.json()).error.code).toBe("reel_not_vertical");
    const check = (await (await api.post(`${API}/reels/eligibility/`, { data: { media_id: landscapeId } })).json()).data;
    expect(check).toMatchObject({ eligible: false, code: "reel_not_vertical" });
    await api.dispose();

    // The composer says so and posts it as a normal video instead.
    const page = await pageAs(browser, a);
    if (lang === "en") await useLocale(page, "en");
    await page.goto("/reels?create=1");
    const dialog = page.getByRole("dialog");
    const chooser = page.waitForEvent("filechooser");
    await dialog.getByTestId("reel-pick").click();
    await (await chooser).setFiles(makeClip("640x360", 2));
    await expect(dialog.getByTestId("reel-create")).toHaveAttribute("data-phase", "notReel", { timeout: 150_000 });
    await expect(dialog.getByTestId("reel-not-reel")).toContainText(T[lang].notReel);
    await expect(dialog.getByTestId("reel-share-submit")).toHaveCount(0);
    expect(await seriousViolations(page, "[role=dialog]")).toEqual([]);
    const body = `فيديو أفقي ${unique()}`;
    await dialog.getByTestId("reel-caption-input").fill(body);
    await dialog.getByTestId("reel-post-as-video").click();
    await expect(page).toHaveURL(/\/posts\/[0-9a-f-]{36}/, { timeout: 30_000 });
    const postId = /\/posts\/([0-9a-f-]{36})/.exec(page.url())![1];
    await expect(page.locator("article").filter({ hasText: body }).getByTestId("video-player")).toBeVisible();
    const owner = await apiAs(a);
    const post = (await (await owner.get(`${API}/posts/${postId}/`)).json()).data;
    expect(post.type).toBe("video");
    expect((await owner.get(`${API}/reels/${postId}/`)).status()).toBe(404);
    await owner.dispose();
  });
}
