import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  isTokenExpired,
  jwtClaims,
  onTokensChangedElsewhere,
  tokenStore,
  withRefreshLock,
} from "@/lib/tokens";

function jwt(claims: Record<string, unknown>): string {
  return `h.${btoa(JSON.stringify(claims)).replace(/=+$/, "")}.s`;
}

describe("tokenStore", () => {
  beforeEach(() => localStorage.clear());

  it("re-reads storage, so a rotation by another tab is seen immediately", () => {
    tokenStore.set("a1", "r1");
    localStorage.setItem("tara.refresh", "r2-from-other-tab");
    localStorage.setItem("tara.access", "a2-from-other-tab");
    expect(tokenStore.refresh).toBe("r2-from-other-tab");
    expect(tokenStore.access).toBe("a2-from-other-tab");
  });

  it("clear removes both tokens", () => {
    tokenStore.set("a", "r");
    tokenStore.clear();
    expect(tokenStore.access).toBeNull();
    expect(tokenStore.refresh).toBeNull();
  });
});

describe("onTokensChangedElsewhere", () => {
  it("fires for token keys and localStorage.clear(), not unrelated keys", () => {
    const handler = vi.fn();
    const off = onTokensChangedElsewhere(handler);
    window.dispatchEvent(new StorageEvent("storage", { key: "tara.theme" }));
    expect(handler).not.toHaveBeenCalled();
    window.dispatchEvent(new StorageEvent("storage", { key: "tara.refresh" }));
    window.dispatchEvent(new StorageEvent("storage", { key: null }));
    expect(handler).toHaveBeenCalledTimes(2);
    off();
    window.dispatchEvent(new StorageEvent("storage", { key: "tara.access" }));
    expect(handler).toHaveBeenCalledTimes(2);
  });
});

describe("jwt helpers", () => {
  it("reads claims and tolerates garbage", () => {
    expect(jwtClaims(jwt({ sub: "u1" }))?.sub).toBe("u1");
    expect(jwtClaims("garbage")).toBeNull();
    expect(jwtClaims(null)).toBeNull();
  });

  it("treats near-expiry, missing and unreadable tokens as expired", () => {
    const now = Math.floor(Date.now() / 1000);
    expect(isTokenExpired(jwt({ exp: now + 3600 }))).toBe(false);
    expect(isTokenExpired(jwt({ exp: now + 5 }))).toBe(true);
    expect(isTokenExpired(jwt({ exp: now - 10 }))).toBe(true);
    expect(isTokenExpired(jwt({}))).toBe(true);
    expect(isTokenExpired(null)).toBe(true);
  });
});

describe("withRefreshLock", () => {
  it("runs through navigator.locks when available", async () => {
    const request = vi.fn((_name: string, fn: () => Promise<string>) => fn());
    vi.stubGlobal("navigator", { locks: { request } });
    await expect(withRefreshLock(async () => "done")).resolves.toBe("done");
    expect(request).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
  });

  it("still runs without navigator.locks (insecure context)", async () => {
    vi.stubGlobal("navigator", {});
    await expect(withRefreshLock(async () => "done")).resolves.toBe("done");
    vi.unstubAllGlobals();
  });
});
