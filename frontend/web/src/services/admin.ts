import { api } from "@/lib/api";
import type { CursorPage } from "@/types";

export interface ServiceHealth {
  service: string;
  status: string; // ready | not_ready | ...
  latency_ms: number | null;
}

export interface HealthOverview {
  overall: string; // ok | degraded
  services: ServiceHealth[];
}

export interface ModerationCase {
  id: string;
  target_type: string;
  target_id: string;
  severity: string | number;
  state: string;
  report_count: number;
  assigned_to: string | null;
  created_at: string;
  updated_at: string;
}

export const adminService = {
  /** Aggregated per-service readiness (admin RBAC). */
  async health(): Promise<HealthOverview> {
    const { data } = await api.get<{ data: HealthOverview }>("/admin/service-health/");
    return data.data;
  },

  /** Moderation queue: cases (reports are aggregated into cases server-side). */
  async cases(state?: string): Promise<ModerationCase[]> {
    const { data } = await api.get<CursorPage<ModerationCase>>("/moderation/cases/", {
      params: state ? { state } : {},
    });
    return data.data;
  },

  /** Resolve a case. action ∈ {dismiss, warn, remove, ...} (ModerationAction). */
  async actionCase(caseId: string, action: string, reason = ""): Promise<void> {
    await api.post(`/moderation/cases/${caseId}/action/`, { action, reason });
  },

  /** File a report from anywhere in the app (any authenticated user). */
  async report(payload: { target_type: string; target_id: string; reason: string }): Promise<void> {
    await api.post("/moderation/reports/file/", payload);
  },
};
