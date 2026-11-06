import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import ReportList from "@/components/moderation/ReportList.vue";
import { i18n, setLocale } from "@/i18n";
import { api } from "@/lib/api";

// Tara Intelligence WP 7.4: a system-sourced report (feed's integrity signal) reads
// "system signal, not a user report" and names no reporter; user reports are unchanged.

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;

async function flush() {
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
}

const ROWS = [
  {
    id: "r-sys",
    reporter_id: null,
    source: "system",
    target_type: "post",
    target_id: "00000000-0000-4000-8000-000000000001",
    reason: "spam_hides",
    evidence: { signal: "spam_hides", rate: 0.4, distinct_accounts: 6 },
    created_at: "2026-11-06T09:00:00Z",
  },
  {
    id: "r-user",
    reporter_id: "00000000-0000-4000-8000-000000000077",
    source: "user",
    target_type: "post",
    target_id: "00000000-0000-4000-8000-000000000001",
    reason: "spam",
    evidence: {},
    created_at: "2026-11-06T09:05:00Z",
  },
];

async function mount() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:rest(.*)*", component: Blank }] });
  await router.push("/admin/moderation");
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({ render: () => h(ReportList, { caseId: "c1" }) });
  app.use(createPinia()).use(router).use(i18n);
  app.mount(host);
  await flush();
  return host;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.spyOn(api, "get").mockResolvedValue({ data: { data: ROWS, page: { next_cursor: null, has_more: false } } });
  vi.spyOn(api, "post").mockResolvedValue({ data: { data: [] } });
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.restoreAllMocks();
  setLocale("en");
});

describe.each([
  ["en", "System signal, not a user report", "Many people hid this post as spam", "From 6 different accounts"],
  ["ar", "إشارة من النظام، مش بلاغ من مستخدم", "ناس كتير خبّت البوست ده على إنه سبام", "من 6 حساب مختلف"],
] as const)("system-sourced report (%s)", (lang, label, signal, distinct) => {
  it("labels the signal, shows no reporter, and leaves user reports alone", async () => {
    setLocale(lang);
    const el = await mount();
    const [sys, user] = [...el.querySelectorAll<HTMLElement>('[data-testid="report-row"]')];
    expect(sys.querySelector('[data-testid="report-system"]')!.textContent?.trim()).toBe(label);
    expect(sys.querySelector('[data-testid="report-system-signal"]')!.textContent).toBe(signal);
    expect(sys.textContent).toContain(distinct);
    expect(sys.querySelector('[data-testid="report-reporter"]')).toBeNull();
    // No percentage is shown for the rate.
    expect(sys.textContent).not.toContain("%");
    expect(user.querySelector('[data-testid="report-system"]')).toBeNull();
    expect(user.querySelector('[data-testid="report-reporter"]')).not.toBeNull();
    if (lang === "ar") expect(document.documentElement.dir).toBe("rtl");
  });
});
