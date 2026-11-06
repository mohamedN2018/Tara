#!/usr/bin/env node
/*
 * Feed delivery perf harness (Tara Intelligence 08 §11.1, 09 R2, WP 4c-B3).
 *
 * Opens Home on the preview build (`vite preview`, :4173) as a real seeded
 * account and measures what the owner sees: time to the first post, the first
 * image, what the first load fetches, where the next page is asked for, what
 * stays mounted after five batches, repeat media transfers, a forced
 * next-page failure, duplicate ids in the chronological modes, and whether a
 * reload returns to the same card.
 *
 * - The account: a seed account (`.seed-state/manifest.json`, password from
 *   TARA_SEED_PASSWORD or the seed script's documented dev default) picked by
 *   a read-only query on feed_db: the manifest account with the
 *   `--account-rank`-th most feed rows. No account is created; no e-mail,
 *   id or token is printed or written.
 * - Profiles: desktop 1366×900; mobile 390×844 @3x with 4× CPU throttling;
 *   weak 400 kbps / 400 ms RTT + mobile + 4× CPU (CDP).
 * - Every timing run is a new browser context (cold cache, service workers
 *   blocked), n runs, reported as p50 / p90.
 * - Output: JSON under --out, and a table between markers in --results-md.
 *
 *   node scripts/intel/feedperf.cjs --label after --runs 10 \
 *     --out <scratch>/feedperf --results-md docs/intelligence/results/phase-04c.md
 *
 * Needs E2E_CHROMIUM_PATH (the e2e browser) and the dev stack + preview up.
 */
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..", "..");
const { chromium } = require(path.join(ROOT, "frontend", "web", "node_modules", "playwright-core"));

// ---------------------------------------------------------------- arguments
const argv = process.argv.slice(2);
function arg(name, fallback) {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] !== undefined ? argv[i + 1] : fallback;
}
const flag = (name) => argv.includes(`--${name}`);
const BASE = arg("base", process.env.E2E_BASE_URL || "http://127.0.0.1:4173");
const API = arg("api", process.env.E2E_API || "http://127.0.0.1:8080/api/v1");
const RUNS = Number(arg("runs", "10"));
const SCROLL_RUNS = Number(arg("scroll-runs", "3"));
const LABEL = arg("label", "run");
const OUT = path.resolve(arg("out", path.join(os.tmpdir(), "feedperf")));
const RESULTS_MD = arg("results-md", "");
const PROFILES = arg("profiles", "desktop,mobile,weak").split(",").filter(Boolean);
const PARTS = arg("parts", "first,foryou,scroll,failure,dupes,reload").split(",").filter(Boolean);
const RANK = Number(arg("account-rank", "0"));
const EXE = process.env.E2E_CHROMIUM_PATH || undefined;

const PROFILE_DEFS = {
  desktop: { viewport: { width: 1366, height: 900 }, scale: 1, mobile: false, cpu: 1, net: null },
  mobile: { viewport: { width: 390, height: 844 }, scale: 3, mobile: true, cpu: 4, net: null },
  // 400 kbps both ways, 400 ms RTT (08 §11.1 scenario 14).
  weak: { viewport: { width: 390, height: 844 }, scale: 3, mobile: true, cpu: 4, net: { latency: 400, kbps: 400 } },
};

// ---------------------------------------------------------------- helpers
const pct = (xs, p) => {
  const v = xs.filter((x) => typeof x === "number" && Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return null;
  const i = Math.min(v.length - 1, Math.max(0, Math.ceil((p / 100) * v.length) - 1));
  return v[i];
};
const round = (n, d = 0) => (n === null || n === undefined ? null : Math.round(n * 10 ** d) / 10 ** d);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function hostInfo() {
  let docker = "unknown";
  try {
    docker = execFileSync("docker", ["version", "--format", "{{.Server.Version}}"], { encoding: "utf8" }).trim();
  } catch {
    // Docker not reachable from here.
  }
  const cpus = os.cpus();
  return {
    cpu: `${cpus[0]?.model?.trim()} (${cpus.length} logical)`,
    ram_gb: round(os.totalmem() / 1024 ** 3, 1),
    os: `${os.type()} ${os.release()} (${os.platform()} ${os.arch()})`,
    docker,
    node: process.version,
  };
}

function seedPassword() {
  if (process.env.TARA_SEED_PASSWORD) return process.env.TARA_SEED_PASSWORD;
  const src = fs.readFileSync(path.join(ROOT, "scripts", "seed", "seed_dataset.py"), "utf8");
  const m = /DEFAULT_PASSWORD = os\.getenv\("TARA_SEED_PASSWORD", "([^"]+)"\)/.exec(src);
  if (!m) throw new Error("no seed password: set TARA_SEED_PASSWORD");
  return m[1];
}

