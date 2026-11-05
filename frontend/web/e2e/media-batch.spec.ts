import { type APIRequestContext, type Browser, type Page, expect, request, test } from "@playwright/test";

import { API, BASE_URL, useLocale } from "./helpers";

// Media lookups in batches (final audit, gap 1 and section c). A /home load used
// to fire about 200 `GET /media/<id>/` calls, one per image; dozens came back
// 429 and the tiles stayed blank. Now the page resolves its images in a few
// `POST /media/resolve/` calls (videos in `POST /media/playback/resolve/`), the
// profile asks `sellers/<id>/shop/` (always 200) instead of the seller page
// (404 for most people), and a default ad button reads in the page's language.
//
// Runs against the seeded dataset (scripts/seed): read only, nothing is created.

const SEED_PASSWORD = process.env.TARA_SEED_PASSWORD ?? "Seed-Tara-2026!";
const SEED_EMAIL = process.env.E2E_SEED_EMAIL ?? "seed.esraa_elsayed.001@example.com";
const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const SINGLE_LOOKUP = new RegExp(`/api/v1/media/${UUID}/(playback/)?(\\?.*)?$`);
const SELLER_PAGE = new RegExp(`/api/v1/marketplace/sellers/${UUID}/(\\?.*)?$`);

async function seedTokens(): Promise<{ access: string; refresh: string; id: string }> {
  const anon = await request.newContext();
  const res = await anon.post(`${API}/auth/login/`, { data: { email: SEED_EMAIL, password: SEED_PASSWORD } });
  test.skip(!res.ok(), `the seeded dataset is not loaded (login ${res.status()})`);
  const { data } = await res.json();
  await anon.dispose();
  const id = JSON.parse(Buffer.from(data.access_token.split(".")[1], "base64url").toString()).sub as string;
  return { access: data.access_token, refresh: data.refresh_token, id };
}

