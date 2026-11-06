import { createPinia, type Pinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import Toaster from "@/components/common/Toaster.vue";
import { i18n, setLocale } from "@/i18n";
import { api } from "@/lib/api";
import { personalizationOff, resetSignals } from "@/lib/signals";
import { resetRelationshipPrefs } from "@/lib/useRelationshipPrefs";
import type { FeedPreferences, InterestProfile } from "@/services/feed";
import { useAuthStore } from "@/stores/auth";
import MyAlgorithmView from "@/views/MyAlgorithmView.vue";

vi.mock("@/components/layout/AppShell.vue", async () => (await import("./deliveryHarness")).shellStub());

// Tara Intelligence R4 (04 WP 8.2): every My Algorithm control is wired to the real
// preferences API, with an undo toast; 409 reloads; reset is two steps with a 429.

const Blank = defineComponent({ render: () => null });
const ME = "00000000-0000-4000-8000-000000000999";
const HIDDEN = "00000000-0000-4000-8000-000000000301";
let app: App | null = null;
let host: HTMLElement | null = null;
let pinia: Pinia;
let prefs: FeedPreferences;
let profile: InterestProfile;

const base = (): FeedPreferences => ({
  default_mode: "recent",
  version: 4,
  discovery_level: 2,
  languages: [],
  formats: { video: "more" },
  discovery_prefs: { trending: true },
  sensitive_inference: false,
  personalization_off: false,
  search_signal: false,
  onboarded_at: "2026-11-01T10:00:00Z",
  reset_at: null,
  reset_available_at: null,
  debug_consent_expires_at: null,
});

async function flush() {
  for (let i = 0; i < 12; i++) await new Promise((r) => setTimeout(r, 0));
}

function mockGets() {
  return vi.spyOn(api, "get").mockImplementation(async (url: string) => {
    if (url === "/feed/preferences/") return { data: { data: prefs } };
    if (url === "/feed/preferences/profile/") return { data: { data: profile } };
    if (url === "/social/favorites/") return { data: { data: { favorites: [] } } };
    if (url === "/feed/topics/") return { data: { data: [] } };
    return { data: { data: [], page: { next_cursor: null, has_more: false } } };
  });
}

async function mount() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:rest(.*)*", component: Blank }] });
  await router.push("/settings/my-algorithm");
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({ render: () => [h(MyAlgorithmView), h(Toaster)] });
  app.use(pinia).use(router).use(i18n);
  app.mount(host);
  await flush();
  return host;
}
const q = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);

beforeEach(() => {
  pinia = createPinia();
  setActivePinia(pinia);
  localStorage.clear();
  resetRelationshipPrefs();
  resetSignals();
  setLocale("en");
  useAuthStore().account = { id: ME, email: "me@example.com" } as never;
  prefs = base();
  profile = {
    tiers: {},
    muted_topics: [{ slug: "politics", label_ar: "سياسة", label_en: "Politics" }],
    hidden_creators: [{ account_id: HIDDEN, hidden_at: "2026-11-05T00:00:00Z" }],
    sensitive_inference: false,
  };
  mockGets();
  vi.spyOn(api, "post").mockResolvedValue({ data: { data: [] } });
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  document.body.innerHTML = "";
  app = null;
  host = null;
  vi.restoreAllMocks();
  resetSignals();
  setLocale("en");
});