/** The manifest account with the RANK-th most feed rows (read-only psql in the postgres container). */
function pickAccount() {
  const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, ".seed-state", "manifest.json"), "utf8"));
  const accounts = Object.values(manifest.accounts).filter((a) => a.id && a.email);
  const ids = accounts.map((a) => `'${String(a.id).replace(/[^0-9a-f-]/gi, "")}'`).join(",");
  const sql =
    "BEGIN TRANSACTION READ ONLY; " +
    `SELECT recipient_id FROM feed_item WHERE recipient_id IN (${ids}) GROUP BY recipient_id ORDER BY count(*) DESC, recipient_id LIMIT ${RANK + 1}; COMMIT;`;
  const out = execFileSync(
    "docker",
    ["exec", "tara-postgres-1", "sh", "-c", `psql -U "$POSTGRES_USER" -d feed_db -Atq -c "${sql}"`],
    { encoding: "utf8" },
  )
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => /^[0-9a-f-]{36}$/i.test(l));
  const id = out[RANK];
  const account = accounts.find((a) => a.id === id);
  if (!account) throw new Error("no seeded account with feed rows (is the seed dataset loaded?)");
  return account;
}

let tokenCache = null;
async function tokens(account) {
  if (tokenCache && Date.now() - tokenCache.at < 8 * 60_000) return tokenCache;
  const res = await fetch(`${API}/auth/login/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: account.email, password: seedPassword() }),
  });
  if (!res.ok) throw new Error(`seed account login failed (${res.status})`);
  const { data } = await res.json();
  tokenCache = { access: data.access_token, refresh: data.refresh_token, at: Date.now() };
  return tokenCache;
}

// In-page probes: first post, first image, next-page trigger distance.
const PROBE = () => {
  const w = window;
  w.__perf = { firstPost: null, firstLive: null, firstImage: null, nextPage: [], apiBeforeFirstPost: null };
  const firstPostSel = "[data-feed-item] [data-post-id]";
  const check = () => {
    const p = w.__perf;
    if (p.firstPost === null && document.querySelector(firstPostSel)) p.firstPost = performance.now();
    if (p.firstLive === null && document.querySelector("[data-feed-item] article[data-post-id]")) p.firstLive = performance.now();
  };
  new MutationObserver(check).observe(document, { childList: true, subtree: true, attributes: false });
  document.addEventListener(
    "load",
    (e) => {
      const t = e.target;
      if (w.__perf.firstImage === null && t instanceof HTMLImageElement && t.closest("[data-feed-item] [data-testid='media-grid']")) {
        w.__perf.firstImage = performance.now();
      }
    },
    true,
  );
  const open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    try {
      const u = String(url);
      if (/\/feed\/(\?|$)/.test(u) && /[?&]cursor=/.test(u) && !/peek=1/.test(u)) {
        const left = (document.documentElement.scrollHeight - (window.scrollY + window.innerHeight)) / window.innerHeight;
        w.__perf.nextPage.push({ at: performance.now(), viewportsLeft: Math.round(left * 100) / 100 });
      }
    } catch {
      // Measurement only.
    }
    return open.call(this, method, url, ...rest);
  };
};

async function newPage(browser, profile, account) {
  const def = PROFILE_DEFS[profile];
  const t = await tokens(account);
  const context = await browser.newContext({
    baseURL: BASE,
    viewport: def.viewport,
    deviceScaleFactor: def.scale,
    isMobile: def.mobile,
    hasTouch: def.mobile,
    serviceWorkers: "block",
    locale: "ar-EG",
  });
  await context.addInitScript(
    ([access, refresh]) => {
      try {
        if (!sessionStorage.getItem("perf.seeded")) {
          localStorage.clear();
          localStorage.setItem("tara.access", access);
          localStorage.setItem("tara.refresh", refresh);
          sessionStorage.setItem("perf.seeded", "1");
        }
      } catch {
        // Storage blocked: the run fails visibly.
      }
    },
    [t.access, t.refresh],
  );
  await context.addInitScript(PROBE);
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Performance.enable");
  if (def.cpu > 1) await cdp.send("Emulation.setCPUThrottlingRate", { rate: def.cpu });
  if (def.net) {
    const bps = (def.net.kbps * 1000) / 8;
    await cdp.send("Network.emulateNetworkConditions", {
      offline: false,
      latency: def.net.latency,
      downloadThroughput: bps,
      uploadThroughput: bps,
    });
  }
  // Every request with its encoded (transfer) size, from CDP (counts cache hits as 0).
  const reqs = new Map();
  cdp.on("Network.requestWillBeSent", (e) => {
    reqs.set(e.requestId, { url: e.request.url, method: e.request.method, type: e.type, t: e.timestamp, bytes: 0, cached: false, done: false, status: 0 });
  });
  cdp.on("Network.responseReceived", (e) => {
    const r = reqs.get(e.requestId);
    if (r) {
      r.status = e.response.status;
      r.mime = e.response.mimeType;
      if (e.response.fromDiskCache || e.response.fromServiceWorker || e.response.fromPrefetchCache) r.cached = true;
    }
  });
  cdp.on("Network.requestServedFromCache", (e) => {
    const r = reqs.get(e.requestId);
    if (r) r.cached = true;
  });
  cdp.on("Network.loadingFinished", (e) => {
    const r = reqs.get(e.requestId);
    if (r) {
      r.bytes = e.encodedDataLength;
      r.done = true;
      r.tEnd = e.timestamp;
    }
  });
  return { context, page, cdp, reqs, def };
}

const isApi = (u) => /\/api\/v1\//.test(u);
const isMedia = (u, type) => /\/__s3\//.test(u) || ((type === "Image" || type === "Media") && !/\/assets\/|\/icons\/|fonts\./.test(u));

async function waitFirstPost(page, timeout) {
  await page.waitForFunction(() => window.__perf && window.__perf.firstPost !== null, null, { timeout, polling: 50 });
}

/** One cold first load of /home?mode=: timings and what was fetched. */
async function firstLoad(browser, profile, account, mode) {
  const s = await newPage(browser, profile, account);
  const { page, reqs } = s;
  const timeout = profile === "weak" ? 90_000 : 30_000;
  const t0 = Date.now();
  let feedItems = null;
  page.on("response", async (resp) => {
    const u = resp.url();
    if (feedItems === null && /\/api\/v1\/feed\/\?/.test(u) && !/cursor=|peek=1/.test(u) && resp.request().method() === "GET") {
      try {
        const body = await resp.json();
        feedItems = Array.isArray(body.data) ? body.data.length : null;
      } catch {
        // Not JSON.
      }
    }
  });
  await page.goto(`/home?mode=${mode}`, { waitUntil: "commit", timeout });
  await waitFirstPost(page, timeout);
  const perf = await page.evaluate(() => ({ ...window.__perf, origin: performance.timeOrigin }));
  // Let the first screen settle (images, rails), without scrolling.
  try {
    await page.waitForLoadState("networkidle", { timeout: profile === "weak" ? 30_000 : 10_000 });
  } catch {
    // Long polls or a slow network: measure what is there.
  }
  await sleep(profile === "weak" ? 1500 : 800);
  const perf2 = await page.evaluate(() => ({ ...window.__perf }));
  const vh = PROFILE_DEFS[profile].viewport.height;
  const below = await page.evaluate((h) => {
    const out = { players: 0, playersBelow: 0, videoBelow: 0, posterBelow: 0 };
    document.querySelectorAll("[data-testid='video-player']").forEach((el) => {
      const top = el.getBoundingClientRect().top;
      out.players++;
      if (top > h) {
        out.playersBelow++;
        const v = el.querySelector("video");
        if (v) out.videoBelow++;
        if ((v && v.getAttribute("poster")) || el.querySelector("img[data-poster]")) out.posterBelow++;
      }
    });
    return out;
  }, vh);
  const list = [...reqs.values()];
  // CDP timestamps are seconds (monotonic); the first request is the document.
  // In-page performance.now() maps to CDP time through the document's fetchStart.
  const docT = Math.min(...list.map((r) => r.t));
  const navEntry = await page.evaluate(() => {
    const n = performance.getEntriesByType("navigation")[0];
    return n ? n.fetchStart : 0;
  });
  const toCdp = (pnow) => docT + (pnow - navEntry) / 1000;
  const fp = toCdp(perf.firstPost);
  const before = list.filter((r) => r.t <= fp);
  const scriptsBefore = before.filter((r) => r.type === "Script");
  const apiBefore = before.filter((r) => isApi(r.url));
  const result = {
    profile,
    mode,
    first_post_ms: round(perf.firstPost),
    first_live_ms: round(perf2.firstLive ?? perf.firstLive),
    first_image_ms: round(perf2.firstImage),
    requests: list.length,
    bytes: list.reduce((n, r) => n + (r.bytes || 0), 0),
    api_calls: list.filter((r) => isApi(r.url)).length,
    api_before_first_post: apiBefore.length,
    api_before_first_post_paths: apiBefore.map((r) => new URL(r.url).pathname.replace(/[0-9a-f-]{36}/g, ":id")),
    script_bytes_before_first_post: scriptsBefore.reduce((n, r) => n + (r.bytes || 0), 0),
    scripts_before_first_post: scriptsBefore.length,
    script_bytes_total: list.filter((r) => r.type === "Script").reduce((n, r) => n + (r.bytes || 0), 0),
    bytes_by_type: list.reduce((acc, r) => {
      const k = isApi(r.url) ? "API" : isMedia(r.url, r.type) ? "Media" : r.type || "Other";
      acc[k] = (acc[k] || 0) + (r.bytes || 0);
      return acc;
    }, {}),
    requests_by_type: list.reduce((acc, r) => {
      const k = isApi(r.url) ? "API" : isMedia(r.url, r.type) ? "Media" : r.type || "Other";
      acc[k] = (acc[k] || 0) + 1;
      return acc;
    }, {}),
    media_requests: list.filter((r) => isMedia(r.url, r.type)).length,
    // --dump-media: the media requests by size (paths without signatures), to see what the bytes are.
    ...(flag("dump-media")
      ? { media_list: list.filter((r) => isMedia(r.url, r.type)).sort((x, y) => y.bytes - x.bytes).map((r) => `${r.bytes} ${r.type} ${new URL(r.url).pathname.split("/").slice(-1)[0]}`) }
      : {}),
    media_resolve_calls: list.filter((r) => /\/media\/resolve\//.test(r.url) && r.method === "POST").length,
    playback_calls: list.filter((r) => /\/media\/playback\/resolve\//.test(r.url) && r.method === "POST").length,
    feed_first_page_items: feedItems,
    feed_done_ms: (() => {
      const f = list.find((r) => /\/api\/v1\/feed\/\?/.test(r.url) && !/cursor=|peek=1/.test(r.url) && r.tEnd);
      return f ? round((f.tEnd - docT) * 1000) : null;
    })(),
    ...below,
    wall_ms: Date.now() - t0,
  };
  await s.context.close();
  return result;
}

/** Scroll at one viewport per second through 5 next pages; then count what is mounted. */
async function scrollRun(browser, profile, account, mode = "recent") {
  const s = await newPage(browser, profile, account);
  const { page, reqs, cdp } = s;
  await page.goto(`/home?mode=${mode}`, { waitUntil: "commit" });
  await waitFirstPost(page, 30_000);
  const nextPages = () => [...reqs.values()].filter((r) => /\/api\/v1\/feed\/\?/.test(r.url) && /cursor=/.test(r.url) && r.done).length;
  let steps = 0;
  const waits = [];
  while (nextPages() < 5 && steps < 400) {
    await page.mouse.wheel(0, PROFILE_DEFS[profile].viewport.height);
    steps++;
    await sleep(1000);
    // A visible "loading" stop: the sentinel's skeleton or text is on screen.
    const waiting = await page.evaluate(() => {
      const el = document.querySelector("[data-testid='feed-next-loading'], [data-testid='feed-sentinel'] .text-sm");
      if (!el) return false;
      const r = el.getBoundingClientRect();
      return r.top < window.innerHeight && r.bottom > 0;
    });
    if (waiting) waits.push(steps);
  }
  await sleep(1500);
  await cdp.send("HeapProfiler.collectGarbage").catch(() => {});
  const metrics = Object.fromEntries((await cdp.send("Performance.getMetrics")).metrics.map((m) => [m.name, m.value]));
  const counts = await page.evaluate(() => ({
    dom: document.getElementsByTagName("*").length,
    videos: document.querySelectorAll("video").length,
    items: document.querySelectorAll("[data-feed-item]").length,
    ids: [...document.querySelectorAll("[data-feed-item]")].map((n) => n.getAttribute("data-feed-item")),
    nextPage: window.__perf.nextPage,
  }));
  const list = [...reqs.values()];
  const media = list.filter((r) => isMedia(r.url, r.type));
  // Repeat network transfers of the same media key (path without the signature).
  const byKey = new Map();
  for (const r of media) {
    if (r.cached || !r.bytes) continue;
    let key = r.url;
    try {
      key = new URL(r.url).pathname;
    } catch {
      // Keep the URL.
    }
    byKey.set(key, (byKey.get(key) || 0) + 1);
  }
  const repeats = [...byKey.values()].filter((n) => n > 1).reduce((n, c) => n + (c - 1), 0);
  const ids = counts.ids;
  const result = {
    profile,
    mode,
    next_pages: nextPages(),
    scroll_steps: steps,
    visible_waits: waits.length,
    trigger_viewports_left: counts.nextPage.map((n) => n.viewportsLeft),
    dom_nodes: counts.dom,
    videos_mounted: counts.videos,
    feed_items: counts.items,
    duplicate_ids: ids.length - new Set(ids).size,
    heap_mb: round((metrics.JSHeapUsedSize || 0) / 1024 ** 2, 1),
    media_bytes: media.reduce((n, r) => n + (r.bytes || 0), 0),
    media_requests: media.length,
    media_repeat_transfers: repeats,
  };
  await s.context.close();
  return result;
}

/** The next page fails twice (aborted); does the feed recover by itself within 3 retries? */
async function failureRun(browser, profile, account) {
  const s = await newPage(browser, profile, account);
  const { page } = s;
  let aborted = 0;
  let attempts = 0;
  await page.route(/\/api\/v1\/feed\/\?.*cursor=/, async (route) => {
    attempts++;
    if (aborted < 2) {
      aborted++;
      return route.abort("failed");
    }
    return route.continue();
  });
  await page.goto("/home?mode=recent", { waitUntil: "commit" });
  await waitFirstPost(page, 30_000);
  const before = await page.locator("[data-feed-item]").count();
  const t0 = Date.now();
  let recovered = false;
  for (let i = 0; i < 40 && !recovered; i++) {
    await page.mouse.wheel(0, PROFILE_DEFS[profile].viewport.height * 2);
    await sleep(500);
    recovered = (await page.locator("[data-feed-item]").count()) > before && attempts >= 3;
  }
  const retryCard = await page.locator("[data-testid='feed-retry']").count();
  const result = { profile, aborted, attempts, recovered_without_click: recovered, recovery_ms: recovered ? Date.now() - t0 : null, retry_card_shown: retryCard > 0 };
  await s.context.close();
  return result;
}

/** 6 UI pages per chronological mode: duplicate ids across them. */
async function dupesRun(browser, account) {
  const out = {};
  for (const mode of ["recent", "following", "friends", "favorites"]) {
    const s = await newPage(browser, "desktop", account);
    const { page, reqs } = s;
    await page.goto(`/home?mode=${mode}`, { waitUntil: "commit" });
    try {
      await waitFirstPost(page, 20_000);
    } catch {
      out[mode] = { pages: 0, items: 0, duplicates: 0, note: "no posts in this mode" };
      await s.context.close();
      continue;
    }
    const pages = () => 1 + [...reqs.values()].filter((r) => /\/api\/v1\/feed\/\?/.test(r.url) && /cursor=/.test(r.url) && r.done).length;
    for (let i = 0; i < 200 && pages() < 6; i++) {
      await page.mouse.wheel(0, 1800);
      await sleep(400);
      const end = await page.locator("[data-testid='feed-end']").count();
      if (end) break;
    }
    await sleep(800);
    const ids = await page.evaluate(() => [...document.querySelectorAll("[data-feed-item]")].map((n) => n.getAttribute("data-feed-item")));
    out[mode] = { pages: pages(), items: ids.length, duplicates: ids.length - new Set(ids).size };
    await s.context.close();
  }
  return out;
}

/** Scroll to ~5,600 px in `recent`, reload, and compare the card at the top. */
async function reloadRun(browser, account) {
  const s = await newPage(browser, "desktop", account);
  const { page } = s;
  await page.goto("/home?mode=recent", { waitUntil: "commit" });
  await waitFirstPost(page, 30_000);
  for (let y = 0; y < 5600; y += 700) {
    await page.mouse.wheel(0, 700);
    await sleep(350);
  }
  await sleep(1200);
  const topCard = () =>
    page.evaluate(() => {
      const items = [...document.querySelectorAll("[data-feed-item]")];
      const header = 64;
      const hit = items.find((n) => n.getBoundingClientRect().bottom > header + 8);
      return { id: hit ? hit.getAttribute("data-feed-item") : null, order: items.map((n) => n.getAttribute("data-feed-item")), y: window.scrollY };
    });
  const before = await topCard();
  await page.reload({ waitUntil: "commit" });
  await waitFirstPost(page, 30_000);
  await sleep(4000);
  const after = await topCard();
  const iBefore = before.order.indexOf(before.id);
  const iAfter = before.order.indexOf(after.id);
  const result = {
    scroll_y_before: before.y,
    scroll_y_after: after.y,
    same_card: before.id === after.id,
    card_distance: iBefore >= 0 && iAfter >= 0 ? Math.abs(iAfter - iBefore) : null,
  };
  await s.context.close();
  return result;
}

function summarize(runs, keys) {
  const out = {};
  for (const k of keys) {
    const xs = runs.map((r) => r[k]);
    out[k] = { p50: round(pct(xs, 50), 1), p90: round(pct(xs, 90), 1) };
  }
  return out;
}

function markdown(report) {
  const L = [];
  const h = report.host;
  L.push(`Run \`${report.label}\` on ${report.at}. Host: ${h.cpu}, ${h.ram_gb} GB RAM, ${h.os}, Docker ${h.docker}, Node ${h.node}. Preview ${report.base}; one seeded account (rank ${report.account_rank} by feed rows). n = ${report.runs} cold runs per profile; p50 / p90. Numbers are host-specific.`);
  L.push("");
  L.push("| Profile | Mode | First post ms | First hydrated card ms | First image ms | Requests | Bytes | API before first post | Script KB before first post | /media/resolve/ | Feed items on page 1 | /feed/ done ms |");
  L.push("|---|---|---|---|---|---|---|---|---|---|---|---|");
  for (const f of report.first) {
    const s = f.summary;
    const cell = (k, div = 1, d = 0) => (s[k].p50 === null ? "n/a" : `${round(s[k].p50 / div, d)} / ${round(s[k].p90 / div, d)}`);
    L.push(
      `| ${f.profile} | ${f.mode} | ${cell("first_post_ms")} | ${cell("first_live_ms")} | ${cell("first_image_ms")} | ${cell("requests")} | ${cell("bytes", 1024 * 1024, 2)} MB | ${cell("api_before_first_post")} | ${cell("script_bytes_before_first_post", 1024, 1)} | ${cell("media_resolve_calls")} | ${cell("feed_first_page_items")} | ${cell("feed_done_ms")} |`,
    );
  }
  if (report.first.length) {
    const below = report.first.flatMap((f) => f.runs).map((r) => r.posterBelow + r.videoBelow);
    L.push("");
    L.push(`Players below the first viewport with a <video> or poster requested at first load: max ${Math.max(0, ...below)} over all runs.`);
  }
  if (report.scroll.length) {
    L.push("");
    L.push("| Profile | Next pages | Trigger: viewports left (all triggers) | Visible waits | DOM nodes | <video> mounted | Heap MB | Media MB | Media repeat transfers | Duplicate ids |");
    L.push("|---|---|---|---|---|---|---|---|---|---|");
    for (const r of report.scroll) {
      L.push(
        `| ${r.profile} | ${r.next_pages} | ${r.trigger_viewports_left.join(", ")} | ${r.visible_waits} | ${r.dom_nodes} | ${r.videos_mounted} | ${r.heap_mb} | ${round(r.media_bytes / 1024 ** 2, 2)} | ${r.media_repeat_transfers} | ${r.duplicate_ids} |`,
      );
    }
  }
  if (report.failure.length) {
    L.push("");
    for (const f of report.failure) {
      L.push(`Forced next-page failure (${f.profile}): ${f.aborted} aborted, ${f.attempts} attempts, recovered without a click: ${f.recovered_without_click}${f.recovery_ms ? ` in ${f.recovery_ms} ms` : ""}; retry card shown: ${f.retry_card_shown}.`);
    }
  }
  if (report.dupes) {
    L.push("");
    L.push(`Duplicates over up to 6 UI pages: ${Object.entries(report.dupes).map(([m, d]) => `${m} ${d.duplicates} in ${d.items} items / ${d.pages} pages${d.note ? ` (${d.note})` : ""}`).join("; ")}.`);
  }
  if (report.reload) {
    const r = report.reload;
    L.push("");
    L.push(`Reload at ${r.scroll_y_before} px: back at ${r.scroll_y_after} px, same card: ${r.same_card}, distance ${r.card_distance === null ? "n/a (card not found)" : `${r.card_distance} card(s)`}.`);
  }
  return L.join("\n");
}

