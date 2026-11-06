import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter, type Router, RouterView } from "vue-router";

import OnboardingTopics from "@/components/feed/OnboardingTopics.vue";
import { i18n, setLocale } from "@/i18n";
import { api } from "@/lib/api";
import { afterSignIn, markTopicsToPick, topicsToPick } from "@/lib/onboarding";
import OnboardingTopicsView from "@/views/OnboardingTopicsView.vue";

// Tara Intelligence WP 6.6 (owner decision 11): an optional picker after sign-up, real
// topics from the server, at most 10, and Skip.

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;
let done: boolean[] = [];

async function flush() {
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
}

const topics = (n: number) =>
  Array.from({ length: n }, (_, i) => ({ slug: `t${i}`, label_ar: `موضوع ${i}`, label_en: `Topic ${i}`, sensitive: i === n - 1 }));

async function mountPicker() {
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({ render: () => h(OnboardingTopics, { onDone: (skipped: boolean) => done.push(skipped) }) });
  app.use(createPinia()).use(i18n);
  app.mount(host);
  await flush();
  return host;
}

async function mountView(path: string): Promise<{ el: HTMLElement; router: Router }> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/welcome/topics", component: OnboardingTopicsView },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push(path);
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({ render: () => h(RouterView) });
  app.use(createPinia()).use(router).use(i18n);
  app.mount(host);
  await flush();
  return { el: host, router };
}

const q = (el: ParentNode, id: string) => el.querySelector<HTMLElement>(`[data-testid="${id}"]`);

beforeEach(() => {
  setActivePinia(createPinia());
  localStorage.clear();
  setLocale("en");
  done = [];
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.restoreAllMocks();
  setLocale("en");
});

describe("topic picker after sign-up (WP 6.6)", () => {
  it("lists the server's topics without sensitive ones and caps picks at 10", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: topics(13) } });
    const el = await mountPicker();
    const list = q(el, "onboarding-list")!;
    expect(list.querySelectorAll("button")).toHaveLength(12); // the sensitive one is left out
    for (let i = 0; i < 11; i++) q(el, `onboarding-topic-t${i}`)!.click();
    await flush();
    expect(q(el, "onboarding-count")!.textContent).toContain("10 of 10 picked");
    expect(q(el, "onboarding-topic-t10")!.hasAttribute("disabled")).toBe(true);
    expect(q(el, "onboarding-topic-t0")!.getAttribute("aria-pressed")).toBe("true");
  });

  it("posts the picks, or an empty skipped choice", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: topics(4) } });
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: {} } });
    let el = await mountPicker();
    expect(q(el, "onboarding-done")!.hasAttribute("disabled")).toBe(true);
    q(el, "onboarding-topic-t1")!.click();
    q(el, "onboarding-topic-t2")!.click();
    await flush();
    q(el, "onboarding-done")!.click();
    await flush();
    expect(post).toHaveBeenLastCalledWith("/feed/preferences/onboarding/", { topics: ["t1", "t2"], skipped: false });
    app?.unmount();
    host?.remove();
    el = await mountPicker();
    q(el, "onboarding-skip")!.click();
    await flush();
    expect(post).toHaveBeenLastCalledWith("/feed/preferences/onboarding/", { topics: [], skipped: true });
    expect(done).toEqual([false, true]);
  });

  it("can still be skipped when topics fail to load", async () => {
    vi.spyOn(api, "get").mockRejectedValue(new Error("down"));
    vi.spyOn(api, "post").mockResolvedValue({ data: {} });
    const el = await mountPicker();
    expect(el.querySelector('[role="alert"]')).not.toBeNull();
    q(el, "onboarding-skip")!.click();
    await flush();
    expect(done).toEqual([true]);
  });

  it("shows only once: an onboarded account goes straight on", async () => {
    markTopicsToPick("acc-1");
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: { default_mode: null, version: 2, onboarded_at: "2026-11-01T00:00:00Z" } } });
    const { el, router } = await mountView("/welcome/topics?next=/home");
    expect(q(el, "onboarding-topics")).toBeNull();
    expect(router.currentRoute.value.fullPath).toBe("/home");
    expect(topicsToPick("acc-1")).toBe(false);
  });

  it("is shown while onboarded_at is null", async () => {
    vi.spyOn(api, "get").mockImplementation(async (url: string) =>
      url === "/feed/preferences/" ? { data: { data: { default_mode: null, version: 1, onboarded_at: null } } } : { data: { data: topics(3) } },
    );
    const { el } = await mountView("/welcome/topics");
    expect(q(el, "onboarding-topics")).not.toBeNull();
  });

  it("routes a new account's first sign-in through the picker", () => {
    expect(afterSignIn("acc-2", "/home")).toBe("/home");
    markTopicsToPick("acc-2");
    expect(afterSignIn("acc-2", "/home")).toEqual({ path: "/welcome/topics", query: { next: "/home" } });
    expect(afterSignIn("someone-else", "/home")).toBe("/home");
  });

  it("speaks Arabic, right to left", async () => {
    setLocale("ar");
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: topics(2) } });
    const el = await mountPicker();
    expect(document.documentElement.dir).toBe("rtl");
    expect(el.querySelector("h1")!.textContent).toBe("إيه اللي بيهمّك؟");
    expect(q(el, "onboarding-skip")!.textContent?.trim()).toBe("تخطّي");
  });
});
