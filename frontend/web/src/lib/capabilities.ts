/**
 * Staff capabilities: the namespaced keys that gate admin, moderation and ads
 * review. Mirrors `libs/tara_common/tara_common/capabilities.py`.
 *
 * Identity puts the account's effective keys in the access token (`caps`).
 * Tokens minted before that claim existed carry only `roles`, so the keys are
 * derived from the default role map for them. The server enforces every key;
 * this only decides what the UI shows.
 */

export const CAPABILITIES = [
  "moderation.case.view",
  "moderation.case.act",
  "moderation.appeal.view",
  "moderation.appeal.resolve",
  "ads.review",
  "admin.users.view",
  "admin.users.reveal",
  "admin.users.suspend",
  "admin.users.sign_out",
  "admin.users.resend_verification",
  "admin.roles.manage",
  "admin.capabilities.manage",
  "admin.flags.manage",
  "admin.audit.view",
  "admin.audit.export",
  "admin.monitor.view",
  "admin.notices.send",
] as const;

export type Capability = (typeof CAPABILITIES)[number];

export const ROLES = ["admin", "moderator", "ad_reviewer", "analyst"] as const;

/** Roles that always hold every capability; the matrix shows them read-only. */
export const LOCKED_ROLES: readonly string[] = ["admin"];

/** Holding the key on the left grants the keys on the right too. */
export const IMPLIES: Readonly<Record<string, readonly string[]>> = {
  "moderation.case.act": ["moderation.case.view"],
  "moderation.appeal.resolve": ["moderation.appeal.view"],
  "admin.audit.export": ["admin.audit.view"],
  "admin.users.reveal": ["admin.users.view"],
  "admin.users.suspend": ["admin.users.view"],
  "admin.users.sign_out": ["admin.users.view"],
  "admin.users.resend_verification": ["admin.users.view"],
};

export const DEFAULT_ROLE_CAPABILITIES: Readonly<Record<string, readonly string[]>> = {
  admin: CAPABILITIES,
  moderator: ["moderation.case.view", "moderation.case.act", "moderation.appeal.view", "moderation.appeal.resolve"],
  ad_reviewer: ["ads.review"],
  analyst: [],
};

/** The namespace of a key: its first segment (`moderation`, `ads`, `admin`). */
export function namespaceOf(key: string): string {
  return key.split(".", 1)[0];
}

/** Add every key the given keys imply (transitively). */
export function withImplied(keys: Iterable<string>, implies: Readonly<Record<string, readonly string[]>> = IMPLIES): Set<string> {
  const result = new Set<string>();
  const pending = [...keys];
  while (pending.length) {
    const key = pending.pop() as string;
    if (result.has(key)) continue;
    result.add(key);
    pending.push(...(implies[key] ?? []));
  }
  return result;
}

/** Default capabilities of a set of roles. Unknown roles grant nothing. */
export function capabilitiesForRoles(roles: Iterable<string>): Set<string> {
  const keys: string[] = [];
  for (const role of roles) keys.push(...(DEFAULT_ROLE_CAPABILITIES[role] ?? []));
  return withImplied(keys);
}

const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];

/** The capabilities a decoded access token grants: `caps` if present, else derived from `roles`. */
export function capabilitiesFromClaims(claims: Record<string, unknown> | null | undefined): Set<string> {
  if (!claims) return new Set();
  if (Array.isArray(claims.caps)) return withImplied(strings(claims.caps));
  return capabilitiesForRoles(strings(claims.roles));
}

/** Whether a capability set opens the admin console (any moderation.* or admin.* key). */
export function opensConsole(caps: Iterable<string>): boolean {
  for (const key of caps) {
    const ns = namespaceOf(key);
    if (ns === "moderation" || ns === "admin") return true;
  }
  return false;
}

export type MatrixState = "grant" | "revoke" | "default";

export interface MatrixChange {
  role: string;
  capability: string;
  state: MatrixState;
}

/**
 * The changes that turn `saved` (role -> effective keys, as the server last
 * reported them) into `edited`. A cell that ends up equal to its role's
 * default is sent as "default", so the override is dropped instead of pinning
 * today's default forever. Locked roles are never sent.
 */
export function matrixDiff(
  saved: Readonly<Record<string, Iterable<string>>>,
  edited: Readonly<Record<string, Iterable<string>>>,
  defaults: Readonly<Record<string, Iterable<string>>>,
): MatrixChange[] {
  const changes: MatrixChange[] = [];
  const roles = [...new Set([...Object.keys(saved), ...Object.keys(edited)])].sort();
  for (const role of roles) {
    if (LOCKED_ROLES.includes(role)) continue;
    const before = new Set(saved[role] ?? []);
    const after = new Set(edited[role] ?? []);
    const byDefault = withImplied(defaults[role] ?? []);
    for (const capability of [...new Set([...before, ...after])].sort()) {
      const has = after.has(capability);
      if (before.has(capability) === has) continue;
      const state: MatrixState = has === byDefault.has(capability) ? "default" : has ? "grant" : "revoke";
      changes.push({ role, capability, state });
    }
  }
  return changes;
}

/**
 * Toggle one cell and keep the implies rules: granting a key grants what it
 * implies; removing a key removes every key that implies it.
 */
export function toggleCapability(current: Iterable<string>, key: string, on: boolean): Set<string> {
  const next = new Set(current);
  if (on) {
    for (const k of withImplied([key])) next.add(k);
    return next;
  }
  next.delete(key);
  let changed = true;
  while (changed) {
    changed = false;
    for (const held of [...next]) {
      if ((IMPLIES[held] ?? []).some((k) => !next.has(k))) {
        next.delete(held);
        changed = true;
      }
    }
  }
  return next;
}