function writeResults(report) {
  if (!RESULTS_MD) return;
  const file = path.resolve(ROOT, RESULTS_MD);
  const start = `<!-- feedperf:${report.label}:start -->`;
  const end = `<!-- feedperf:${report.label}:end -->`;
  const block = `${start}\n${markdown(report)}\n${end}`;
  let text = fs.existsSync(file) ? fs.readFileSync(file, "utf8") : "";
  if (text.includes(start) && text.includes(end)) {
    text = text.slice(0, text.indexOf(start)) + block + text.slice(text.indexOf(end) + end.length);
  } else text = `${text.trimEnd()}\n\n${block}\n`;
  fs.writeFileSync(file, text);
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const account = pickAccount();
  const browser = await chromium.launch({ executablePath: EXE, headless: true });
  const report = { label: LABEL, at: new Date().toISOString(), base: BASE, runs: RUNS, account_rank: RANK, host: hostInfo(), first: [], scroll: [], failure: [], dupes: null, reload: null };
  const firstKeys = ["first_post_ms", "first_live_ms", "first_image_ms", "requests", "bytes", "api_before_first_post", "script_bytes_before_first_post", "media_resolve_calls", "feed_first_page_items", "feed_done_ms", "playback_calls"];
  try {
    for (const profile of PROFILES) {
      const modes = [];
      if (PARTS.includes("first")) modes.push("recent");
      if (PARTS.includes("foryou") && profile !== "weak") modes.push("for_you");
      for (const mode of modes) {
        const runs = [];
        for (let i = 0; i < RUNS; i++) {
          try {
            runs.push(await firstLoad(browser, profile, account, mode));
          } catch (e) {
            runs.push({ profile, mode, error: String(e && e.message ? e.message.split("\n")[0] : e) });
          }
          process.stdout.write(".");
        }
        report.first.push({ profile, mode, runs, summary: summarize(runs, firstKeys), errors: runs.filter((r) => r.error).length });
        console.log(` ${profile}/${mode}`, JSON.stringify(summarize(runs, ["first_post_ms", "first_image_ms", "bytes", "requests"])));
      }
      if (PARTS.includes("scroll") && profile !== "weak") {
        for (let i = 0; i < SCROLL_RUNS; i++) {
          try {
            report.scroll.push(await scrollRun(browser, profile, account));
          } catch (e) {
            console.log("scroll run failed:", String(e && e.message ? e.message.split("\n")[0] : e));
          }
        }
      }
      if (PARTS.includes("failure") && profile !== "mobile") {
        try {
          report.failure.push(await failureRun(browser, profile, account));
        } catch (e) {
          console.log("failure run failed:", String(e && e.message ? e.message.split("\n")[0] : e));
        }
      }
    }
    if (PARTS.includes("dupes")) report.dupes = await dupesRun(browser, account);
    if (PARTS.includes("reload")) report.reload = await reloadRun(browser, account);
  } finally {
    await browser.close();
  }
  const file = path.join(OUT, `feedperf-${LABEL}-${Date.now()}.json`);
  fs.writeFileSync(file, JSON.stringify(report, null, 2));
  writeResults(report);
  console.log(markdown(report));
  console.log(`\nJSON: ${file}`);
})().catch((e) => {
  console.error(e && e.stack ? e.stack.split("\n").slice(0, 3).join("\n") : e);
  process.exit(1);
});
