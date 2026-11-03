import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { CAPABILITIES, capabilitiesFromClaims, opensConsole } from "@/lib/capabilities";
import { staffAccessAllowed } from "@/router";
import {
  accountLabel,
  adminUsers,
  minUntilDay,
  newIdempotencyKey,
  reasonValid,
  searchParams,
  untilFromDay,
} from "@/services/adminUsers";

afterEach(() => vi.restoreAllMocks());

const USER_CAPS = [
  "admin.users.view",
  "admin.users.reveal",
  "admin.users.suspend",
  "admin.users.sign_out",
  "admin.users.resend_verification",
];

describe("user console capabilities", () => {
  it("mirror the registry: admins hold them all, and each action implies view", () => {
    for (const cap of USER_CAPS) expect(CAPABILITIES).toContain(cap);
    expect([...capabilitiesFromClaims({ roles: ["admin"] })]).toEqual(expect.arrayContaining(USER_CAPS));
    for (const cap of USER_CAPS.slice(1)) expect(capabilitiesFromClaims({ caps: [cap] }).has("admin.users.view")).toBe(true);
    expect([...capabilitiesFromClaims({ roles: ["moderator"] })].filter((c) => c.startsWith("admin.users."))).toEqual([]);
  });

  it("open the console, and the users routes need admin.users.view", () => {
    const auth = (caps: string[]) => ({
      isStaff: opensConsole(caps),
      roles: [],
      canAny: (wanted: readonly string[]) => wanted.some((c) => caps.includes(c)),
    });
    const meta = { staff: true, caps: ["admin.users.view"] };
    expect(staffAccessAllowed(meta, auth(["admin.users.view"]))).toBe(true);
    expect(staffAccessAllowed(meta, auth([...capabilitiesFromClaims({ caps: ["admin.users.suspend"] })]))).toBe(true);
    expect(staffAccessAllowed(meta, auth(["admin.audit.view"]))).toBe(false);
    expect(staffAccessAllowed(meta, auth([]))).toBe(false);
  });
});

describe("user console helpers", () => {
  it("sends only the search params that are set", () => {
    expect(searchParams(" layla@ ")).toEqual({ q: "layla@" });
    expect(searchParams("lay", "email", "c2")).toEqual({ q: "lay", field: "email", cursor: "c2" });
  });

  it("needs a reason of 5 to 500 characters, ignoring surrounding spaces", () => {
    expect(reasonValid("   abc  ")).toBe(false);
    expect(reasonValid("ticket 42")).toBe(true);
    expect(reasonValid("سبب واضح")).toBe(true);
    expect(reasonValid("x".repeat(501))).toBe(false);
  });

  it("turns a chosen day into the start of the next local day, and nothing into no end", () => {
    const iso = untilFromDay("2026-12-01") as string;
    const end = new Date(iso);
    expect(end.getFullYear()).toBe(2026);
    expect(end.getMonth()).toBe(11);
    expect(end.getDate()).toBe(2);
    expect(end.getHours()).toBe(0);
    expect(untilFromDay("")).toBeNull();
    expect(untilFromDay("not-a-date")).toBeNull();
  });

  it("offers tomorrow as the earliest end date", () => {
    expect(minUntilDay(new Date(2026, 11, 31, 15))).toBe("2027-01-01");
  });

  it("names an account by its display name, handle or masked email", () => {
    expect(accountLabel({ display_name: "ليلى", handle: "layla", email_masked: "l***@e***.com" })).toBe("ليلى");
    expect(accountLabel({ display_name: " ", handle: "layla", email_masked: "l***" })).toBe("@layla");
    expect(accountLabel({ display_name: null, handle: null, email_masked: "l***@e***.com" })).toBe("l***@e***.com");
  });

  it("makes a different idempotency key every time", () => {
    const a = newIdempotencyKey();
    expect(a).toMatch(/^ui-/);
    expect(a.length).toBeGreaterThanOrEqual(8);
    expect(newIdempotencyKey()).not.toBe(a);
  });
});

describe("adminUsers service", () => {
  it("passes the cursor and copes with an odd page", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValueOnce({ data: { data: null } });
    const page = await adminUsers.search("lay", "name", "c1");
    expect(get).toHaveBeenCalledWith("/admin/users/", { params: { q: "lay", field: "name", cursor: "c1" } });
    expect(page.data).toEqual([]);
    expect(page.page.has_more).toBe(false);
  });

  it("sends the trimmed reason with a reveal", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValueOnce({ data: { data: { email: "a@b.co", phone: "", sessions: [] } } });
    const data = await adminUsers.reveal("acc-1", "  ticket 42 ");
    expect(post).toHaveBeenCalledWith("/admin/users/acc-1/reveal/", { reason: "ticket 42" });
    expect(data.email).toBe("a@b.co");
  });

  it("sends the dialog's idempotency key with a suspension", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValueOnce({ data: { data: {} } });
    await adminUsers.suspend("acc-1", { reason: " spam ring ", until: null }, "ui-key-123");
    expect(post).toHaveBeenCalledWith(
      "/admin/users/acc-1/suspend/",
      { reason: "spam ring", until: null },
      { headers: { "Idempotency-Key": "ui-key-123" } },
    );
  });

  it("returns how many sessions a sign-out ended", async () => {
    vi.spyOn(api, "post").mockResolvedValueOnce({ data: { data: { sessions_revoked: 3 } } });
    expect(await adminUsers.signOut("acc-1")).toBe(3);
  });
});
