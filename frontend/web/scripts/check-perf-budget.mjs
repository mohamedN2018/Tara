#!/usr/bin/env node
// Critical-JS budget check (Tara Intelligence 08 §7.13, WP 4c.10-B3).
//
// Reads the Vite build manifest and sums the compressed transfer size of the
// JavaScript needed to render Home's first card: the entry chunk (which holds
// the router) and its static imports, plus the Home route chunk (HomeView,
// whose static imports carry the PostCard path) and its static imports. Lazy
// chunks (dynamic imports) are not counted: they load after the first post or
// on demand. Fails (exit 1) when the gzip sum is over `critical_js_kb` of
// perf-budget.json.
//
// Transfer size is gzip at level 5, the level nginx.conf serves with
// (`gzip_comp_level 5`); brotli and the decoded size are printed too.
//
//   node scripts/check-perf-budget.mjs [--dist dist] [--json]
import { existsSync, readFileSync } from "node:fs";
import process from "node:process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { brotliCompressSync, constants, gzipSync } from "node:zlib";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const dist = resolve(root, opt("--dist", "dist"));
const asJson = args.includes("--json");

const budget = JSON.parse(readFileSync(join(root, "perf-budget.json"), "utf8"));
const manifestPath = [join(dist, ".vite", "manifest.json"), join(dist, "manifest.json")].find(existsSync);
if (!manifestPath) {
  console.error(`perf-budget: no Vite manifest under ${dist} (build.manifest must be on; run the build first)`);
  process.exit(2);
}
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));

// The critical roots: the HTML entry, and the Home route (the post-login landing view).
const HOME_ROUTE = "src/views/HomeView.vue";
const entryKey = Object.keys(manifest).find((k) => manifest[k].isEntry);
if (!entryKey) {
  console.error("perf-budget: the manifest has no entry chunk");
  process.exit(2);
}
if (!manifest[HOME_ROUTE]) {
  console.error(`perf-budget: ${HOME_ROUTE} is not a chunk of its own (is the Home route still lazy?)`);
  process.exit(2);
}

const seen = new Set();
function walk(key) {
  if (seen.has(key)) return;
  const chunk = manifest[key];
  if (!chunk) return;
  seen.add(key);
  for (const dep of chunk.imports ?? []) walk(dep); // static imports only
}
walk(entryKey);
walk(HOME_ROUTE);

const rows = [...seen]
  .map((key) => manifest[key].file)
  .filter((file, i, all) => file.endsWith(".js") && all.indexOf(file) === i)
  .map((file) => {
    const bytes = readFileSync(join(dist, file));
    return {
      file,
      raw: bytes.length,
      gzip: gzipSync(bytes, { level: 5 }).length,
      brotli: brotliCompressSync(bytes, { params: { [constants.BROTLI_PARAM_QUALITY]: 11 } }).length,
    };
  })
  .sort((a, b) => b.gzip - a.gzip);

const sum = (k) => rows.reduce((n, r) => n + r[k], 0);
const kb = (n) => Math.round((n / 1024) * 10) / 10;
const total = { raw: sum("raw"), gzip: sum("gzip"), brotli: sum("brotli") };
const ok = total.gzip <= budget.critical_js_kb * 1024;
const result = {
  budget_kb: budget.critical_js_kb,
  budget_version: budget.version,
  chunks: rows.length,
  raw_kb: kb(total.raw),
  gzip_kb: kb(total.gzip),
  brotli_kb: kb(total.brotli),
  // At 400 kbps (scenario 14) every KB of transfer costs 8 / 400 s, before any RTT.
  gzip_seconds_at_400kbps: Math.round(((total.gzip * 8) / 400_000) * 100) / 100,
  ok,
  files: rows.map((r) => ({ ...r, raw: kb(r.raw), gzip: kb(r.gzip), brotli: kb(r.brotli) })),
};

if (asJson) console.log(JSON.stringify(result, null, 2));
else {
  for (const r of result.files) console.log(`${String(r.gzip).padStart(7)} KB gz  ${String(r.raw).padStart(7)} KB raw  ${r.file}`);
  console.log(
    `critical JS: ${result.gzip_kb} KB gzip (brotli ${result.brotli_kb} KB, decoded ${result.raw_kb} KB) in ${result.chunks} chunks; budget ${result.budget_kb} KB -> ${ok ? "OK" : "OVER BUDGET"}`,
  );
}
process.exit(ok ? 0 : 1);
