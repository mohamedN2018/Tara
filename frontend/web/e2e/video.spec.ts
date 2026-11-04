import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, type Page, expect, request, test } from "@playwright/test";

import { API, apiAs, BASE_URL, befriend, expectNoUuid, pageAs, sharedAccounts, unfriend, unique, useLocale } from "./helpers";

// Video in posts (roadmap 5.2, 5.3, 5.7): the composer uploads a clip, media's
// transcoder turns it into HLS, the post plays it through a token-checked
// playlist, and a friends-only video stays hidden from strangers.

const MEDIA_CONTAINER = process.env.E2E_MEDIA_CONTAINER ?? "tara-media-1";

/** A short test-pattern clip made by the media image's own ffmpeg. */
function makeClip(seconds = 3): string {
  const dir = join(tmpdir(), "tara-e2e-video");
  mkdirSync(dir, { recursive: true });
  const path = join(dir, `clip-${seconds}s-${unique()}.mp4`);
  const bytes = execFileSync(
    "docker",
    [
      "exec", MEDIA_CONTAINER, "ffmpeg", "-hide_banner", "-loglevel", "error",
      "-f", "lavfi", "-i", `testsrc=size=640x360:rate=30:duration=${seconds}`,
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

/** Wait until the player's <video> really plays: currentTime moves forward. */
async function expectPlaying(page: Page, scope = page.locator("body")) {
  const player = scope.getByTestId("video-player").first();
  await expect(player).toHaveAttribute("data-state", "ready", { timeout: 30_000 });
  await player.getByTestId("video-play").click();
  const video = player.getByTestId("video-element");
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.currentTime), { timeout: 30_000 }).toBeGreaterThan(0.5);
  await expect(player.getByTestId("video-controls")).toBeVisible();
  // Media time runs left to right in both languages (not mirrored in Arabic).
  await expect(player.getByTestId("video-scrubber")).toHaveAttribute("dir", "ltr");
}

/** The same presigned flow as the app: sign, PUT through the storage proxy, complete. */
async function uploadVideo(api: APIRequestContext, path: string): Promise<string> {
  const bytes = readFileSync(path);
  const signed = await api.post(`${API}/media/uploads/sign/`, {
    data: { kind: "video", mime: "video/mp4", size: bytes.length, purpose: "post" },
  });
  expect(signed.status(), await signed.text()).toBe(201);
  const { media_id: mediaId, upload_url: uploadUrl } = (await signed.json()).data;
  const target = new URL(uploadUrl);
  // Like the browser: the presigned URL is the only credential (no bearer token).
  const storage = await request.newContext();
  const put = await storage.put(`${BASE_URL}/__s3${target.pathname}${target.search}`, {
    headers: { "Content-Type": "video/mp4" },
    data: bytes,
  });
  expect(put.ok(), `PUT ${put.status()}`).toBe(true);
  await storage.dispose();
  const done = await api.post(`${API}/media/uploads/${mediaId}/complete/`);
  expect(done.ok(), await done.text()).toBe(true);
  await expect
    .poll(async () => (await (await api.get(`${API}/media/${mediaId}/`)).json()).data.status, { timeout: 120_000 })
    .toBe("ready");
  return mediaId;
}

const T = {
  ar: { open: "بماذا تفكر؟", addVideo: "إضافة فيديو", post: "نشر", ready: "الفيديو جاهز للنشر." },
  en: { open: "What's on your mind?", addVideo: "Add a video", post: "Post", ready: "Your video is ready to post." },
};

for (const lang of ["ar", "en"] as const) {
  test(`upload a clip in a post, see it processed, and play it (${lang})`, async ({ browser }) => {
    test.setTimeout(240_000);
    const { a } = await sharedAccounts();
    const clip = makeClip(3);
    const page = await pageAs(browser, a);
    if (lang === "en") await useLocale(page, "en");
    await page.goto("/home");
    await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");

    const text = `فيديو ${unique()}`;
    await page.getByRole("button", { name: T[lang].open }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("textbox", { name: T[lang].open }).fill(text);
    const chooser = page.waitForEvent("filechooser");
    await dialog.getByRole("button", { name: T[lang].addVideo }).click();
    await (await chooser).setFiles(clip);

    // Uploading, then processing (the transcoder), then ready with a preview.
    const attachment = dialog.getByTestId("video-attachment");
    await expect(attachment).toHaveAttribute("data-state", /uploading|processing/);
    await expect(dialog.getByTestId("video-player")).toHaveAttribute("data-state", /processing|ready/, { timeout: 30_000 });
    await expect(attachment).toHaveAttribute("data-state", "ready", { timeout: 120_000 });
    await expect(dialog.getByText(T[lang].ready)).toBeVisible();
    expect(await seriousViolations(page, "[data-testid=video-attachment]")).toEqual([]);

    await dialog.getByTestId("composer-submit").click();
    await expect(dialog).toHaveCount(0);
    const post = page.locator("article").filter({ hasText: text });
    await expect(post).toBeVisible();
    await expectPlaying(page, post);
    expect(await seriousViolations(page, "[data-testid=video-player]")).toEqual([]);
    await expectNoUuid(page);

    // The owner was told the video was ready (notification kind video.ready).
    const api = await apiAs(a);
    await expect
      .poll(async () => {
        const rows = (await (await api.get(`${API}/notifications/`)).json()).data as { kind: string }[];
        return rows.some((n) => n.kind === "video.ready");
      }, { timeout: 30_000 })
      .toBe(true);
    await api.dispose();
  });

  test(`a stranger cannot play a friends-only video (${lang})`, async ({ browser }) => {
    test.setTimeout(240_000);
    const { a, b, c } = await sharedAccounts();
    await befriend(a, b);
    await unfriend(a, c);
    const owner = await apiAs(a);
    const mediaId = await uploadVideo(owner, makeClip(2));
    const created = await owner.post(`${API}/posts/`, {
      data: { body: `للأصدقاء ${unique()}`, type: "video", audience: "friends", media_ids: [mediaId] },
    });
    expect(created.status(), await created.text()).toBe(201);
    const postId = (await created.json()).data.id;

    // The stranger: the post page is not found, and media refuses playback.
    const stranger = await apiAs(c);
    expect((await stranger.get(`${API}/media/${mediaId}/playback/`)).status()).toBe(404);
    expect((await stranger.get(`${API}/media/${mediaId}/`)).status()).toBe(404);
    const strangerPage = await pageAs(browser, c);
    if (lang === "en") await useLocale(strangerPage, "en");
    await strangerPage.goto(`/posts/${postId}`);
    await expect(strangerPage.getByRole("button", { name: lang === "ar" ? "إعادة المحاولة" : "Retry", exact: true })).toBeVisible();
    await expect(strangerPage.getByTestId("video-element")).toHaveCount(0);

    // A friend plays it; the playlist token cannot be reused for another video.
    const friend = await apiAs(b);
    const play = await friend.get(`${API}/media/${mediaId}/playback/`);
    expect(play.status()).toBe(200);
    const hlsPath = (await play.json()).data.hls_url as string;
    const token = new URL(hlsPath, "http://x/").searchParams.get("token");
    expect((await stranger.get(`${API}/media/${mediaId}/hls/master.m3u8?token=${token}x`)).status()).toBe(401);
    const friendPage = await pageAs(browser, b);
    if (lang === "en") await useLocale(friendPage, "en");
    await friendPage.goto(`/posts/${postId}`);
    await expectPlaying(friendPage);

    await Promise.all([owner.dispose(), stranger.dispose(), friend.dispose()]);
  });
}
