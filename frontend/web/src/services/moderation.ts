// The member's side of moderation: reporting a person or a Page, the Support
// inbox (decisions about my content and account, the reports I filed) and
// appeals. The staff queue lives in services/admin.ts.
import { api, apiError } from "@/lib/api";
import type { CursorPage } from "@/types";

/** Targets reported straight to moderation; posts, comments, listings... go through their own service. */
export type ManualReportTarget = "user" | "page";

/** A fixed list, so the report carries no free text unless the member adds some. */
export const PROFILE_REPORT_REASONS = [
  "fake_account",
  "impersonation",
  "harassment",
  "hate",
  "violence",
  "nudity",
  "scam",
  "spam",
  "underage",
  "other",
] as const;

export type ProfileReportReason = (typeof PROFILE_REPORT_REASONS)[number];

/** The server keeps 200 characters of a report's reason. */
export const REPORT_DETAIL_MAX = 200;
export const APPEAL_TEXT_MAX = 4000;

/** Error codes worth their own wording when filing a report. */
export const MANUAL_REPORT_ERRORS: Record<string, string> = {
  throttled: "safety.report.throttled",
  rate_limited: "safety.report.throttled",
  validation_error: "safety.report.invalid",
};

export const APPEAL_ERRORS: Record<string, string> = {
  conflict: "safety.status.appealConflict",
  not_found: "safety.status.appealGone",
};

export type Decision = "remove" | "restrict" | "warn";
export type AppealStatus = "open" | "upheld" | "overturned";

/** A decision about my own content or account. */
export interface MyCase {
  id: string;
  target_type: string;
  target_id: string;
  decision: Decision | string;
  /** What the moderator chose to share with me; often empty. */
  reason: string;
  decided_at: string | null;
  appeal_status: AppealStatus | null;
  appealed_at: string | null;
  can_appeal: boolean;
}

/** A report I filed and where it stands. */
export interface MyReport {
  id: string;
  target_type: string;
  target_id: string;
  reason: string;
  created_at: string;
  state: "open" | "in_review" | "resolved";
  outcome: "actioned" | "no_action" | null;
}

/** The report's stored reason: the chosen code, plus the member's words when given. */
export function reportReason(code: string, detail = ""): string {
  const extra = detail.trim();
  return (extra ? `${code}: ${extra}` : code).slice(0, REPORT_DETAIL_MAX);
}

/** The reason code of a stored reason ("spam: …" -> "spam"). */
export function reasonCode(reason: string): string {
  return (reason || "").split(":", 1)[0].trim();
}

const emptyPage = { next_cursor: null, prev_cursor: null, has_more: false };

function page<T>(data: CursorPage<T> | undefined): CursorPage<T> {
  return { data: Array.isArray(data?.data) ? data.data : [], page: data?.page ?? emptyPage };
}

/** The in-app place a member can open for their own target, when it has one. */
export function ownTargetLink(targetType: string, targetId: string): string | null {
  const id = encodeURIComponent(targetId);
  if (targetType === "post") return `/posts/${id}`;
  if (targetType === "listing") return `/marketplace/${id}`;
  if (targetType === "gathering") return `/events/${id}`;
  if (targetType === "group") return `/groups/${id}`;
  if (targetType === "page") return `/pages/id/${id}`;
  return null;
}

/** A blocked sign-in that names a suspension: until when (null: open-ended) and who decided. */
export interface Suspension {
  until: string | null;
  source: string;
}

/** The suspension a failed sign-in reports (code `account_suspended`), or null. */
export function suspensionFrom(error: unknown): Suspension | null {
  const { code, details = [] } = apiError(error);
  if (code !== "account_suspended") return null;
  const until = details.find((d) => d.field === "until")?.message || "";
  const source = details.find((d) => d.field === "source")?.code || "";
  return { until: until && !Number.isNaN(Date.parse(until)) ? until : null, source };
}

export const moderationService = {
  /** Report a person or a Page (202; at most 20 an hour per account). */
  async report(target_type: ManualReportTarget, target_id: string, reason: string): Promise<void> {
    await api.post("/moderation/reports/file/", { target_type, target_id, reason });
  },

  /** Decisions about my content or account, newest first. */
  async myCases(cursor?: string | null): Promise<CursorPage<MyCase>> {
    const { data } = await api.get<CursorPage<MyCase>>("/moderation/me/cases/", {
      params: cursor ? { cursor } : {},
    });
    return page(data);
  },

  /** The reports I filed, newest first. */
  async myReports(cursor?: string | null): Promise<CursorPage<MyReport>> {
    const { data } = await api.get<CursorPage<MyReport>>("/moderation/me/reports/", {
      params: cursor ? { cursor } : {},
    });
    return page(data);
  },

  /** Ask for a decision to be reviewed again (once per case). */
  async appeal(caseId: string, text: string): Promise<void> {
    await api.post(`/moderation/cases/${caseId}/appeals/`, { text });
  },
};
