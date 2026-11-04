// Full registration (plan 08, track 1D): the strength meter and the sign-up
// form's validation messages, client side and from the server's codes.
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApp, h, nextTick, type App } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import PasswordStrength from "@/components/auth/PasswordStrength.vue";
import { i18n, setLocale } from "@/i18n";
import { api } from "@/lib/api";
import { profileToComplete } from "@/lib/completeProfile";
import { PRIVACY_VERSION, TERMS_VERSION } from "@/lib/legal";
import { passwordStrength } from "@/lib/passwordStrength";
import { identityService } from "@/services/identity";
import { profileService } from "@/services/profile";
import RegisterView from "@/views/RegisterView.vue";

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const Blank = { render: () => null };

let app: App | null = null;
let host: HTMLElement;

async function mount(component: object, props: Record<string, unknown> = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: Blank },
      { path: "/register", component: Blank },
      { path: "/login", component: Blank },
      { path: "/home", component: Blank },
      { path: "/legal/:doc", component: Blank },
    ],
  });
  await router.push("/register");
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({ render: () => h(component, props) });
  app.use(pinia).use(router).use(i18n);
  app.mount(host);
  await flush();
}

const $ = <T extends Element = HTMLInputElement>(selector: string) => host.querySelector(selector) as T;

async function type(selector: string, value: string) {
  const input = $(selector);
  input.value = value;
  input.dispatchEvent(new Event("input"));
  await nextTick();
}

async function choose(selector: string, value: string) {
  const select = $<HTMLSelectElement>(selector);
  select.value = value;
  select.dispatchEvent(new Event("change"));
  await nextTick();
}

async function check(selector: string) {
  const box = $(selector);
  box.checked = true;
  box.dispatchEvent(new Event("change"));
  await nextTick();
}

async function fillValid(password = "Str0ng-Pass-987!") {
  await type("#reg-first-name", "Laila");
  await type("#reg-last-name", "Ahmed");
  await type("#reg-email", "laila@example.com");
  await type("#reg-password", password);
  await type("#reg-password-confirm", password);
  await choose("#reg-dob-day", "14");
  await choose("#reg-dob-month", "3");
  await choose("#reg-dob-year", "1995");
  await check("#reg-consent");
}

async function submit() {
  $<HTMLFormElement>("form").dispatchEvent(new Event("submit", { cancelable: true }));
  await flush();
  await nextTick();
}

const text = () => host.textContent ?? "";

beforeEach(() => {
  setLocale("en");
  vi.spyOn(identityService, "providers").mockResolvedValue({ google: { enabled: false, client_id: "" } } as never);
});

afterEach(() => {
  app?.unmount();
  app = null;
  host?.remove();
  localStorage.clear();
  vi.useRealTimers();
});

// ---- the scoring ----------------------------------------------------------------

describe("passwordStrength", () => {
  it("calls anything under 10 characters too short, as the server does", () => {
    expect(passwordStrength("Ab1!xyz")).toMatchObject({ score: 0, label: "tooShort", acceptable: false });
    expect(passwordStrength("Ab1!xyz").tips).toContain("length");
  });

  it("refuses numbers only", () => {
    expect(passwordStrength("1234567890123")).toMatchObject({ score: 0, acceptable: false });
  });

  it("marks common words, sequences and the person's own details as weak", () => {
    expect(passwordStrength("MyPassword2024!")).toMatchObject({ score: 1, acceptable: false });
    expect(passwordStrength("Zabcdef!9xy")).toMatchObject({ score: 1 });
    const own = passwordStrength("Laila-Rocks-77", ["laila@example.com"]);
    expect(own).toMatchObject({ score: 1, acceptable: false });
    expect(own.tips).toContain("personal");
  });

  it("grows with length and variety", () => {
    expect(passwordStrength("plainlowercase").score).toBe(1);
    expect(passwordStrength("Plainlowercase7").score).toBe(3);
    expect(passwordStrength("Str0ng-Pass-987!")).toMatchObject({ score: 4, label: "strong", acceptable: true });
  });

  it("counts Arabic letters as their own kind", () => {
    expect(passwordStrength("كلمةسرطويلة42").score).toBeGreaterThan(passwordStrength("كلمةسرطويلةجدا").score);
  });
});

describe("PasswordStrength", () => {
  it("shows nothing for an empty password", async () => {
    await mount(PasswordStrength, { password: "" });
    expect($("[data-testid=password-strength]")).toBeNull();
  });

  it("names the level and the most useful tip, in the current language", async () => {
    await mount(PasswordStrength, { password: "short" });
    const meter = $("[data-testid=password-strength]");
    expect(meter.getAttribute("data-score")).toBe("0");
    expect(meter.textContent).toContain("Password strength: Too short");
    expect(meter.textContent).toContain("Use at least 10 characters.");
    app?.unmount();
    host.remove();
    setLocale("ar");
    await mount(PasswordStrength, { password: "Str0ng-Pass-987!" });
    expect($("[data-testid=password-strength]").textContent).toContain("قوة كلمة المرور: قوية");
  });
});

