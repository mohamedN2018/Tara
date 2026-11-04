// Settings & privacy centre (track T1): server-synced display preferences,
// relationship privacy, the content-preference lists, two-factor setup and the
// section routing.
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApp, nextTick, type App, type Component } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

import ContentPreferences from "@/components/settings/ContentPreferences.vue";
import RelationshipPrivacySettings from "@/components/settings/RelationshipPrivacySettings.vue";
import { isSettingsSection, LEGACY_HASH } from "@/components/settings/sections";
import TwoFactorSettings from "@/components/settings/TwoFactorSettings.vue";
import { i18n, setLocale } from "@/i18n";
import { resetRelationshipPrefs } from "@/lib/useRelationshipPrefs";
import { feedService } from "@/services/feed";
import { graphService } from "@/services/graph";
import { identityService } from "@/services/identity";
import { relationshipsService } from "@/services/relationships";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const Blank = { render: () => null };

let app: App | null = null;
let host: HTMLElement;
let router: Router;

async function mount(component: Component, path = "/settings/content") {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/settings/:section?", component: Blank },
      { path: "/u/id/:id", name: "profile-by-id", component: Blank },
    ],
  });
  await router.push(path);
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp(component);
  app.use(router).use(i18n);
  app.mount(host);
  await flush();
  await flush();
}

const q = <T extends Element = HTMLElement>(sel: string) => host.querySelector(sel) as T;

beforeEach(() => {
  setActivePinia(createPinia());
  localStorage.removeItem("tara.prefs.pending");
  setLocale("en");
  resetRelationshipPrefs();
  useAuthStore().account = { id: "me", email: "me@example.com", email_verified: true, status: "active", language: "en", theme: "dark" };
});

afterEach(() => {
  app?.unmount();
  app = null;
  host?.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("display preferences follow the account", () => {
  it("saves theme and language with PATCH /me/ once signed in, in order", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
    const patch = vi.spyOn(identityService, "updateAccount").mockResolvedValue({} as never);
    const ui = useUiStore();
    ui.setTheme("light"); // signed out: local only
    await flush();
    expect(patch).not.toHaveBeenCalled();

    // The choice made while signed out is pending: it wins once and is saved.
    ui.applyAccount({ language: "en", theme: "dark" });
    expect(ui.theme).toBe("light");
    await flush();
    expect(patch.mock.calls).toEqual([[{ theme: "light" }]]);
    patch.mockClear();

    ui.setTheme("dark");
    ui.changeLocale("ar");
    await flush();
    expect(patch.mock.calls).toEqual([[{ theme: "dark" }], [{ language: "ar" }]]);
    ui.changeLocale("en");
    await flush();
  });

  it("takes the account's values on every sign-in, even after this browser chose before", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
    vi.spyOn(identityService, "updateAccount").mockResolvedValue({} as never);
    const ui = useUiStore();
    ui.init(); // writes tara.locale, as every boot does
    ui.applyAccount({ language: "ar", theme: "dark" });
    ui.changeLocale("en"); // saved to the account on this device
    await flush();
    // Device B changed both since: the next boot here follows the account.
    ui.applyAccount({ language: "ar", theme: "system" });
    expect(ui.locale).toBe("ar");
    expect(ui.theme).toBe("system"); // an explicit "system" syncs too
    expect(localStorage.getItem("tara.prefs.pending")).toBeNull();
  });

  it("stops saving to the account once signed out", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
    const patch = vi.spyOn(identityService, "updateAccount").mockResolvedValue({} as never);
    const ui = useUiStore();
    ui.applyAccount({ language: "en", theme: "dark" });
    ui.applyAccount(null);
    ui.setTheme("light");
    ui.changeLocale("ar");
    await flush();
    expect(patch).not.toHaveBeenCalled();
    ui.changeLocale("en");
  });

  it("keeps a failed save pending and sends it at the next sign-in", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
    const patch = vi.spyOn(identityService, "updateAccount").mockRejectedValueOnce(new Error("offline"));
    const ui = useUiStore();
    ui.applyAccount({ language: "en", theme: "dark" });
    ui.setTheme("light");
    await flush();
    patch.mockResolvedValue({} as never);
    ui.applyAccount({ language: "en", theme: "dark" });
    expect(ui.theme).toBe("light");
    await flush();
    expect(patch.mock.calls.at(-1)).toEqual([{ theme: "light" }]);
    expect(localStorage.getItem("tara.prefs.pending")).toBeNull();
  });
});

describe("RelationshipPrivacySettings", () => {
  it("loads the four choices and saves one change", async () => {
    vi.spyOn(relationshipsService, "settings").mockResolvedValue({
      friends_list_visibility: "public",
      follow_lists_visibility: "friends",
      counts_visibility: "public",
      friend_requests_from: "everyone",
    });
    const update = vi.spyOn(relationshipsService, "updateSettings").mockImplementation(async (c) => ({
      friends_list_visibility: "only_me",
      follow_lists_visibility: "friends",
      counts_visibility: "public",
      friend_requests_from: "everyone",
      ...c,
    }));
    setActivePinia(createPinia());
    await mount(RelationshipPrivacySettings);
    const select = q<HTMLSelectElement>("[data-testid=privacy-friends_list_visibility]");
    expect(select.value).toBe("public");
    expect(host.querySelectorAll("select")).toHaveLength(4);
    select.value = "only_me";
    select.dispatchEvent(new Event("change"));
    await flush();
    expect(update).toHaveBeenCalledWith({ friends_list_visibility: "only_me" });
  });
});

