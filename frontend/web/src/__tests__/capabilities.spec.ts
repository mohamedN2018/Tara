import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import {
  CAPABILITIES,
  capabilitiesFromClaims,
  matrixDiff,
  opensConsole,
  toggleCapability,
  withImplied,
} from "@/lib/capabilities";
import { startVisiblePolling } from "@/lib/visiblePolling";
import { realtime } from "@/lib/ws";
import { staffAccessAllowed } from "@/router";
import { adminService, auditParams } from "@/services/admin";
import { identityService } from "@/services/identity";
import { useAuthStore } from "@/stores/auth";

const sorted = (s: Set<string>) => [...s].sort();

describe("capabilities from the token", () => {
  it("uses the caps claim when the token has one", () => {
    expect(sorted(capabilitiesFromClaims({ roles: ["admin"], caps: ["ads.review"] }))).toEqual(["ads.review"]);
    // An empty claim is an answer, not a missing one.
    expect(sorted(capabilitiesFromClaims({ roles: ["admin"], caps: [] }))).toEqual([]);
  });

  it("derives them from roles for tokens minted before the claim existed", () => {
    expect(sorted(capabilitiesFromClaims({ roles: ["admin"] }))).toEqual([...CAPABILITIES].sort());
    expect(sorted(capabilitiesFromClaims({ roles: ["moderator"] }))).toEqual([
      "moderation.appeal.resolve",
      "moderation.appeal.view",
      "moderation.case.act",
      "moderation.case.view",
    ]);
    expect(sorted(capabilitiesFromClaims({ roles: ["ad_reviewer"] }))).toEqual(["ads.review"]);
    expect(sorted(capabilitiesFromClaims({ roles: ["analyst", "nonsense", 7] }))).toEqual([]);
    expect(sorted(capabilitiesFromClaims(null))).toEqual([]);
  });

  it("applies the implies closure", () => {
    expect(sorted(capabilitiesFromClaims({ caps: ["admin.audit.export"] }))).toEqual(["admin.audit.export", "admin.audit.view"]);
    expect(sorted(withImplied(["moderation.case.act"]))).toEqual(["moderation.case.act", "moderation.case.view"]);
  });

  it("opens the console for moderation or admin keys only", () => {
    expect(opensConsole(capabilitiesFromClaims({ roles: ["ad_reviewer"] }))).toBe(false);
    expect(opensConsole(capabilitiesFromClaims({ roles: ["moderator"] }))).toBe(true);
    expect(opensConsole(new Set(["admin.monitor.view"]))).toBe(true);
  });
});

describe("matrix editing", () => {
  const defaults = { admin: [...CAPABILITIES], moderator: ["moderation.case.act"], analyst: [] };

  it("lists grants, revocations and returns to the default", () => {
    const saved = {
      admin: [...CAPABILITIES],
      moderator: ["moderation.case.act", "moderation.case.view", "admin.audit.view"],
      analyst: [],
    };
    const edited = {
      admin: [],
      moderator: ["admin.monitor.view"],
      analyst: ["admin.monitor.view"],
    };
    expect(matrixDiff(saved, edited, defaults)).toEqual([
      // The admin role is locked: never sent.
      { role: "analyst", capability: "admin.monitor.view", state: "grant" },
      { role: "moderator", capability: "admin.audit.view", state: "default" },
      { role: "moderator", capability: "admin.monitor.view", state: "grant" },
      { role: "moderator", capability: "moderation.case.act", state: "revoke" },
      { role: "moderator", capability: "moderation.case.view", state: "revoke" },
    ]);
  });

  it("finds nothing to save when nothing changed", () => {
    expect(matrixDiff({ analyst: ["ads.review"] }, { analyst: new Set(["ads.review"]) }, defaults)).toEqual([]);
  });

  it("keeps the implies rules when a cell is toggled", () => {
    expect(sorted(toggleCapability([], "admin.audit.export", true))).toEqual(["admin.audit.export", "admin.audit.view"]);
    expect(sorted(toggleCapability(["admin.audit.export", "admin.audit.view", "ads.review"], "admin.audit.view", false))).toEqual([
      "ads.review",
    ]);
  });
});

describe("route gates", () => {
  const auth = (caps: string[], roles: string[] = []) => {
    const set = capabilitiesFromClaims({ caps });
    return { isStaff: opensConsole(set), roles, canAny: (keys: readonly string[]) => keys.some((k) => set.has(k)) };
  };

  it("lets a route through only with one of its capabilities", () => {
    expect(staffAccessAllowed({ caps: ["admin.audit.view"] }, auth(["admin.audit.export"]))).toBe(true);
    expect(staffAccessAllowed({ staff: true, caps: ["admin.audit.view"] }, auth(["moderation.case.view"]))).toBe(false);
    expect(staffAccessAllowed({ caps: ["ads.review"] }, auth(["ads.review"]))).toBe(true);
    expect(staffAccessAllowed({ staff: true }, auth(["ads.review"]))).toBe(false);
    expect(staffAccessAllowed({}, auth([]))).toBe(true);
  });
});