// ---- the form ---------------------------------------------------------------------

describe("RegisterView", () => {
  it("says the passwords don't match before sending anything", async () => {
    const post = vi.spyOn(api, "post");
    await mount(RegisterView);
    await fillValid();
    await type("#reg-password-confirm", "Str0ng-Pass-988!");
    expect(text()).toContain("The passwords don't match.");
    await submit();
    expect(post).not.toHaveBeenCalled();
    expect($("#reg-password-confirm").getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement?.id).toBe("reg-password-confirm");
  });

  it("asks for consent before sending", async () => {
    const post = vi.spyOn(api, "post");
    await mount(RegisterView);
    await fillValid();
    const box = $("#reg-consent");
    box.checked = false;
    box.dispatchEvent(new Event("change"));
    await submit();
    expect(post).not.toHaveBeenCalled();
    expect(text()).toContain("Accept the terms and the privacy policy to continue.");
  });

  it("refuses an impossible date and an incomplete one", async () => {
    await mount(RegisterView);
    await fillValid();
    await choose("#reg-dob-day", "30");
    await choose("#reg-dob-month", "2");
    await submit();
    expect(text()).toContain("Enter your real date of birth.");
    await choose("#reg-dob-year", "");
    await submit();
    expect(text()).toContain("Choose your day, month and year of birth.");
  });

  it("needs the words for a custom gender", async () => {
    await mount(RegisterView);
    await fillValid();
    await check("#reg-gender-custom");
    await submit();
    expect(text()).toContain("Describe your gender, or pick another option.");
  });

  it("sends every field with the legal versions it showed", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({
      data: { data: { account_id: "acc-1", email: "laila@example.com", status: "pending" } },
    });
    await mount(RegisterView);
    await fillValid();
    await check("#reg-gender-female");
    await submit();
    expect(post).toHaveBeenCalledWith("/auth/register/", {
      first_name: "Laila",
      last_name: "Ahmed",
      handle: "",
      email: "laila@example.com",
      password: "Str0ng-Pass-987!",
      password_confirm: "Str0ng-Pass-987!",
      date_of_birth: "1995-03-14",
      gender: "female",
      gender_custom: "",
      accept_terms: true,
      terms_version: TERMS_VERSION,
      privacy_version: PRIVACY_VERSION,
      language: "en",
    });
    expect(text()).toContain("Account created.");
    expect(profileToComplete("acc-1")).toBe(true);
  });

  it.each([
    ["password_confirm", "password_mismatch", "#reg-password-confirm", "The passwords don't match."],
    ["date_of_birth", "age_below_minimum", "#reg-dob-day", "You're not old enough to join Tara yet."],
    ["accept_terms", "consent_required", "#reg-consent", "Accept the terms and the privacy policy to continue."],
    ["terms_version", "legal_version_mismatch", "#reg-consent", "The terms have changed."],
    ["handle", "reserved_handle", "#reg-handle", "This username isn't available."],
  ])("shows the server's %s / %s on its field", async (field, code, selector, message) => {
    vi.spyOn(api, "post").mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 400,
        data: { error: { code: "validation_error", message: "x", details: [{ field, code, message: "x" }] } },
      },
    });
    await mount(RegisterView);
    await fillValid();
    await submit();
    expect(text()).toContain(message);
    expect(text()).toContain("Check the highlighted fields.");
    expect(document.activeElement).toBe($(selector));
  });

  it("checks the username while typing, after a pause, and blocks a taken one", async () => {
    const lookup = vi
      .spyOn(profileService, "handleAvailable")
      .mockResolvedValue({ handle: "taken_one", available: false, reason: "unavailable" });
    const post = vi.spyOn(api, "post");
    await mount(RegisterView);
    vi.useFakeTimers();
    await type("#reg-handle", "tak");
    await type("#reg-handle", "taken_one");
    expect($("[data-testid=handle-status]").textContent).toContain("Checking…");
    await vi.advanceTimersByTimeAsync(450);
    expect(lookup).toHaveBeenCalledTimes(1); // debounced: only the last value
    expect(lookup.mock.calls[0][0]).toBe("taken_one");
    expect($("[data-testid=handle-status]").getAttribute("data-state")).toBe("taken");
    expect(text()).toContain("This username isn't available. Try another.");
    vi.useRealTimers();
    await fillValid();
    await submit();
    expect(post).not.toHaveBeenCalled();
  });

  it("says when a username is free", async () => {
    vi.spyOn(profileService, "handleAvailable").mockResolvedValue({
      handle: "free_one",
      available: true,
      reason: null,
    });
    await mount(RegisterView);
    vi.useFakeTimers();
    await type("#reg-handle", "Free_One");
    await vi.advanceTimersByTimeAsync(450);
    expect($("[data-testid=handle-status]").textContent).toContain("@free_one is available.");
  });
});