describe("ContentPreferences", () => {
  it("lists favorites, switches tabs and removes an entry", async () => {
    vi.spyOn(relationshipsService, "list").mockImplementation(async (kind) => (kind === "favorites" ? ["u1", "u2"] : ["u3"]));
    const remove = vi.spyOn(relationshipsService, "remove").mockResolvedValue();
    vi.spyOn(graphService, "blockedIds").mockResolvedValue([]);
    await mount(ContentPreferences, "/settings/content#favorites");
    expect(host.querySelectorAll("[data-testid=content-row]")).toHaveLength(2);

    q<HTMLButtonElement>("[data-testid=content-tab-mutes]").click();
    await flush();
    await flush();
    expect(q("[data-testid=content-tab-mutes]").getAttribute("aria-selected")).toBe("true");
    expect(router.currentRoute.value.hash).toBe("#mutes");
    const rows = host.querySelectorAll("[data-testid=content-row]");
    expect(rows).toHaveLength(1);
    (rows[0].querySelector("button") as HTMLButtonElement).click();
    await flush();
    expect(remove).toHaveBeenCalledWith("mutes", "u3");
    expect(host.querySelectorAll("[data-testid=content-row]")).toHaveLength(0);
    expect(q("[data-testid=content-empty]").textContent).toContain(i18n.global.t("settingsCenter.content.empty.mutes"));
  });

  it("shows snoozes with their end date and ends one", async () => {
    vi.spyOn(feedService, "snoozes").mockResolvedValue({
      data: [{ author_id: "u9", until: "2026-12-01T00:00:00Z", snoozed_at: "2026-11-01T00:00:00Z" }],
      page: { next_cursor: null, prev_cursor: null, has_more: false },
    });
    const unsnooze = vi.spyOn(feedService, "unsnooze").mockResolvedValue();
    await mount(ContentPreferences, "/settings/content#snoozed");
    expect(host.querySelectorAll("[data-testid=content-row]")).toHaveLength(1);
    (host.querySelector("[data-testid=content-row] button") as HTMLButtonElement).click();
    await flush();
    expect(unsnooze).toHaveBeenCalledWith("u9");
  });
});

describe("TwoFactorSettings", () => {
  it("re-authenticates, shows the key, confirms and shows the recovery codes once", async () => {
    vi.spyOn(identityService, "twoFactor").mockResolvedValue({
      enabled: false,
      method: null,
      enabled_at: null,
      recovery_codes_remaining: 0,
    });
    const start = vi.spyOn(identityService, "startTwoFactor").mockResolvedValue({
      secret: "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
      otpauth_uri: "otpauth://totp/Tara:me%40example.com?secret=JBSWY3DPEHPK3PXP&issuer=Tara",
      digits: 6,
      period: 30,
    });
    const confirm = vi.spyOn(identityService, "confirmTwoFactor").mockResolvedValue({
      enabled: true,
      method: "totp",
      enabled_at: "2026-11-04T10:00:00Z",
      recovery_codes_remaining: 10,
      recovery_codes: Array.from({ length: 10 }, (_, i) => `code-${i}`),
    });
    await mount(TwoFactorSettings, "/settings/security");
    expect(q("[data-testid=two-factor-status]").textContent?.trim()).toBe("Off");

    q<HTMLButtonElement>("[data-testid=two-factor-turn-on]").click();
    await nextTick();
    const password = q<HTMLInputElement>("input[type=password]");
    password.value = "pw";
    password.dispatchEvent(new Event("input"));
    q<HTMLFormElement>("[data-testid=two-factor-reauth]").dispatchEvent(new Event("submit"));
    await flush();
    expect(start).toHaveBeenCalledWith("pw");
    expect(q("[data-testid=two-factor-key]").textContent).toBe("JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP");

    const code = q<HTMLInputElement>("input[autocomplete=one-time-code]");
    code.value = "123456";
    code.dispatchEvent(new Event("input"));
    await nextTick();
    q<HTMLFormElement>("[data-testid=two-factor-setup]").dispatchEvent(new Event("submit"));
    await flush();
    expect(confirm).toHaveBeenCalledWith("123456");
    expect(host.querySelectorAll("[data-testid=recovery-codes] li")).toHaveLength(10);
    expect(useAuthStore().account?.two_factor_enabled).toBe(true);

    q<HTMLButtonElement>("[data-testid=recovery-codes-done]").click();
    await nextTick();
    expect(host.querySelector("[data-testid=recovery-codes]")).toBeNull();
    expect(q("[data-testid=two-factor-status]").textContent?.trim()).toBe("On");
  });
});

describe("settings sections", () => {
  it("knows its sections and maps the old one-page anchors", () => {
    expect(isSettingsSection("privacy")).toBe(true);
    expect(isSettingsSection("billing")).toBe(false);
    expect(LEGACY_HASH.notifications).toEqual({ section: "notifications" });
    expect(LEGACY_HASH.tags).toEqual({ section: "privacy", hash: "#tags" });
  });
});
