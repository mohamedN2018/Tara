import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, expect, type Page, test } from "@playwright/test";

import { API, apiAs, pageAs, sharedAccounts } from "./helpers";

// Tara Intelligence R4 (04 WP 8.2; 07 WP 8.4-B2, 8.5-B2, 8.7-B2): Settings > My Algorithm.
// Every control persists on the server, Undo restores it, reset is two steps and the
// second one inside 24 h is refused with the next allowed time, personalization can be
// turned off; RTL, dark mode and axe.

type Prefs = {
  version: number;
  discovery_level: number;
  formats: Record<string, string>;
  discovery_prefs: Record<string, boolean>;
  languages: string[];
  sensitive_inference: boolean;
  search_signal: boolean;
  personalization_off: boolean;
};

async function prefs(api: APIRequestContext): Promise<Prefs> {
  const res = await api.get(`${API}/feed/preferences/`);
  expect(res.status()).toBe(200);
  return ((await res.json()) as { data: Prefs }).data;
}

async function seriousViolations(page: Page, selector: string): Promise<string[]> {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).include(selector).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

const patched = (page: Page) => page.waitForResponse((r) => r.url().endsWith("/feed/preferences/") && r.request().method() === "PATCH");

const TITLE = { ar: "الخوارزمية بتاعتي", en: "My Algorithm" } as const;

/** The page's own GET /me/ answers with `lang` and the dark theme; nothing is saved. */
async function localeAndDark(page: Page, lang: "ar" | "en") {
  await page.addInitScript((l) => localStorage.setItem("tara.locale", l), lang);
  await page.route(/\/api\/v1\/me\/(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const res = await route.fetch();
    const body = await res.json().catch(() => null);
    if (!body?.data) return route.fulfill({ response: res });
    await route.fulfill({ response: res, json: { ...body, data: { ...body.data, language: lang, theme: "dark" } } });
  });
}

