import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApp, nextTick, type App } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

import LoginCard from "@/components/auth/LoginCard.vue";
import { i18n, setLocale } from "@/i18n";
import { api } from "@/lib/api";
import { browserSessionEnded, forgetSignIn, rememberSignIn } from "@/lib/rememberMe";
import { tokenStore } from "@/lib/tokens";
import { identityService } from "@/services/identity";
import { useAuthStore } from "@/stores/auth";

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const Blank = { render: () => null };
let app: App | null = null;
let host: HTMLElement;
let router: Router;

async function mountCard(path = "/") {
  const pinia = createPinia();
  setActivePinia(pinia);
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: Blank },
      { path: "/home", component: Blank },
      { path: "/settings", component: Blank },
      { path: "/register", component: Blank },
      { path: "/forgot-password", component: Blank },
    ],
  });
  await router.push(path);
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp(LoginCard, { title: "Log in to Tara" });
  app.use(pinia).use(router).use(i18n);
  app.mount(host);
  await flush();
  return useAuthStore();
}

function field(selector: string) {
  return host.querySelector(selector) as HTMLInputElement;
}

async function type(input: HTMLInputElement, value: string) {
  input.value = value;
  input.dispatchEvent(new Event("input"));
  await nextTick();
}

beforeEach(() => {
  setLocale("en");
  // No Google sign-in in these tests.
  vi.spyOn(identityService, "providers").mockResolvedValue({ google: { enabled: false, client_id: "" } } as never);
});

afterEach(() => {
  app?.unmount();
  app = null;
  host?.remove();
  forgetSignIn();
  localStorage.clear();
});

describe("LoginCard", () => {
  it("labels the field as email or username", async () => {
    await mountCard();
    const label = host.querySelector(`label[for="${field("input[autocomplete=username]").id}"]`);
    expect(label?.textContent).toContain("Email or username");
    expect(field("input[autocomplete=username]").type).toBe("text");
  });

  it("shows and hides the password with aria-pressed", async () => {
    await mountCard();
    const password = field("input[autocomplete=current-password]");
    const toggle = host.querySelector("[data-testid=toggle-password]") as HTMLButtonElement;
    expect(password.type).toBe("password");
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(toggle.getAttribute("aria-controls")).toBe(password.id);
    expect(toggle.type).toBe("button"); // never submits the form

    toggle.click();
    await nextTick();
    expect(password.type).toBe("text");
    expect(toggle.getAttribute("aria-pressed")).toBe("true");

    toggle.click();
    await nextTick();
    expect(password.type).toBe("password");
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
  });

  it("sends the identifier, the password and an unticked remember", async () => {
    const auth = await mountCard("/?redirect=/settings");
    const login = vi.spyOn(auth, "login").mockResolvedValue();
    await type(field("input[autocomplete=username]"), "  sara_k ");
    await type(field("input[autocomplete=current-password]"), "Str0ng-Pass-987!");
    const remember = field("input[type=checkbox]");
    expect(remember.checked).toBe(true); // ticked by default
    remember.click();
    await nextTick();

    host.querySelector("form")!.dispatchEvent(new Event("submit"));
    await flush();
    expect(login).toHaveBeenCalledWith("sara_k", "Str0ng-Pass-987!", false);
    expect(router.currentRoute.value.fullPath).toBe("/settings");
  });

  it("sends remember=true when left ticked, and honours ?next=", async () => {
    const auth = await mountCard("/?next=/settings");
    const login = vi.spyOn(auth, "login").mockResolvedValue();
    await type(field("input[autocomplete=username]"), "sara@example.com");
    await type(field("input[autocomplete=current-password]"), "Str0ng-Pass-987!");
    host.querySelector("form")!.dispatchEvent(new Event("submit"));
    await flush();
    expect(login).toHaveBeenCalledWith("sara@example.com", "Str0ng-Pass-987!", true);
    expect(router.currentRoute.value.fullPath).toBe("/settings");
  });

  it("shows one generic message for a failed sign-in", async () => {
    const auth = await mountCard();
    vi.spyOn(auth, "login").mockRejectedValue({
      response: { status: 401, data: { error: { code: "authentication_failed", message: "x" } } },
    });
    await type(field("input[autocomplete=username]"), "nobody_here");
    await type(field("input[autocomplete=current-password]"), "wrong");
    host.querySelector("form")!.dispatchEvent(new Event("submit"));
    await flush();
    expect(host.querySelector("[role=alert]")?.textContent).toBe(i18n.global.t("loginCard.invalid"));
    expect(router.currentRoute.value.fullPath).toBe("/");
  });
});

describe("auth store login", () => {
  it("posts identifier and remember to the API", async () => {
    setActivePinia(createPinia());
    const post = vi.spyOn(api, "post").mockRejectedValue(new Error("stop here"));
    await expect(useAuthStore().login("sara_k", "pw", false)).rejects.toThrow("stop here");
    expect(post).toHaveBeenCalledWith("/auth/login/", { identifier: "sara_k", password: "pw", remember: false });
  });

  it("boot ends a session-only sign-in once the browser has closed, and revokes it", async () => {
    setActivePinia(createPinia());
    tokenStore.set("a.b.c", "refresh-1");
    rememberSignIn(false);
    document.cookie = "tara_browser_session=; Path=/; Max-Age=0"; // the browser closed
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: null });
    const get = vi.spyOn(api, "get");
    const auth = useAuthStore();
    await auth.bootstrap();
    expect(auth.isAuthenticated).toBe(false);
    expect(tokenStore.refresh).toBeNull();
    expect(post).toHaveBeenCalledWith("/auth/logout/", { refresh_token: "refresh-1" });
    expect(get).not.toHaveBeenCalledWith("/me/");
  });
});

describe("rememberMe", () => {
  it("a remembered sign-in survives the browser closing", () => {
    rememberSignIn(true);
    document.cookie = "tara_browser_session=; Path=/; Max-Age=0"; // the browser closed
    expect(browserSessionEnded()).toBe(false);
  });

  it("a session-only sign-in ends when the browser closes", () => {
    rememberSignIn(false);
    expect(browserSessionEnded()).toBe(false); // same browser session
    document.cookie = "tara_browser_session=; Path=/; Max-Age=0"; // the browser closed
    expect(browserSessionEnded()).toBe(true);
  });

  it("signing out forgets the choice", () => {
    rememberSignIn(false);
    forgetSignIn();
    expect(browserSessionEnded()).toBe(false);
  });
});
