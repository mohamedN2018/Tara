import AxeBuilder from "@axe-core/playwright";
import { expect, request, test } from "@playwright/test";

import { API, fillRegisterForm, PASSWORD, REGISTER_LABELS, unique, verificationToken } from "./helpers";

// Tara Intelligence WP 6.6 (owner decision 11): after sign-up, the first sign-in offers an
// optional topic picker with real topics from feed (at most 10) and Skip; once done (or
// skipped) it never shows again, and the picks become the account's own interests.

const L = {
  ar: { title: "إيه اللي بيهمّك؟", submit: REGISTER_LABELS.ar.submit, login: "دخول", created: "تم إنشاء الحساب" },
  en: { title: "What are you into?", submit: REGISTER_LABELS.en.submit, login: "Log in", created: "Account created" },
} as const;

for (const lang of ["ar", "en"] as const) {
  test(`the optional topic picker after sign-up (${lang})`, async ({ browser, baseURL }) => {
    test.setTimeout(180_000);
    const l = L[lang];
    const tag = unique();
    const handle = `onb_${lang}_${tag}`;
    const email = `e2e_${handle}@example.com`;
    const context = await browser.newContext({ baseURL });
    await context.addInitScript((x) => localStorage.setItem("tara.locale", x), lang);
    const page = await context.newPage();

    await page.goto("/register");
    await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
    await fillRegisterForm(page, { first: lang === "ar" ? "منى" : "Mona", last: tag, handle, email }, lang);
    await page.getByRole("button", { name: l.submit, exact: true }).click();
    await expect(page.getByText(l.created)).toBeVisible();

    const mailpit = await request.newContext();
    const token = await verificationToken(mailpit, email);
    expect((await mailpit.post(`${API}/auth/verify-email/`, { data: { token } })).ok()).toBe(true);
    await mailpit.dispose();

    await page.goto("/login");
    await page.locator('input[autocomplete="username"]').fill(email);
    await page.locator('input[autocomplete="current-password"]').fill(PASSWORD);
    await page.locator('form button[type="submit"]').click();
    await expect(page).toHaveURL(/\/welcome\/topics/);
    const picker = page.getByTestId("onboarding-topics");
    await expect(picker).toBeVisible();
    await expect(page.getByRole("heading", { level: 1, name: l.title })).toBeVisible();
    const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).include('[data-testid="onboarding-topics"]').analyze();
    expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);

    // Real topics from the server, never a sensitive one.
    const tokenRes = await (await request.newContext()).post(`${API}/auth/login/`, { data: { email, password: PASSWORD } });
    const access = ((await tokenRes.json()) as { data: { access_token: string } }).data.access_token;
    const api = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${access}` } });
    const served = ((await (await api.get(`${API}/feed/topics/`, { params: { limit: 60 } })).json()) as { data: { slug: string; sensitive: boolean }[] }).data;
    const offered = await picker.locator('[data-testid^="onboarding-topic-"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")!.replace("onboarding-topic-", "")));
    expect(offered.length).toBeGreaterThan(0);
    const sensitive = new Set(served.filter((t) => t.sensitive).map((t) => t.slug));
    expect(offered.filter((s) => sensitive.has(s))).toEqual([]);
    expect(offered.every((s) => served.some((t) => t.slug === s))).toBe(true);

    if (lang === "ar") {
      // Pick two and continue: they become explicit interests.
      const picks = offered.slice(0, 2);
      for (const slug of picks) await picker.getByTestId(`onboarding-topic-${slug}`).click();
      await expect(picker.getByTestId("onboarding-count")).toContainText("2");
      const posted = page.waitForResponse((r) => r.url().endsWith("/feed/preferences/onboarding/"));
      await picker.getByTestId("onboarding-done").click();
      expect((await posted).ok()).toBe(true);
      await expect(page).toHaveURL(/\/home$/);
      const profile = ((await (await api.get(`${API}/feed/preferences/profile/`)).json()) as { data: { tiers: { explicit?: { key: string }[] } } }).data;
      expect((profile.tiers.explicit ?? []).map((r) => r.key).sort()).toEqual([...picks].sort());
    } else {
      const posted = page.waitForResponse((r) => r.url().endsWith("/feed/preferences/onboarding/"));
      await picker.getByTestId("onboarding-skip").click();
      expect((await posted).ok()).toBe(true);
      await expect(page).toHaveURL(/\/home$/);
    }
    const prefs = ((await (await api.get(`${API}/feed/preferences/`)).json()) as { data: { onboarded_at: string | null } }).data;
    expect(prefs.onboarded_at).toBeTruthy();
    // Shown once: opening it again goes straight on.
    await page.goto("/welcome/topics?next=/home");
    await expect(page).toHaveURL(/\/home$/);
    await api.dispose();
    await context.close();
  });
}
