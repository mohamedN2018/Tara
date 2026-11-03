import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, skipsRefresh } from "@/lib/api";
import {
  GIS_SRC,
  loadGoogleIdentity,
  renderGoogleButton,
  resetGoogleIdentityForTests,
} from "@/lib/googleIdentity";
import { pollUntil } from "@/lib/pollUntil";
import { detailCode, errorField, securityErrorKey } from "@/lib/securityErrors";
import { tokenStore } from "@/lib/tokens";
import { realtime } from "@/lib/ws";
import { identityService } from "@/services/identity";
import { useAuthStore } from "@/stores/auth";

const envelope = (status: number, code: string, details?: { field: string | null; code: string }[]) => ({
  response: { status, data: { error: { code, message: "x", details: details?.map((d) => ({ ...d, message: "m" })) } } },
});

function gisScripts() {
  return document.querySelectorAll(`script[src="${GIS_SRC}"]`);
}

function fakeGoogle() {
  const id = { initialize: vi.fn(), renderButton: vi.fn(), disableAutoSelect: vi.fn() };
  window.google = { accounts: { id } };
  return id;
}

afterEach(() => {
  delete window.google;
  document.head.querySelectorAll("script").forEach((s) => s.remove());
  resetGoogleIdentityForTests();
});

describe("Google Identity Services loader", () => {
  it("injects the script once and shares the pending load", async () => {
    const first = loadGoogleIdentity();
    const second = loadGoogleIdentity();
    expect(gisScripts()).toHaveLength(1);
    const id = fakeGoogle();
    (gisScripts()[0] as HTMLScriptElement).onload?.(new Event("load"));
    await expect(first).resolves.toBe(id);
    await expect(second).resolves.toBe(id);
  });

  it("does not load anything when GIS is already present", async () => {
    const id = fakeGoogle();
    await expect(loadGoogleIdentity()).resolves.toBe(id);
    expect(gisScripts()).toHaveLength(0);
  });

  it("removes a failed script so a retry can load it again", async () => {
    const failed = loadGoogleIdentity();
    (gisScripts()[0] as HTMLScriptElement).onerror?.(new Event("error"));
    await expect(failed).rejects.toThrow();
    expect(gisScripts()).toHaveLength(0);
    void loadGoogleIdentity();
    expect(gisScripts()).toHaveLength(1);
  });

  it("renders the button and hands back only the credential", async () => {
    const id = fakeGoogle();
    const host = document.createElement("div");
    const onCredential = vi.fn();
    await renderGoogleButton(host, {
      clientId: "client-1",
      locale: "ar",
      text: "signin_with",
      dark: true,
      onCredential,
    });
    const config = id.initialize.mock.calls[0][0];
    expect(config.client_id).toBe("client-1");
    expect(config.auto_select).toBe(false);
    expect(id.renderButton.mock.calls[0][0]).toBe(host);
    expect(id.renderButton.mock.calls[0][1]).toMatchObject({ locale: "ar", text: "signin_with", theme: "filled_black" });
    config.callback({});
    expect(onCredential).not.toHaveBeenCalled();
    config.callback({ credential: "id-token" });
    expect(onCredential).toHaveBeenCalledWith("id-token");
  });
});

describe("auth providers", () => {
  beforeEach(() => vi.resetModules());

  it("is fetched once per page load", async () => {
    const { api: freshApi } = await import("@/lib/api");
    const { identityService: fresh } = await import("@/services/identity");
    const body = { password: true, google: { enabled: true, client_id: "c" }, telegram: { enabled: false, bot_username: "" } };
    const get = vi.spyOn(freshApi, "get").mockResolvedValue({ data: { data: body } });
    await expect(fresh.providers()).resolves.toEqual(body);
    await fresh.providers();
    expect(get).toHaveBeenCalledOnce();
    expect(get.mock.calls[0][0]).toBe("/auth/providers/");
  });

  it("hides every optional provider when the server can't answer, and retries later", async () => {
    const { api: freshApi } = await import("@/lib/api");
    const { identityService: fresh } = await import("@/services/identity");
    const get = vi.spyOn(freshApi, "get").mockRejectedValueOnce(new Error("offline"));
    const result = await fresh.providers();
    expect(result.google.enabled).toBe(false);
    expect(result.telegram.enabled).toBe(false);
    get.mockResolvedValueOnce({ data: { data: { ...result, google: { enabled: true, client_id: "c" } } } });
    expect((await fresh.providers()).google.enabled).toBe(true);
  });
});

