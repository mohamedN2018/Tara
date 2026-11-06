import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { type Browser, type Page, expect, request, test } from "@playwright/test";

import { API, BASE_URL, useLocale } from "./helpers";

// Tara Intelligence R3, track B (07 WP 4b.8, brief Part 5.3): infinite scroll on a
// slow connection. What R2's feed-delivery.spec.ts does not already cover: under
// throttled network (Slow 3G-like: 400 ms RTT, 400 kbps) with page 2 failing until
// Retry, three pages load with no duplicate id, and the cumulative layout shift is
// measured and reported against the 0.1 budget. The budget is NOT met yet and is
// reported, not enforced (like R2's critical-JS budget): the remaining shifts come
// from cards growing after they are drawn (snapshot to live post, the comment
// preview a PostCard loads on its own, media boxes), see results/r3-track-b.md.
// E2E_CLS_DEBUG=1 prints each shift with its sources. The viewer is the seeded dev account (many real feed rows); its
// e-mail and password are never printed.

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const NEXT_PAGE = /\/api\/v1\/feed\/\?(?=.*cursor=)(?!.*peek=1)/;
const RETRY = { ar: "حاول تاني", en: "Try again" } as const;

function seedLogin(): { email: string; password: string } {
  const manifest = JSON.parse(readFileSync(join(ROOT, ".seed-state", "manifest.json"), "utf8"));
  const emails = (Object.values(manifest.accounts) as Array<{ email: string }>).map((a) => a.email).sort();
  const src = readFileSync(join(ROOT, "scripts", "seed", "seed_dataset.py"), "utf8");
  const fallback = /DEFAULT_PASSWORD = os\.getenv\("TARA_SEED_PASSWORD", "([^"]+)"\)/.exec(src)?.[1] ?? "";
  // The second seeded account: R2's delivery spec uses the first.
  return { email: emails[1], password: process.env.TARA_SEED_PASSWORD || fallback };
}

let tokens: { access: string; refresh: string } | null = null;
async function seededPage(browser: Browser, lang: "ar" | "en"): Promise<Page> {
  if (!tokens) {
    const anon = await request.newContext();
    const res = await anon.post(`${API}/auth/login/`, { data: seedLogin() });
    expect(res.ok(), "seed account login (is the seed dataset loaded?)").toBe(true);
    const { data } = await res.json();
    tokens = { access: data.access_token, refresh: data.refresh_token };
    await anon.dispose();
  }
  const context = await browser.newContext({ baseURL: BASE_URL, serviceWorkers: "block", viewport: { width: 412, height: 915 } });
  await context.addInitScript(
    ([access, refresh]) => {
      if (sessionStorage.getItem("e2e.seeded")) return;
      sessionStorage.setItem("e2e.seeded", "1");
      localStorage.setItem("tara.access", access);
      localStorage.setItem("tara.refresh", refresh);
    },
    [tokens.access, tokens.refresh],
  );
  // Cumulative layout shift, as the browser reports it (shifts right after input excluded).
  await context.addInitScript(() => {
    const w = window as unknown as { __cls: number; __shifts: string[] };
    w.__cls = 0;
    w.__shifts = [];
    new PerformanceObserver((list) => {
      for (const e of list.getEntries() as Array<PerformanceEntry & { value: number; hadRecentInput: boolean; sources?: Array<{ node?: Node }> }>) {
        if (e.hadRecentInput) continue;
        w.__cls += e.value;
        if (e.value > 0.01) {
          const who = (e.sources ?? []).map((src) => {
            const el = src.node as HTMLElement | undefined;
            const r = src as unknown as { previousRect: DOMRectReadOnly; currentRect: DOMRectReadOnly };
            const name = el?.dataset?.testid ?? el?.dataset?.feedItem?.slice(0, 8) ?? el?.className?.toString().slice(0, 30) ?? el?.nodeName;
            return `${name}@${Math.round(r.previousRect.y)}/${Math.round(r.previousRect.height)}->${Math.round(r.currentRect.y)}/${Math.round(r.currentRect.height)}`;
          });
          w.__shifts.push(`${Math.round(e.startTime)}ms ${e.value.toFixed(3)} ${who.join(" | ")}`);
        }
      }
    }).observe({ type: "layout-shift", buffered: true });
  });
  const page = await context.newPage();
  await useLocale(page, lang);
  return page;
}

for (const lang of ["ar", "en"] as const) {
  test(`slow network (${lang}): page 2 fails until Retry, then 3 pages, no duplicate id; CLS measured`, async ({ browser }) => {
    test.setTimeout(240_000);
    const page = await seededPage(browser, lang);
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Network.enable");
    await cdp.send("Network.emulateNetworkConditions", {
      offline: false,
      latency: 400,
      downloadThroughput: (400 * 1024) / 8,
      uploadThroughput: (400 * 1024) / 8,
    });
    let failing = true;
    const cursors: string[] = [];
    await page.route(NEXT_PAGE, (route) => {
      if (failing) return route.abort("failed");
      cursors.push(new URL(route.request().url()).searchParams.get("cursor") ?? "");
      return route.continue();
    });
    await page.goto("/home?mode=recent");
    await expect(page.locator("[data-feed-item]").first()).toBeVisible({ timeout: 90_000 });

    // Scroll until the next page gives up (R2: 3 automatic retries) and the error row shows.
    const card = page.getByTestId("feed-retry");
    await expect(async () => {
      await page.mouse.wheel(0, 2500);
      await expect(card).toBeVisible({ timeout: 2000 });
    }).toPass({ timeout: 90_000 });
    failing = false;
    await card.getByRole("button", { name: RETRY[lang] }).click();
    await expect(card).toBeHidden({ timeout: 30_000 });

    // Read on through page 3.
    await expect(async () => {
      await page.mouse.wheel(0, 2500);
      expect(new Set(cursors).size).toBeGreaterThanOrEqual(2);
    }).toPass({ timeout: 120_000 });
    await page.waitForTimeout(3000);
    const ids = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>("[data-feed-item]")].map((n) => n.dataset.feedItem ?? ""));
    expect(ids.length).toBeGreaterThan(20);
    expect(new Set(ids).size).toBe(ids.length);
    const cls = await page.evaluate(() => (window as unknown as { __cls: number }).__cls);
    test.info().annotations.push({ type: "cls", description: cls.toFixed(4) });
    if (process.env.E2E_CLS_DEBUG) console.log((await page.evaluate(() => (window as unknown as { __shifts: string[] }).__shifts)).join(" ;; "));
    console.log(`slow network ${lang}: ${ids.length} cards, ${new Set(cursors).size} next pages, CLS ${cls.toFixed(4)}`);
    expect(Number.isFinite(cls)).toBe(true); // budget 0.1: reported above, not enforced yet
    await page.context().close();
  });
}
