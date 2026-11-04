// Settings fix track A: the Blocked list names who you blocked, the 2FA QR
// code, "Delete account" with re-authentication and the grouped login activity.
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApp, nextTick, type App, type Component } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import ContentPreferences from "@/components/settings/ContentPreferences.vue";
import DeleteAccount from "@/components/settings/DeleteAccount.vue";
import LoginActivity from "@/components/settings/LoginActivity.vue";
import TwoFactorSettings from "@/components/settings/TwoFactorSettings.vue";
import { i18n, setLocale } from "@/i18n";
import { api } from "@/lib/api";
import { clearBlockedCards } from "@/lib/blockedCards";
import { resetRelationshipPrefs } from "@/lib/useRelationshipPrefs";
import { graphService } from "@/services/graph";
import { identityService } from "@/services/identity";
import { profileService } from "@/services/profile";
import { useAuthStore } from "@/stores/auth";

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const Blank = { render: () => null };

let app: App | null = null;
let host: HTMLElement;

async function mount(component: Component, path = "/settings/content") {
  const router = createRouter({
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
  setLocale("en");
  resetRelationshipPrefs();
  clearBlockedCards();
  useAuthStore().account = { id: "me", email: "me@example.com", email_verified: true, status: "active", language: "en", theme: "dark" };
});

afterEach(() => {
  app?.unmount();
  app = null;
  host?.remove();
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

describe("Blocked list", () => {
  it("names the people you blocked from your own block list, without a profile link", async () => {
    vi.spyOn(graphService, "blockedIds").mockResolvedValue(["b1", "b2"]);
    const shared = vi.spyOn(profileService, "lookup").mockResolvedValue([]);
    const post = vi.spyOn(api, "post").mockResolvedValue({
      data: { data: [{ account_id: "b1", handle: "pest", display_name: "Pest Person", avatar_media_id: null }] },
    });
    await mount(ContentPreferences, "/settings/content#blocks");
    await flush();
    expect(post).toHaveBeenCalledWith("/profile/me/blocked/lookup/", { ids: ["b1", "b2"] });
    const names = [...host.querySelectorAll("[data-testid=content-row-name]")].map((n) => n.textContent?.trim());
    expect(names).toEqual(["Pest Person", i18n.global.t("profile.unknownUser")]);
    expect(host.querySelector("[data-testid=content-row] a")).toBeNull();
    // Blocked people never go through the shared directory.
    expect(shared).not.toHaveBeenCalledWith(expect.arrayContaining(["b1"]));
  });
});

describe("two-factor QR code", () => {
  it("shows a scannable QR next to the setup key", async () => {
    vi.spyOn(identityService, "twoFactor").mockResolvedValue({ enabled: false, method: null, enabled_at: null, recovery_codes_remaining: 0 });
    vi.spyOn(identityService, "startTwoFactor").mockResolvedValue({
      secret: "JBSWY3DPEHPK3PXP",
      otpauth_uri: "otpauth://totp/Tara:me%40example.com?secret=JBSWY3DPEHPK3PXP&issuer=Tara",
      digits: 6,
      period: 30,
    });
    await mount(TwoFactorSettings, "/settings/security");
    q<HTMLButtonElement>("[data-testid=two-factor-turn-on]").click();
    await nextTick();
    const password = q<HTMLInputElement>("input[type=password]");
    password.value = "pw";
    password.dispatchEvent(new Event("input"));
    q<HTMLFormElement>("[data-testid=two-factor-reauth]").dispatchEvent(new Event("submit"));
    await vi.waitFor(() => expect(q("[data-testid=two-factor-qr]")).not.toBeNull(), { timeout: 3000 });
    const img = q<HTMLImageElement>("[data-testid=two-factor-qr]");
    expect(img.getAttribute("src")).toMatch(/^data:image\/svg\+xml;charset=utf-8,/);
    expect(decodeURIComponent(img.getAttribute("src")!.split(",")[1])).toContain("<svg");
    expect(img.getAttribute("alt")).toBe(i18n.global.t("settingsCenter.twoFactor.qrAlt"));
  });
});

describe("Delete account", () => {
  it("re-authenticates, confirms, schedules the deletion and signs out", async () => {
    vi.spyOn(identityService, "security").mockResolvedValue({ has_password: true } as never);
    const remove = vi.spyOn(identityService, "deleteAccount").mockResolvedValue({ deletion_scheduled_for: "2026-12-04T10:00:00Z" });
    const logout = vi.spyOn(useAuthStore(), "logout").mockResolvedValue();
    await mount(DeleteAccount, "/settings/account");
    expect(q("[data-testid=delete-account]").textContent).toContain("30 days");
    const password = q<HTMLInputElement>("input[type=password]");
    password.value = "pw";
    password.dispatchEvent(new Event("input"));
    q<HTMLFormElement>("[data-testid=delete-account] form").dispatchEvent(new Event("submit"));
    await nextTick();
    const dialog = document.querySelector("[data-testid=confirm-action]") as HTMLElement;
    expect(dialog).not.toBeNull();
    const buttons = dialog.querySelectorAll("button");
    (buttons[buttons.length - 1] as HTMLButtonElement).click();
    await flush();
    expect(remove).toHaveBeenCalledWith("pw", "");
    expect(logout).toHaveBeenCalledWith({ remote: false });
  });

  it("asks a Google-only account to type DELETE", async () => {
    vi.spyOn(identityService, "security").mockResolvedValue({ has_password: false } as never);
    const remove = vi.spyOn(identityService, "deleteAccount").mockResolvedValue({ deletion_scheduled_for: "2026-12-04T10:00:00Z" });
    await mount(DeleteAccount, "/settings/account");
    expect(q("input[type=password]")).toBeNull();
    const word = q<HTMLInputElement>("[data-testid=delete-account] input");
    word.value = "nope";
    word.dispatchEvent(new Event("input"));
    q<HTMLFormElement>("[data-testid=delete-account] form").dispatchEvent(new Event("submit"));
    await nextTick();
    expect(document.querySelector("[data-testid=confirm-action]")).toBeNull();
    expect(remove).not.toHaveBeenCalled();
  });
});

describe("Login activity", () => {
  it("groups repeats and shows five groups until Show more", async () => {
    const row = (i: number, type: string, region = "") => ({ id: `e${i}`, type, ip_region: region, created_at: `2026-11-0${(i % 9) + 1}T10:00:00Z` });
    const rows = [
      ...Array.from({ length: 12 }, (_, i) => row(i, "login_succeeded")),
      row(20, "login_failed"),
      row(21, "password_changed"),
      row(22, "login_succeeded", "EG"),
      row(23, "login_failed"),
      row(24, "login_succeeded"),
      row(25, "two_factor_enabled"),
    ];
    const fetch = vi.spyOn(identityService, "securityActivity").mockResolvedValue({ results: rows, next: "c2" });
    await mount(LoginActivity, "/settings/security");
    expect(host.querySelectorAll("[data-testid=activity-row]")).toHaveLength(5);
    expect(q("[data-testid=activity-count]").textContent?.trim()).toBe("×12");
    expect(host.textContent).not.toContain("—");

    q<HTMLButtonElement>("[data-testid=activity-more]").click();
    await nextTick();
    expect(host.querySelectorAll("[data-testid=activity-row]")).toHaveLength(7);
    expect(fetch).toHaveBeenCalledTimes(1);
    q<HTMLButtonElement>("[data-testid=activity-more]").click();
    await flush();
    expect(fetch).toHaveBeenLastCalledWith("c2");
  });
});
