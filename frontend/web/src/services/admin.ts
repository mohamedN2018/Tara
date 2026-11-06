import { api } from "@/lib/api";
import type { MatrixChange } from "@/lib/capabilities";
import type { CursorPage } from "@/types";

export interface ServiceHealth {
  service: string;
  status: string; // ready | not_ready | unreachable | unknown
  latency_ms: number | null;
  /** When the beat task last polled it; null before the first poll. */
  checked_at?: string | null;
}

export interface HealthOverview {
  overall: string; // ok | degraded
  services: ServiceHealth[];
}

export type CaseState = "open" | "in_review" | "resolved";

export interface ModerationCase {
  id: string;
  target_type: string;
  target_id: string;
  severity: string | number;
  state: CaseState | string;
  report_count: number;
  assigned_to: string | null;
  owner_id?: string | null;
  /** Tara Intelligence WP 7.4: the automatic signal behind the case (`spam_hides` …); "" when none. */
  system_signal?: string;
  created_at: string;
  updated_at: string;
}

/** One raw report behind a case (moderation.case.view). */
export interface ModerationReport {
  id: string;
  /** Null for a system-sourced report (WP 7.4): no person filed it. */
  reporter_id: string | null;
  /** `system`: feed's integrity signal, not a user report. Absent from older servers (= user). */
  source?: "user" | "system";
  target_type: string;
  target_id: string;
  reason: string;
  /** What the reporter saw when the target is private (a chat message): text only. */
  evidence?: {
    type?: string;
    body?: string;
    created_at?: string;
    attachment_count?: number;
    /** System reports (WP 7.4): the signal and how many distinct accounts it came from. */
    signal?: string;
    distinct_accounts?: number;
  };
  created_at: string;
}

/** Queue filters: one state, or the caller's own claimed cases. */
export interface CaseQuery {
  state?: CaseState;
  assigned?: "me";
}

/** Counts for the console overview; `open_appeals` only with moderation.appeal.view. */
export interface ModerationSummary {
  open: number;
  in_review: number;
  assigned_to_me: number;
  open_appeals?: number;
}

/** An administrative notice staff sent (admin.notices.send). */
export interface SystemNotice {
  id: string;
  body: string;
  recipient_ids: string[];
  recipient_count: number;
  created_by: string;
  created_at: string;
}

export const NOTICE_MAX_BODY = 300;
export const NOTICE_MAX_RECIPIENTS = 50;

/**
 * What a moderator may do to each kind of target. Mirrors
 * `services/moderation/moderation/services.py` ACTIONS_BY_TARGET; the server
 * refuses any other pair with a 400.
 */
const CONTENT_ACTIONS = ["remove", "approve", "warn", "dismiss"] as const;
export const ACTIONS_BY_TARGET: Readonly<Record<string, readonly string[]>> = {
  post: CONTENT_ACTIONS,
  comment: CONTENT_ACTIONS,
  message: CONTENT_ACTIONS,
  listing: CONTENT_ACTIONS,
  listing_review: CONTENT_ACTIONS,
  gathering: CONTENT_ACTIONS,
  group: CONTENT_ACTIONS,
  story: CONTENT_ACTIONS,
  page: ["remove", "restrict", "warn", "dismiss"],
  user: ["restrict", "shadow", "warn", "dismiss"],
};

export function caseActions(targetType: string): readonly string[] {
  return ACTIONS_BY_TARGET[targetType] ?? ["dismiss"];
}

/** Decisions that do something to the owner (shown as a danger action). */
export const ENFORCING_ACTIONS: readonly string[] = ["remove", "restrict", "shadow", "warn"];

export const ACTION_REASON_MAX = 2000;

/**
 * The in-app link to a case's target, when the target has a page of its own.
 * Comments, messages and listing reviews live inside their owner's context, so
 * they have none (their id is shown instead); a message report carries the
 * text the reporter saw as `evidence`. Pages resolve by id (`/pages/id/:id`).
 * A reported profile opens the public profile, which every moderator may
 * see (the account console needs `admin.users.view`, which moderators lack).
 */
export function targetLink(targetType: string, targetId: string): string | null {
  const id = encodeURIComponent(targetId);
  switch (targetType) {
    case "post":
      return `/posts/${id}`;
    case "listing":
      return `/marketplace/${id}`;
    case "gathering":
      return `/events/${id}`;
    case "group":
      return `/groups/${id}`;
    case "page":
      return `/pages/id/${id}`;
    case "user":
      return `/u/id/${id}`;
    default:
      return null;
  }
}

export type AppealStatus = "open" | "upheld" | "overturned";

