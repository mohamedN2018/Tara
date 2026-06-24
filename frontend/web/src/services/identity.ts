import { api } from "@/lib/api";

export interface UserSession {
  id: string;
  ip_region: string;
  user_agent: string;
  platform: string;
  created_at: string;
  last_seen_at: string;
  is_current: boolean;
}

export const identityService = {
  async verifyEmail(token: string): Promise<void> {
    await api.post("/auth/verify-email/", { token });
  },
  async forgotPassword(email: string): Promise<void> {
    await api.post("/auth/password/forgot/", { email });
  },
  async resetPassword(token: string, password: string): Promise<void> {
    await api.post("/auth/password/reset/", { token, password });
  },
  async sessions(): Promise<UserSession[]> {
    const { data } = await api.get<{ data: UserSession[] | { sessions: UserSession[] } }>(
      "/auth/sessions/",
    );
    return Array.isArray(data.data) ? data.data : (data.data.sessions ?? []);
  },
  async revokeSession(id: string): Promise<void> {
    await api.delete(`/auth/sessions/${id}/`);
  },
};
