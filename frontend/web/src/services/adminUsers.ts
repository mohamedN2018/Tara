import { api } from "@/lib/api";
import type { CursorPage } from "@/types";

/** User management console (roadmap 8.6). The server enforces every capability. */

export const SEARCH_FIELDS = ["auto", "email", "handle", "name", "id"] as const;
export type SearchField = (typeof SEARCH_FIELDS)[number];

export const ACCOUNT_STATUSES = ["active", "pending", "suspended", "deactivated", "deleted"] as const;

/** One search result: masked contact details only. */
export interface UserRow {
  account_id: string;
  email_masked: string;
  status: string;
  email_verified: boolean;
  created_at: string | null;
  handle: string | null;
  display_name: string | null;
}

export interface UserSuspension {
  id: string;
  reason: string;
  /** ISO datetime, or null: until staff lift it. */
  until: string | null;
  source: string;
  created_at: string | null;
  created_by: string | null;
}

/** An account's page. Every fetch of it is written to the audit log. */
export interface UserDetail {
  account_id: string;
  email_masked: string;
  status: string;
  email_verified: boolean;
  created_at: string | null;
  phone_verified: boolean;
  phone_masked: string;
  last_login_at: string | null;
  language: string;
  roles: string[];
  bridged_roles: string[];
  active_sessions: number;
  google_linked: boolean;
  suspension: UserSuspension | null;
  profile: { handle: string | null; display_name: string | null; avatar_media_id: string | null } | null;
  /** null: the owning service did not answer. */
  counts: { posts: number | null; listings: number | null; open_cases: number | null };
}

export interface UserSession {
  id: string;
  platform: string;
  user_agent: string;
  ip_region: string;
  created_at: string | null;
  last_seen_at: string | null;
}

/** Shown only after a reveal, which records the typed reason in the audit log. */
export interface PersonalData {
  account_id: string;
  email: string;
  phone: string;
  sessions: UserSession[];
}

export interface UserSearchPage extends CursorPage<UserRow> {
  field?: string;
}

/** The server's minimum for a reason; the dialog checks it first. */
export const REASON_MIN = 5;
export const REASON_MAX = 500;

export function reasonValid(reason: string): boolean {
  const trimmed = reason.trim();
  return trimmed.length >= REASON_MIN && trimmed.length <= REASON_MAX;
}

/** Query params for a search: only what is set. */
export function searchParams(q: string, field: SearchField = "auto", cursor?: string | null): Record<string, string> {
  const params: Record<string, string> = { q: q.trim() };
  if (field !== "auto") params.field = field;
  if (cursor) params.cursor = cursor;
  return params;
}

/**
 * A date input's local day as the end of the suspension: the start of the next
 * local day, as an ISO datetime. Empty or invalid input means "no end date".
 */
export function untilFromDay(day: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
  const d = new Date(`${day}T00:00:00`);
  if (Number.isNaN(d.getTime())) return null;
  d.setDate(d.getDate() + 1);
  return d.toISOString();
}

/** Tomorrow as a date input's `min` (a suspension must end in the future). */
export function minUntilDay(now: Date = new Date()): string {
  const d = new Date(now);
  d.setDate(d.getDate() + 1);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** What to call an account in the console: its name, its handle, or its masked email. */
export function accountLabel(row: { display_name?: string | null; handle?: string | null; email_masked?: string }): string {
  return row.display_name?.trim() || (row.handle ? `@${row.handle}` : "") || row.email_masked || "";
}

/** A fresh key per dialog: a retried submit of the same dialog applies once. */
export function newIdempotencyKey(): string {
  const random = globalThis.crypto?.randomUUID?.();
  return random ? `ui-${random}` : `ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

const emptyPage = { next_cursor: null, prev_cursor: null, has_more: false };

export const adminUsers = {
  async search(q: string, field: SearchField = "auto", cursor?: string | null): Promise<UserSearchPage> {
    const { data } = await api.get<UserSearchPage>("/admin/users/", { params: searchParams(q, field, cursor) });
    return { data: Array.isArray(data?.data) ? data.data : [], page: data?.page ?? emptyPage, field: data?.field };
  },
  async detail(accountId: string): Promise<UserDetail> {
    const { data } = await api.get<{ data: UserDetail }>(`/admin/users/${encodeURIComponent(accountId)}/`);
    return data.data;
  },
  async reveal(accountId: string, reason: string): Promise<PersonalData> {
    const { data } = await api.post<{ data: PersonalData }>(`/admin/users/${encodeURIComponent(accountId)}/reveal/`, {
      reason: reason.trim(),
    });
    return data.data;
  },
  async suspend(accountId: string, body: { reason: string; until: string | null }, idempotencyKey: string): Promise<void> {
    await api.post(
      `/admin/users/${encodeURIComponent(accountId)}/suspend/`,
      { reason: body.reason.trim(), until: body.until },
      { headers: { "Idempotency-Key": idempotencyKey } },
    );
  },
  async unsuspend(accountId: string, reason: string): Promise<void> {
    await api.post(`/admin/users/${encodeURIComponent(accountId)}/unsuspend/`, { reason: reason.trim() });
  },
  async signOut(accountId: string): Promise<number> {
    const { data } = await api.post<{ data: { sessions_revoked: number } }>(`/admin/users/${encodeURIComponent(accountId)}/sign-out/`);
    return data.data.sessions_revoked;
  },
  async resendVerification(accountId: string): Promise<void> {
    await api.post(`/admin/users/${encodeURIComponent(accountId)}/resend-verification/`);
  },
};