/** A member's appeal against a moderation decision (moderators only). */
export interface Appeal {
  id: string;
  case_id: string;
  target_type: string;
  target_id: string;
  account_id: string;
  text: string;
  status: AppealStatus;
  created_at: string;
}

export interface FeatureFlag {
  key: string;
  enabled: boolean;
  rollout_pct: number;
  description: string;
}

export interface RoleHolder {
  account_id: string;
  email: string;
  roles: string[];
  bridged_roles: string[];
}

export interface CapabilityOverride {
  role: string;
  capability: string;
  granted: boolean;
  updated_by: string | null;
  updated_at: string;
}

/** The role x capability matrix as identity stores it. */
export interface CapabilityMatrix {
  capabilities: { key: string; namespace: string }[];
  roles: string[];
  locked_roles: string[];
  defaults: Record<string, string[]>;
  overrides: CapabilityOverride[];
  effective: Record<string, string[]>;
  implies: Record<string, string[]>;
}

export interface AuditEntry {
  id: string;
  occurred_at: string;
  actor_kind: "account" | "system";
  actor_id: string | null;
  actor_name: string;
  action: string;
  target_type: string;
  target_id: string;
  request_id: string;
  detail: Record<string, unknown>;
  /** A staff member's own justification (a personal-data reveal); empty otherwise. */
  reason?: string;
}

export interface AuditFilters {
  actor?: string;
  action?: string;
  target_type?: string;
  target_id?: string;
  /** ISO datetimes. */
  since?: string;
  until?: string;
}

export const AUDIT_ACTIONS = [
  "role.granted",
  "role.revoked",
  "capability.changed",
  "moderation.actioned",
  "appeal.resolved",
  "ad.review.decided",
  "feature_flag.changed",
  "audit.exported",
  "user.viewed",
  "user.personal_data.revealed",
  "account.suspended",
  "account.unsuspended",
  "account.signed_out",
  "account.verification_resent",
  "system_notice.sent",
] as const;

export const PLATFORM_METRICS = ["accounts", "posts", "active_conversations", "listings", "open_cases"] as const;

export interface PlatformStat {
  metric: string;
  value: number | null;
  updated_at: string | null;
}

export interface MonitorOverview {
  overall: string; // ok | degraded | unknown
  services: ServiceHealth[];
  stats: PlatformStat[];
  intervals: { health_seconds: number; stats_seconds: number };
}

/** Only the filters that are set: an empty `actor=` would filter on "". */
export function auditParams(filters: AuditFilters, cursor?: string | null): Record<string, string> {
  const params: Record<string, string> = {};
  for (const [key, value] of Object.entries(filters)) {
    const v = typeof value === "string" ? value.trim() : "";
    if (v) params[key] = v;
  }
  if (cursor) params.cursor = cursor;
  return params;
}