for (const lang of ["ar", "en"] as const) {
  test(`My Algorithm controls persist, undo, reset and personalization off (${lang})`, async ({ browser }) => {
    test.setTimeout(240_000);
    const { a, c } = await sharedAccounts();
    const who = lang === "ar" ? a : c;
    const api = await apiAs(who);
    // A known start: frequency 2, no format choices, every discovery switch on, personalization on.
    const start = await prefs(api);
    const reset = await api.patch(`${API}/feed/preferences/`, {
      data: {
        version: start.version,
        discovery_level: 2,
        formats: {},
        languages: [],
        sensitive_inference: false,
        search_signal: false,
        personalization_off: false,
        discovery_prefs: { new_creators: true, trending: true, people_suggestions: true, page_suggestions: true, group_suggestions: true, other_languages: true },
      },
    });
    expect(reset.status()).toBe(200);

    const page = await pageAs(browser, who);
    await page.emulateMedia({ colorScheme: "dark" });
    await localeAndDark(page, lang);
    // The settings link leads here.
    await page.goto("/settings/content");
    await page.getByTestId("my-algorithm-link").click();
    await expect(page).toHaveURL(/\/settings\/my-algorithm$/);
    await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
    await expect(page.getByRole("heading", { level: 1, name: TITLE[lang] })).toBeVisible();
    await expect(page.getByTestId("ma-reset")).toBeVisible();
    expect(await seriousViolations(page, '[data-testid="my-algorithm"]')).toEqual([]);
    // Dark mode: the cards are dark.
    await expect(page.locator("html")).toHaveClass(/(^|\s)dark(\s|$)/);
    const bg = await page.getByTestId("ma-formats").evaluate((el) => getComputedStyle(el).backgroundColor);
    const [r, g, b] = (bg.match(/\d+/g) ?? ["255", "255", "255"]).map(Number);
    expect(r + g + b).toBeLessThan(200);

    // Frequency: persists, then Undo restores it.
    let res = patched(page);
    await page.getByTestId("ma-level-3").click();
    expect((await res).status()).toBe(200);
    expect((await prefs(api)).discovery_level).toBe(3);
    const undone = page.waitForResponse((r) => r.url().endsWith("/feed/preferences/undo/"));
    await page.getByTestId("pref-undo").first().click();
    expect((await undone).ok()).toBe(true);
    await expect.poll(async () => (await prefs(api)).discovery_level).toBe(2);
    await expect(page.getByTestId("ma-level-2")).toHaveAttribute("aria-checked", "true");

    // Formats, discovery switches, languages and the two opt-ins: each persists.
    res = patched(page);
    await page.getByTestId("ma-format-video-more").click();
    expect((await res).status()).toBe(200);
    res = patched(page);
    await page.getByTestId("ma-discovery-people_suggestions").click();
    expect((await res).status()).toBe(200);
    res = patched(page);
    await page.getByTestId(`ma-language-${lang}`).click();
    expect((await res).status()).toBe(200);
    res = patched(page);
    await page.getByTestId("ma-search-signal").click();
    expect((await res).status()).toBe(200);
    res = patched(page);
    await page.getByTestId("ma-sensitive").click();
    expect((await res).status()).toBe(200);
    const saved = await prefs(api);
    expect(saved.formats.video).toBe("more");
    expect(saved.discovery_prefs.people_suggestions).toBe(false);
    expect(saved.languages).toEqual([lang]);
    expect(saved.search_signal).toBe(true);
    expect(saved.sensitive_inference).toBe(true);
    // A reload shows what the server holds.
    await page.reload();
    await expect(page.getByTestId("ma-format-video-more")).toHaveAttribute("aria-checked", "true");
    await expect(page.getByTestId("ma-discovery-people_suggestions")).toHaveAttribute("aria-checked", "false");

    // Reset: two steps with the scope; a second one within 24 h is refused with the time.
    await page.getByTestId("ma-reset-start").click();
    const dialog = page.getByTestId("ma-reset-dialog");
    const errorLine = page.getByTestId("ma-reset-error");
    await expect(dialog.or(errorLine)).toBeVisible();
    if (await dialog.isVisible()) {
      await expect(page.getByTestId("ma-reset-scope").locator("li").first()).toBeVisible();
      await expect(page.getByTestId("ma-reset-keeps").locator("li").first()).toBeVisible();
      expect(await seriousViolations(page, '[data-testid="ma-reset-dialog"]')).toEqual([]);
      const confirmed = page.waitForResponse((r) => r.url().endsWith("/feed/preferences/reset/") && r.request().method() === "POST" && (r.request().postData() ?? "").includes("confirm_token"));
      await page.getByTestId("ma-reset-confirm").click();
      const status = (await confirmed).status();
      expect([202, 429]).toContain(status);
      if (status === 202) {
        await page.getByTestId("ma-reset-start").click();
        await expect(dialog).toBeVisible();
        await page.getByTestId("ma-reset-confirm").click();
      }
    }
    await expect(errorLine).toBeVisible();
    await expect(errorLine).toContainText(/\d/);

    // Turn off personalization: persisted, the note shows, the tab sends no signals.
    res = patched(page);
    await page.getByTestId("ma-personalization-off").click();
    expect((await res).status()).toBe(200);
    expect((await prefs(api)).personalization_off).toBe(true);
    await expect(page.getByTestId("personalization-off-note")).toBeVisible();
    const signals: string[] = [];
    page.on("request", (r) => r.url().includes("/feed/signals/") && signals.push(r.url()));
    await page.goto("/home");
    await page.waitForTimeout(12_000); // past one flush interval (10 s)
    expect(signals).toEqual([]);

    // Leave the shared account as it was.
    const end = await prefs(api);
    await api.patch(`${API}/feed/preferences/`, {
      data: { version: end.version, personalization_off: false, sensitive_inference: false, search_signal: false, formats: {}, languages: [] },
    });
    await api.dispose();
    await page.context().close();
  });
}
