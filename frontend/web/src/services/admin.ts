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