describe("identity security calls", () => {
  it("changes the password with the field names the API expects", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: { revoked_sessions: 2 } } });
    await expect(identityService.changePassword("old-pass", "new-pass-123")).resolves.toBe(2);
    expect(post).toHaveBeenCalledWith("/me/password/", { current_password: "old-pass", new_password: "new-pass-123" });
  });

  it("requests an email change and returns the pending address", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: { pending_email: "n@x.co" } } });
    await expect(identityService.requestEmailChange("n@x.co", "pw")).resolves.toBe("n@x.co");
    expect(post).toHaveBeenCalledWith("/me/email/", { new_email: "n@x.co", password: "pw" });
  });

  it("confirms an email change with the token from the link", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: { id: "a", email: "n@x.co" } } });
    await identityService.confirmEmailChange("tok");
    expect(post).toHaveBeenCalledWith("/auth/email/confirm/", { token: "tok" });
  });

  it("links and unlinks Google, and starts phone verification", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: {} } });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: { data: {} } });
    await identityService.linkGoogle("cred");
    await identityService.unlinkGoogle();
    await identityService.startPhoneVerification();
    expect(post).toHaveBeenCalledWith("/me/google/", { credential: "cred" });
    expect(del).toHaveBeenCalledWith("/me/google/", undefined);
    expect(post).toHaveBeenCalledWith("/me/phone/telegram/");
  });

  it("re-authenticates Google changes with the current password", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: {} } });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: { data: {} } });
    await identityService.linkGoogle("cred", "pw");
    await identityService.unlinkGoogle("pw");
    expect(post).toHaveBeenCalledWith("/me/google/", { credential: "cred", password: "pw" });
    expect(del).toHaveBeenCalledWith("/me/google/", { data: { password: "pw" } });
    expect(securityErrorKey(envelope(400, "password_required"))).toBe("accountSecurity.errors.passwordRequired");
    expect(securityErrorKey(envelope(403, "invalid_password"))).toBe("accountSecurity.errors.wrongPassword");
  });

  it("starts phone verification", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: {} } });
    await identityService.startPhoneVerification();
    expect(post).toHaveBeenCalledWith("/me/phone/telegram/");
  });

  it("never spends the refresh token on a rejected Google sign-in", () => {
    expect(skipsRefresh("/auth/google/")).toBe(true);
    // Linking runs on a live session: a 401 there would still mean the session expired.
    expect(skipsRefresh("/me/google/")).toBe(false);
  });
});

describe("Google sign-in in the auth store", () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  it("stores the tokens, loads the account and reports a new account", async () => {
    vi.spyOn(identityService, "googleSignIn").mockResolvedValue({
      access_token: "h.e30.s",
      refresh_token: "r1",
      token_type: "Bearer",
      expires_in: 900,
      created: true,
    });
    vi.spyOn(api, "get").mockImplementation(async (url: string) =>
      url === "/me/"
        ? { data: { data: { id: "a1", email: "g@gmail.com", email_verified: true, status: "active", language: "en", theme: "system" } } }
        : { data: { data: { account_id: "a1" } } },
    );
    const connect = vi.spyOn(realtime, "connect").mockImplementation(() => {});
    const auth = useAuthStore();
    await expect(auth.loginWithGoogle("cred", "ar")).resolves.toBe(true);
    expect(identityService.googleSignIn).toHaveBeenCalledWith("cred", "ar");
    expect(tokenStore.refresh).toBe("r1");
    expect(auth.account?.email).toBe("g@gmail.com");
    expect(connect).toHaveBeenCalled();
  });

  it("a different account signing in does not inherit the last one's local data", async () => {
    localStorage.setItem("tara.dataOwner", "someone-else");
    localStorage.setItem("tara.recentSearches", JSON.stringify(["private term"]));
    localStorage.setItem("tara.market.compare", JSON.stringify(["l1"]));
    vi.spyOn(identityService, "googleSignIn").mockResolvedValue({
      access_token: "h.e30.s",
      refresh_token: "r1",
      token_type: "Bearer",
      expires_in: 900,
      created: false,
    });
    vi.spyOn(api, "get").mockImplementation(async (url: string) =>
      url === "/me/"
        ? { data: { data: { id: "a1", email: "g@gmail.com", email_verified: true, status: "active", language: "en", theme: "system" } } }
        : { data: { data: { account_id: "a1" } } },
    );
    vi.spyOn(realtime, "connect").mockImplementation(() => {});
    await useAuthStore().loginWithGoogle("cred", "ar");
    expect(localStorage.getItem("tara.recentSearches")).toBeNull();
    expect(localStorage.getItem("tara.market.compare")).toBeNull();
    expect(localStorage.getItem("tara.dataOwner")).toBe("a1");

    // The same account again keeps its own conveniences.
    localStorage.setItem("tara.recentSearches", JSON.stringify(["mine"]));
    await useAuthStore().loginWithGoogle("cred", "ar");
    expect(localStorage.getItem("tara.recentSearches")).toBe(JSON.stringify(["mine"]));
  });
});

