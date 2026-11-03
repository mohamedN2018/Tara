import axios, { AxiosError, type AxiosAdapter, type InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, apiError, ensureFreshAccess, refreshSession, setUnauthorizedHandler, skipsRefresh } from "@/lib/api";
import { tokenStore } from "@/lib/tokens";

const FRESH = `h.${btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 }))}.s`;
const EXPIRED = `h.${btoa(JSON.stringify({ exp: 1000 }))}.s`;

const tokens = (access: string, refresh: string) => ({
  data: { data: { access_token: access, refresh_token: refresh, token_type: "bearer", expires_in: 900 } },
});
const httpError = (status: number) =>
  new AxiosError("failed", "ERR", undefined, undefined, { status } as never);

function serialLocks() {
  let tail: Promise<unknown> = Promise.resolve();
  vi.stubGlobal("navigator", {
    locks: {
      request: (_name: string, fn: () => Promise<unknown>) => {
        const run = tail.then(fn, fn);
        tail = run.catch(() => {});
        return run;
      },
    },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("refreshSession", () => {
  beforeEach(() => localStorage.clear());

  it("rotates and stores the new pair", async () => {
    tokenStore.set(EXPIRED, "r1");
    const post = vi.spyOn(axios, "post").mockResolvedValue(tokens(FRESH, "r2"));
    await expect(refreshSession(EXPIRED)).resolves.toBe("ok");
    expect(post).toHaveBeenCalledOnce();
    expect(post.mock.calls[0][1]).toEqual({ refresh_token: "r1" });
    expect(tokenStore.refresh).toBe("r2");
  });

  it("does not spend the refresh token when another tab already rotated", async () => {
    tokenStore.set(FRESH, "r2-from-other-tab");
    const post = vi.spyOn(axios, "post");
    await expect(refreshSession(EXPIRED)).resolves.toBe("ok");
    expect(post).not.toHaveBeenCalled();
    expect(tokenStore.refresh).toBe("r2-from-other-tab");
  });

  it("is single-flight within a tab", async () => {
    tokenStore.set(EXPIRED, "r1");
    const post = vi.spyOn(axios, "post").mockResolvedValue(tokens(FRESH, "r2"));
    await Promise.all([refreshSession(EXPIRED), refreshSession(EXPIRED), refreshSession(EXPIRED)]);
    expect(post).toHaveBeenCalledOnce();
  });

  it("two tabs racing spend the refresh token only once", async () => {
    serialLocks();
    tokenStore.set(EXPIRED, "r1");
    const post = vi.spyOn(axios, "post").mockImplementation(async () => tokens(FRESH, "r2"));

    // A second copy of the module is what a second tab runs.
    const first = refreshSession(EXPIRED);
    vi.resetModules();
    const otherTab = await import("@/lib/api");
    const second = otherTab.refreshSession(EXPIRED);

    await expect(Promise.all([first, second])).resolves.toEqual(["ok", "ok"]);
    expect(post).toHaveBeenCalledOnce();
  });

  it("ends the session only when the server rejects the token", async () => {
    tokenStore.set(EXPIRED, "r1");
    vi.spyOn(axios, "post").mockRejectedValue(httpError(401));
    await expect(refreshSession(EXPIRED)).resolves.toBe("invalid");
    expect(tokenStore.refresh).toBeNull();
  });

  it.each([500, 502, 503, 429])("keeps the session on HTTP %i", async (status) => {
    tokenStore.set(EXPIRED, "r1");
    vi.spyOn(axios, "post").mockRejectedValue(httpError(status));
    await expect(refreshSession(EXPIRED)).resolves.toBe("unavailable");
    expect(tokenStore.refresh).toBe("r1");
  });

  it("keeps the session on a network failure or timeout", async () => {
    tokenStore.set(EXPIRED, "r1");
    vi.spyOn(axios, "post").mockRejectedValue(new AxiosError("timeout", "ECONNABORTED"));
    await expect(refreshSession(EXPIRED)).resolves.toBe("unavailable");
    expect(tokenStore.access).toBe(EXPIRED);
  });

  it("reports invalid when there is no refresh token at all", async () => {
    await expect(refreshSession(null)).resolves.toBe("invalid");
  });
});

describe("ensureFreshAccess", () => {
  beforeEach(() => localStorage.clear());

  it("leaves a valid token alone", async () => {
    tokenStore.set(FRESH, "r1");
    const post = vi.spyOn(axios, "post");
    await expect(ensureFreshAccess()).resolves.toBe("ok");
    expect(post).not.toHaveBeenCalled();
  });

  it("refreshes an expired one", async () => {
    tokenStore.set(EXPIRED, "r1");
    vi.spyOn(axios, "post").mockResolvedValue(tokens(FRESH, "r2"));
    await expect(ensureFreshAccess()).resolves.toBe("ok");
    expect(tokenStore.access).toBe(FRESH);
  });
});

describe("response interceptor", () => {
  const unauthorized = vi.fn();
  let seen: InternalAxiosRequestConfig[];

  /** Answer each request in turn with the given HTTP statuses. */
  function respondWith(...statuses: number[]) {
    seen = [];
    api.defaults.adapter = (async (config) => {
      seen.push(config);
      const status = statuses.shift() ?? 200;
      const response = { status, statusText: "", data: {}, headers: {}, config };
      if (status >= 400) throw new AxiosError("failed", "ERR", config, undefined, response as never);
      return response;
    }) as AxiosAdapter;
  }

  beforeEach(() => {
    localStorage.clear();
    unauthorized.mockReset();
    setUnauthorizedHandler(unauthorized);
  });

  it("retries once with the new token after a 401", async () => {
    tokenStore.set(EXPIRED, "r1");
    vi.spyOn(axios, "post").mockResolvedValue(tokens(FRESH, "r2"));
    respondWith(401, 200);
    await api.get("/feed/");
    expect(seen).toHaveLength(2);
    expect(seen[1].headers.get("Authorization")).toBe(`Bearer ${FRESH}`);
    expect(unauthorized).not.toHaveBeenCalled();
  });

  it("just retries when the token changed while the request was in flight", async () => {
    tokenStore.set(EXPIRED, "r1");
    const post = vi.spyOn(axios, "post");
    seen = [];
    api.defaults.adapter = (async (config) => {
      seen.push(config);
      if (seen.length > 1) return { status: 200, statusText: "", data: {}, headers: {}, config };
      tokenStore.set(FRESH, "r2-from-other-tab");
      throw new AxiosError("failed", "ERR", config, undefined, { status: 401 } as never);
    }) as AxiosAdapter;
    await api.get("/feed/");
    expect(post).not.toHaveBeenCalled();
    expect(seen).toHaveLength(2);
  });

  it("logs out only on an invalid refresh", async () => {
    tokenStore.set(EXPIRED, "r1");
    vi.spyOn(axios, "post").mockRejectedValue(httpError(401));
    respondWith(401);
    await expect(api.get("/feed/")).rejects.toBeDefined();
    expect(unauthorized).toHaveBeenCalledOnce();
  });

  it("does not log out when refresh is merely unavailable", async () => {
    tokenStore.set(EXPIRED, "r1");
    vi.spyOn(axios, "post").mockRejectedValue(httpError(503));
    respondWith(401);
    await expect(api.get("/feed/")).rejects.toBeDefined();
    expect(unauthorized).not.toHaveBeenCalled();
    expect(tokenStore.refresh).toBe("r1");
  });

  it("does not touch the session on a 5xx response", async () => {
    tokenStore.set(FRESH, "r1");
    const post = vi.spyOn(axios, "post");
    respondWith(500);
    await expect(api.get("/feed/")).rejects.toBeDefined();
    expect(post).not.toHaveBeenCalled();
    expect(tokenStore.refresh).toBe("r1");
  });

  it("leaves a failed login alone", async () => {
    const post = vi.spyOn(axios, "post");
    respondWith(401);
    await expect(api.post("/auth/login/", {})).rejects.toBeDefined();
    expect(post).not.toHaveBeenCalled();
  });
});

describe("skipsRefresh", () => {
  it.each(["/auth/login/", "/auth/register/", "/auth/refresh/", "/auth/logout/", "/api/v1/auth/login"])(
    "skips %s",
    (url) => expect(skipsRefresh(url)).toBe(true),
  );

  it.each(["/auth/sessions/", "/auth/sessions/abc/", "/auth/verify-email/", "/feed/", undefined])(
    "refreshes %s",
    (url) => expect(skipsRefresh(url)).toBe(false),
  );
});

describe("apiError", () => {
  it("prefers the backend envelope", () => {
    const e = { response: { status: 409, data: { error: { code: "conflict", message: "x" } } } };
    expect(apiError(e).code).toBe("conflict");
  });

  it("derives a code from the status when there is no envelope", () => {
    expect(apiError({ response: { status: 502 } }).code).toBe("server_error");
    expect(apiError({ response: { status: 429 } }).code).toBe("rate_limited");
    expect(apiError({ response: { status: 418 } }).code).toBe("request_failed");
    expect(apiError(new Error("offline")).code).toBe("network_error");
  });
});