async function seedPage(browser: Browser, lang: "ar" | "en") {
  const tokens = await seedTokens();
  const context = await browser.newContext({ baseURL: BASE_URL });
  await context.addInitScript(
    ([access, refresh]) => {
      if (localStorage.getItem("e2e.seeded")) return;
      localStorage.setItem("e2e.seeded", "1");
      localStorage.setItem("tara.access", access);
      localStorage.setItem("tara.refresh", refresh);
    },
    [tokens.access, tokens.refresh],
  );
  const page = await context.newPage();
  await useLocale(page, lang);
  const api = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${tokens.access}` } });
  return { page, api, me: tokens.id };
}

/** Every API call the page makes, and the ones rate limited or failed. */
function recordTraffic(page: Page) {
  const traffic = { single: [] as string[], batches: [] as string[], limited: [] as string[], sellerPage: [] as string[], errors: [] as string[] };
  page.on("request", (req) => {
    const url = req.url();
    if (SINGLE_LOOKUP.test(url)) traffic.single.push(url);
    if (/\/api\/v1\/media\/(playback\/)?resolve\/$/.test(url)) traffic.batches.push(url);
    if (SELLER_PAGE.test(url)) traffic.sellerPage.push(url);
  });
  page.on("response", (res) => {
    if (!res.url().includes("/api/v1/")) return;
    if (res.status() === 429) traffic.limited.push(res.url());
    else if (res.status() >= 500) traffic.errors.push(`${res.status()} ${res.url()}`);
  });
  return traffic;
}

/** How many storage images on the page actually decoded. */
const loadedImages = (page: Page) =>
  page.locator('img[src^="/__s3/"], img[src*="/tara-media/"]').evaluateAll((imgs) =>
    imgs.filter((img) => (img as HTMLImageElement).complete && (img as HTMLImageElement).naturalWidth > 0).length,
  );

async function scrollThrough(page: Page, steps = 4) {
  for (let i = 0; i < steps; i++) {
    await page.mouse.wheel(0, 1400);
    await page.waitForTimeout(500);
  }
  await page.waitForTimeout(800);
}

async function aSellerWithPhotos(api: APIRequestContext): Promise<string | null> {
  const res = await api.get(`${API}/marketplace/listings/`);
  if (!res.ok()) return null;
  const listings = ((await res.json()).data ?? []) as { seller_id: string; media?: unknown[] }[];
  return listings.find((l) => l.media?.length)?.seller_id ?? listings[0]?.seller_id ?? null;
}

for (const lang of ["ar", "en"] as const) {
  test(`home, a profile and marketplace show their images with batched lookups and no 429 (${lang})`, async ({ browser }) => {
    test.setTimeout(150_000);
    const { page, api, me } = await seedPage(browser, lang);
    const traffic = recordTraffic(page);

    // Home: dozens of images and avatars, a handful of batch calls.
    await page.goto("/home");
    await expect(page.locator("[data-feed-item]").first()).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => loadedImages(page), { timeout: 30_000 }).toBeGreaterThan(3);
    await scrollThrough(page);
    const homeImages = await loadedImages(page);
    const homeBatches = traffic.batches.length;
    expect(homeImages).toBeGreaterThan(3);
    expect(traffic.single, "per-image lookups").toEqual([]);
    expect(homeBatches).toBeGreaterThan(0);
    expect(homeBatches).toBeLessThan(25);

    // A default ad button reads in the page's language, whatever the advertiser saved.
    const ads = page.getByTestId("sponsored");
    if ((await ads.count()) > 0) {
      const ctas = await ads.locator("button.btn-primary").allTextContents();
      if (lang === "ar") expect(ctas.map((c) => c.trim())).not.toContain("Learn more");
      else expect(ctas.map((c) => c.trim())).not.toContain("اعرف المزيد");
    }

    // A seller's profile: images, and the shop check never asks the seller page.
    const seller = (await aSellerWithPhotos(api)) ?? me;
    const shopChecks: number[] = [];
    page.on("response", (res) => {
      if (/\/marketplace\/sellers\/[^/]+\/shop\/$/.test(res.url())) shopChecks.push(res.status());
    });
    await page.goto(`/u/id/${seller}`);
    await expect(page.getByTestId("profile-tab-posts")).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => shopChecks.length, { timeout: 15_000 }).toBeGreaterThan(0);
    expect(shopChecks.every((s) => s === 200)).toBe(true);
    if (seller !== me) await expect(page.getByTestId("profile-tab-marketplace")).toBeVisible();
    await expect.poll(() => loadedImages(page), { timeout: 30_000 }).toBeGreaterThan(0);
    // My own profile too: no shop, still a 200 and no seller-page 404.
    await page.goto(`/u/id/${me}`);
    await expect(page.getByTestId("profile-tab-posts")).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => shopChecks.length, { timeout: 15_000 }).toBeGreaterThan(1);
    expect(shopChecks.every((s) => s === 200)).toBe(true);

    // Marketplace: listing photos.
    await page.goto("/marketplace");
    await expect(page.getByTestId("listing-card").first()).toBeVisible({ timeout: 30_000 });
    await scrollThrough(page, 2);
    await expect.poll(() => loadedImages(page), { timeout: 30_000 }).toBeGreaterThan(0);

    expect(traffic.single, "per-image lookups").toEqual([]);
    expect(traffic.sellerPage, "seller page asked by a profile").toEqual([]);
    expect(traffic.limited, "rate-limited calls").toEqual([]);
    expect(traffic.errors, "server errors").toEqual([]);
    test.info().annotations.push({
      type: "traffic",
      description: `home images ${homeImages}, home batches ${homeBatches}, total batches ${traffic.batches.length}, 429s ${traffic.limited.length}`,
    });
    console.log(`[media-batch ${lang}] home images ${homeImages}, home batches ${homeBatches}, total batches ${traffic.batches.length}, 429s ${traffic.limited.length}`);

    await api.dispose();
    await page.context().close();
  });
}

test("the batch endpoints follow the single endpoints' rules", async () => {
  const { access } = await seedTokens();
  const api = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${access}` } });
  const anon = await request.newContext();
  try {
    expect((await anon.post(`${API}/media/resolve/`, { data: { ids: [] } })).status()).toBe(401);
    expect((await api.post(`${API}/media/resolve/`, { data: { ids: ["not-a-uuid"] } })).status()).toBe(400);
    const tooMany = Array.from({ length: 101 }, () => crypto.randomUUID());
    expect((await api.post(`${API}/media/resolve/`, { data: { ids: tooMany } })).status()).toBe(400);
    // Unknown ids are simply absent, for media and for playback.
    const unknown = (await (await api.post(`${API}/media/resolve/`, { data: { ids: [crypto.randomUUID()] } })).json()).data;
    expect(unknown).toEqual([]);
    const noVideo = (await (await api.post(`${API}/media/playback/resolve/`, { data: { ids: [crypto.randomUUID()] } })).json()).data;
    expect(noVideo).toEqual([]);
    // Unknown sellers: 200 and no shop, where the seller page is a 404.
    const stranger = crypto.randomUUID();
    expect((await api.get(`${API}/marketplace/sellers/${stranger}/`)).status()).toBe(404);
    const shop = await api.get(`${API}/marketplace/sellers/${stranger}/shop/`);
    expect(shop.status()).toBe(200);
    expect((await shop.json()).data).toEqual({ has_shop: false });
  } finally {
    await api.dispose();
    await anon.dispose();
  }
});