describe("security error mapping", () => {
  it("maps field details to specific messages", () => {
    const wrong = envelope(400, "validation_error", [{ field: "current_password", code: "invalid_password" }]);
    expect(securityErrorKey(wrong)).toBe("accountSecurity.errors.wrongPassword");
    expect(errorField(wrong)).toBe("current_password");
    expect(detailCode(wrong, "current_password")).toBe("invalid_password");
    expect(detailCode(wrong, "new_password")).toBeUndefined();
    expect(securityErrorKey(envelope(400, "validation_error", [{ field: "new_password", code: "weak_password" }]))).toBe(
      "accountSecurity.errors.weakPassword",
    );
    expect(securityErrorKey(envelope(400, "validation_error", [{ field: "new_email", code: "same_email" }]))).toBe(
      "accountSecurity.errors.sameEmail",
    );
  });

  it("maps account-security codes", () => {
    expect(securityErrorKey(envelope(409, "account_exists"))).toBe("accountSecurity.google.accountExists");
    expect(securityErrorKey(envelope(409, "last_login_method"))).toBe("accountSecurity.google.lastMethod");
    expect(securityErrorKey(envelope(409, "already_linked"))).toBe("accountSecurity.google.alreadyLinked");
  });

  it("falls back to the generic error keys, and honours overrides", () => {
    expect(securityErrorKey(envelope(429, "throttled"))).toBe("errors.throttled");
    expect(securityErrorKey(envelope(418, "teapot"))).toBe("errors.unknown");
    expect(securityErrorKey(envelope(401, "authentication_failed"), { authentication_failed: "custom.key" })).toBe(
      "custom.key",
    );
  });
});

describe("pollUntil", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("resolves true once the check passes, retrying failed checks", async () => {
    const results: (() => Promise<boolean>)[] = [
      () => Promise.reject(new Error("blip")),
      async () => false,
      async () => true,
    ];
    const check = vi.fn(() => (results.shift() ?? (async () => true))());
    const { done } = pollUntil(check, { intervalMs: 1000, timeoutMs: 60_000 });
    await vi.advanceTimersByTimeAsync(3000);
    await expect(done).resolves.toBe(true);
    expect(check).toHaveBeenCalledTimes(3);
  });

  it("gives up at the deadline", async () => {
    const check = vi.fn(async () => false);
    const { done } = pollUntil(check, { intervalMs: 1000, timeoutMs: 3500 });
    await vi.advanceTimersByTimeAsync(10_000);
    await expect(done).resolves.toBe(false);
    expect(check.mock.calls.length).toBeLessThanOrEqual(4);
  });

  it("stops when asked", async () => {
    const check = vi.fn(async () => false);
    const poll = pollUntil(check, { intervalMs: 1000, timeoutMs: 60_000 });
    poll.stop();
    await vi.advanceTimersByTimeAsync(5000);
    await expect(poll.done).resolves.toBe(false);
    expect(check).not.toHaveBeenCalled();
  });
});