describe("My Algorithm (WP 8.2)", () => {
  it("shows every section from the server's real values", async () => {
    await mount();
    for (const id of ["ma-mode", "ma-formats", "ma-frequency", "ma-discovery", "ma-languages", "ma-interests", "ma-muted", "ma-hidden", "ma-favorites", "ma-privacy", "ma-consent", "ma-reset", "ma-personalization"]) {
      expect(q(id), id).not.toBeNull();
    }
    expect(q("ma-mode-recent")!.getAttribute("aria-checked")).toBe("true");
    expect(q("ma-format-video-more")!.getAttribute("aria-checked")).toBe("true");
    expect(q("ma-format-text-normal")!.getAttribute("aria-checked")).toBe("true");
    expect(q("ma-level-2")!.getAttribute("aria-checked")).toBe("true");
    // Frequency and discovery are two separate groups.
    expect(q("ma-frequency")!.contains(q("ma-discovery-trending"))).toBe(false);
    // Off by default (decisions 7 and 12).
    expect(q("ma-sensitive")!.getAttribute("aria-checked")).toBe("false");
    expect(q("ma-search-signal")!.getAttribute("aria-checked")).toBe("false");
    expect(q("ma-muted")!.textContent).toContain("Politics");
    expect(document.body.textContent).not.toMatch(/\bAI\b|artificial intelligence/i);
  });

  it("PATCHes with the version read and offers Undo through the change id", async () => {
    const patch = vi.spyOn(api, "patch").mockResolvedValue({ data: { data: { ...prefs, version: 5, discovery_level: 3, change_id: "ch-1" } } });
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: { ...prefs, version: 6 } } });
    await mount();
    q("ma-level-3")!.click();
    await flush();
    expect(patch).toHaveBeenCalledWith("/feed/preferences/", { discovery_level: 3, version: 4 });
    expect(q("ma-level-3")!.getAttribute("aria-checked")).toBe("true");
    q("pref-undo")!.click();
    await flush();
    expect(post).toHaveBeenCalledWith("/feed/preferences/undo/", { change_id: "ch-1" });
    expect(q("ma-level-2")!.getAttribute("aria-checked")).toBe("true");
  });

  it("sends a format back to normal by dropping it, and a discovery switch on its own", async () => {
    const patch = vi.spyOn(api, "patch").mockResolvedValue({ data: { data: { ...prefs, version: 5 } } });
    await mount();
    q("ma-format-video-normal")!.click();
    await flush();
    expect(patch).toHaveBeenLastCalledWith("/feed/preferences/", { formats: {}, version: 4 });
    q("ma-discovery-people_suggestions")!.click();
    await flush();
    expect(patch).toHaveBeenLastCalledWith("/feed/preferences/", { discovery_prefs: { trending: true, people_suggestions: false }, version: 5 });
  });

  it("on 409 reloads the preferences and says so", async () => {
    vi.spyOn(api, "patch").mockRejectedValue({ response: { status: 409, data: { error: { code: "conflict" } } } });
    await mount();
    prefs = { ...base(), version: 9, default_mode: "for_you" };
    q("ma-mode-friends")!.click();
    await flush();
    expect(document.body.textContent).toContain("These settings changed in another window");
    expect(q("ma-mode-for_you")!.getAttribute("aria-checked")).toBe("true");
  });

  it("turning personalization off stops collection on this tab", async () => {
    vi.spyOn(api, "patch").mockResolvedValue({ data: { data: { ...prefs, version: 5, personalization_off: true, change_id: "ch-2" } } });
    await mount();
    expect(personalizationOff()).toBe(false);
    q("ma-personalization-off")!.click();
    await flush();
    expect(personalizationOff()).toBe(true);
    expect(q("personalization-off-note")).not.toBeNull();
  });

  it("unmutes a topic and unhides a creator through DELETE", async () => {
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: null });
    await mount();
    q("ma-unmute-politics")!.click();
    await flush();
    expect(del).toHaveBeenCalledWith("/feed/preferences/profile/topic/politics/");
    q(`ma-unhide-${HIDDEN}`)!.click();
    await flush();
    expect(del).toHaveBeenCalledWith(`/feed/preferences/profile/creator/${HIDDEN}/`);
  });

  it("resets in two steps, listing the scope, what stays and that it cannot be undone", async () => {
    const post = vi.spyOn(api, "post").mockImplementation(async (url: string, body?: unknown) => {
      if (url === "/feed/preferences/reset/" && !(body as { confirm_token?: string })?.confirm_token) {
        return { data: { data: { confirm_token: "tok", expires_in_s: 120, scope: ["inferred_interests", "seen_history", "engagement"], keeps: ["explicit_topics", "follows", "blocks"] } } };
      }
      return { data: { data: { reset_at: "2026-11-06T10:00:00Z", next_allowed_at: "2026-11-07T10:00:00Z" } } };
    });
    await mount();
    q("ma-reset-start")!.click();
    await flush();
    const dlg = q("ma-reset-dialog")!;
    expect(q("ma-reset-scope")!.textContent).toContain("Interests learned from your activity");
    expect(q("ma-reset-keeps")!.textContent).toContain("Topics you chose");
    expect(dlg.textContent).toContain("This cannot be undone.");
    q("ma-reset-confirm")!.click();
    await flush();
    expect(post).toHaveBeenCalledWith("/feed/preferences/reset/", { confirm_token: "tok" });
    expect(q("ma-reset-dialog")).toBeNull();
    expect(document.body.textContent).toContain("Your recommendations are starting over.");
  });

  it("shows the next allowed time on 429", async () => {
    vi.spyOn(api, "post").mockRejectedValue({ response: { status: 429, headers: { "retry-after": "3600" }, data: { error: { code: "rate_limited" } } } });
    await mount();
    q("ma-reset-start")!.click();
    await flush();
    expect(q("ma-reset-error")!.textContent).toContain("You can reset again after");
    expect(q("ma-reset-dialog")).toBeNull();
  });

  it("grants and revokes the 24 h support consent", async () => {
    const expires = new Date(Date.now() + 86_400_000).toISOString();
    const post = vi.spyOn(api, "post").mockImplementation(async () => {
      prefs = { ...prefs, debug_consent_expires_at: expires }; // the server now holds it
      return { data: { data: { granted_at: new Date().toISOString(), expires_at: expires } } };
    });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: null });
    await mount();
    q("ma-consent-grant")!.click();
    await flush();
    expect(post).toHaveBeenCalledWith("/feed/preferences/debug-consent/", {});
    expect(q("ma-consent-active")).not.toBeNull();
    q("ma-consent-revoke")!.click();
    await flush();
    expect(del).toHaveBeenCalledWith("/feed/preferences/debug-consent/");
  });

  it("hides the R4 sections on a server that only knows the mode", async () => {
    prefs = { default_mode: null, version: 1 };
    await mount();
    expect(q("ma-mode")).not.toBeNull();
    expect(q("ma-formats")).toBeNull();
    expect(q("ma-reset")).toBeNull();
  });

  it("speaks Arabic, right to left", async () => {
    setLocale("ar");
    await mount();
    expect(document.documentElement.dir).toBe("rtl");
    expect(document.querySelector("h1")!.textContent).toBe("الخوارزمية بتاعتي");
    expect(q("ma-personalization")!.textContent).toContain("اقفل التخصيص");
    expect(q("ma-muted")!.textContent).toContain("سياسة");
  });
});