describe("audit export", () => {
  afterEach(() => vi.restoreAllMocks());

  it("sends only the filters that are set", () => {
    expect(auditParams({ actor: " ", action: "role.granted", since: "" }, "c1")).toEqual({ action: "role.granted", cursor: "c1" });
  });

  it("downloads the CSV through the API client and saves it under a dated name", async () => {
    const blob = new Blob(["﻿occurred_at\n"], { type: "text/csv" });
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: blob });
    const createUrl = vi.fn(() => "blob:audit");
    const revokeUrl = vi.fn();
    Object.assign(URL, { createObjectURL: createUrl, revokeObjectURL: revokeUrl });
    const clicked: HTMLAnchorElement[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this);
    });

    await adminService.exportAudit({ action: "audit.exported", actor: "" }, new Date("2026-11-03T10:00:00Z"));

    expect(get).toHaveBeenCalledWith("/admin/audit/export.csv", { params: { action: "audit.exported" }, responseType: "blob" });
    expect(createUrl).toHaveBeenCalledWith(blob);
    expect(clicked).toHaveLength(1);
    expect(clicked[0].download).toBe("tara-audit-2026-11-03.csv");
    expect(clicked[0].href).toBe("blob:audit");
    expect(document.body.contains(clicked[0])).toBe(false);
  });
});

describe("monitor polling", () => {
  afterEach(() => vi.useRealTimers());

  function fakeDocument(hidden: boolean) {
    const target = new EventTarget();
    return Object.assign(target, { hidden }) as unknown as Document & { hidden: boolean };
  }

  it("polls while visible and pauses while the tab is hidden", async () => {
    vi.useFakeTimers();
    const doc = fakeDocument(false);
    const tick = vi.fn();
    const stop = startVisiblePolling(tick, 15_000, doc);
    await vi.advanceTimersByTimeAsync(0);
    expect(tick).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(15_000);
    expect(tick).toHaveBeenCalledTimes(2);

    (doc as { hidden: boolean }).hidden = true;
    doc.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(tick).toHaveBeenCalledTimes(2);

    (doc as { hidden: boolean }).hidden = false;
    doc.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(0);
    expect(tick).toHaveBeenCalledTimes(3); // at once on return

    stop();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(tick).toHaveBeenCalledTimes(3);
  });

  it("does not poll a tab that opens hidden", async () => {
    vi.useFakeTimers();
    const tick = vi.fn();
    const stop = startVisiblePolling(tick, 1000, fakeDocument(true));
    await vi.advanceTimersByTimeAsync(5000);
    expect(tick).not.toHaveBeenCalled();
    stop();
  });
});

describe("the auth store", () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });
  afterEach(() => vi.restoreAllMocks());

  async function signInWith(claims: Record<string, unknown>) {
    const payload = btoa(JSON.stringify(claims)).replace(/=+$/, "");
    vi.spyOn(identityService, "googleSignIn").mockResolvedValue({
      access_token: `h.${payload}.s`,
      refresh_token: "r1",
      token_type: "Bearer",
      expires_in: 900,
      created: false,
    });
    vi.spyOn(api, "get").mockImplementation(async (url: string) =>
      url === "/me/"
        ? { data: { data: { id: "a1", email: "x@y.z", email_verified: true, status: "active", language: "ar", theme: "system" } } }
        : { data: { data: { account_id: "a1" } } },
    );
    vi.spyOn(realtime, "connect").mockImplementation(() => {});
    const auth = useAuthStore();
    await auth.loginWithGoogle("cred", "ar");
    return auth;
  }

  it("reads capabilities from the caps claim", async () => {
    const auth = await signInWith({ sub: "a1", roles: ["analyst"], caps: ["admin.monitor.view"] });
    expect(auth.can("admin.monitor.view")).toBe(true);
    expect(auth.canAny(["admin.audit.view", "admin.monitor.view"])).toBe(true);
    expect(auth.can("admin.audit.view")).toBe(false);
    expect(auth.isStaff).toBe(true);
  });

  it("keeps an ad reviewer out of the console, as before", async () => {
    const auth = await signInWith({ sub: "a1", roles: ["ad_reviewer"] });
    expect(auth.can("ads.review")).toBe(true);
    expect(auth.isStaff).toBe(false);
  });
});