/** Hand a downloaded file to the browser under `filename`. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

const emptyPage = { next_cursor: null, prev_cursor: null, has_more: false };

export const adminService = {
  async flags(): Promise<FeatureFlag[]> {
    const { data } = await api.get<{ data: FeatureFlag[] }>("/admin/feature-flags/");
    return data.data;
  },
  async setFlag(flag: FeatureFlag): Promise<void> {
    const { key, enabled, rollout_pct, description } = flag;
    await api.patch(`/admin/feature-flags/${encodeURIComponent(key)}/`, {
      enabled,
      rollout_pct,
      description,
    });
  },

  async roleHolders(): Promise<RoleHolder[]> {
    const { data } = await api.get<{ data: RoleHolder[] }>("/admin/roles/");
    return data.data;
  },
  async findAccount(email: string): Promise<RoleHolder> {
    const { data } = await api.get<{ data: RoleHolder }>("/admin/roles/lookup/", { params: { email } });
    return data.data;
  },
  async grantRole(accountId: string, role: string): Promise<void> {
    await api.post("/admin/roles/", { account_id: accountId, role });
  },
  async revokeRole(accountId: string, role: string): Promise<void> {
    await api.delete("/admin/roles/", { data: { account_id: accountId, role } });
  },

  /** Roles x capabilities: defaults, overrides and the effective result. */
  async capabilityMatrix(): Promise<CapabilityMatrix> {
    const { data } = await api.get<{ data: CapabilityMatrix }>("/admin/capabilities/");
    return data.data;
  },
  async saveCapabilities(changes: MatrixChange[]): Promise<CapabilityMatrix> {
    const { data } = await api.put<{ data: CapabilityMatrix }>("/admin/capabilities/", { changes });
    return data.data;
  },

  /** The unified audit trail, newest first (cursor-paginated). */
  async audit(filters: AuditFilters = {}, cursor?: string | null): Promise<CursorPage<AuditEntry>> {
    const { data } = await api.get<CursorPage<AuditEntry>>("/admin/audit/", { params: auditParams(filters, cursor) });
    return { data: Array.isArray(data?.data) ? data.data : [], page: data?.page ?? emptyPage };
  },

  /** Download the filtered audit trail as CSV (through the API client, which adds the token). */
  async exportAudit(filters: AuditFilters = {}, now: Date = new Date()): Promise<void> {
    const { data } = await api.get<Blob>("/admin/audit/export.csv", {
      params: auditParams(filters),
      responseType: "blob",
    });
    saveBlob(data, `tara-audit-${now.toISOString().slice(0, 10)}.csv`);
  },

  /** Service health and platform statistics, as the beat task last recorded them. */
  async monitor(): Promise<MonitorOverview> {
    const { data } = await api.get<{ data: MonitorOverview }>("/admin/monitor/");
    return data.data;
  },

  /** Aggregated per-service readiness (admin RBAC). */
  async health(): Promise<HealthOverview> {
    const { data } = await api.get<{ data: HealthOverview }>("/admin/service-health/");
    return data.data;
  },

  /** Moderation queue: cases (reports are aggregated into cases server-side), cursor-paginated. */
  async cases(query: CaseQuery = {}, cursor?: string | null): Promise<CursorPage<ModerationCase>> {
    const params: Record<string, string> = {};
    if (query.state) params.state = query.state;
    if (query.assigned) params.assigned = query.assigned;
    if (cursor) params.cursor = cursor;
    const { data } = await api.get<CursorPage<ModerationCase>>("/moderation/cases/", { params });
    return { data: Array.isArray(data?.data) ? data.data : [], page: data?.page ?? emptyPage };
  },

  /** Claim a case: it moves to in_review, assigned to the caller. */
  async assignCase(caseId: string): Promise<ModerationCase> {
    const { data } = await api.post<{ data: ModerationCase }>(`/moderation/cases/${caseId}/assign/`);
    return data.data;
  },

  /** Raw reports, newest first: all of them, or one case's. */
  async reports(caseId?: string | null, cursor?: string | null): Promise<CursorPage<ModerationReport>> {
    const params: Record<string, string> = {};
    if (caseId) params.case = caseId;
    if (cursor) params.cursor = cursor;
    const { data } = await api.get<CursorPage<ModerationReport>>("/moderation/reports/", { params });
    return { data: Array.isArray(data?.data) ? data.data : [], page: data?.page ?? emptyPage };
  },

  /** Queue counts for the overview. */
  async moderationSummary(): Promise<ModerationSummary> {
    const { data } = await api.get<{ data: ModerationSummary }>("/moderation/summary/");
    return data.data;
  },

  /** Resolve a case. action ∈ {dismiss, warn, remove, ...} (ModerationAction). */
  async actionCase(caseId: string, action: string, reason = ""): Promise<void> {
    await api.post(`/moderation/cases/${caseId}/action/`, { action, reason });
  },

  /** Administrative notices sent so far, newest first. */
  async notices(cursor?: string | null): Promise<CursorPage<SystemNotice>> {
    const { data } = await api.get<CursorPage<SystemNotice>>("/admin/notices/", {
      params: cursor ? { cursor } : {},
    });
    return { data: Array.isArray(data?.data) ? data.data : [], page: data?.page ?? emptyPage };
  },

  /** Send a notice to 1-50 accounts; it reaches them as a notification. */
  async sendNotice(recipientIds: string[], body: string): Promise<SystemNotice> {
    const { data } = await api.post<{ data: SystemNotice }>("/admin/notices/", { recipient_ids: recipientIds, body });
    return data.data;
  },

  /** Appeals, oldest first (cursor-paginated). */
  async appeals(status: AppealStatus = "open", cursor?: string | null): Promise<CursorPage<Appeal>> {
    const { data } = await api.get<CursorPage<Appeal>>("/moderation/appeals/", {
      params: cursor ? { status, cursor } : { status },
    });
    return {
      data: Array.isArray(data?.data) ? data.data : [],
      page: data?.page ?? { next_cursor: null, prev_cursor: null, has_more: false },
    };
  },

  /** Uphold the decision, or overturn it. */
  async resolveAppeal(appealId: string, status: Exclude<AppealStatus, "open">): Promise<void> {
    await api.post(`/moderation/appeals/${appealId}/resolve/`, { status });
  },

  /** File a report from anywhere in the app (any authenticated user). Prefer `moderationService.report`. */
  async report(payload: { target_type: string; target_id: string; reason: string }): Promise<void> {
    await api.post("/moderation/reports/file/", payload);
  },
};
