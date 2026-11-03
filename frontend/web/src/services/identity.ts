import { api } from "@/lib/api";
import type { Account, Tokens } from "@/types";

export interface UserSession {
  id: string;
  ip_region: string;
  user_agent: string;
  platform: string;
  created_at: string;
  last_seen_at: string;
  is_current: boolean;
}

/** Sign-in methods the server offers (GET /auth/providers/). Public values only. */
export interface AuthProviders {
  password: boolean;
  google: { enabled: boolean; client_id: string };
  telegram: { enabled: boolean; bot_username: string };
}

/** GET /me/security/: what the Security section of Settings shows. */
export interface SecurityOverview {
  email: string;
  email_verified: boolean;
  has_password: boolean;
  pending_email: string | null;
  google: { linked: boolean; email: string | null; linked_at: string | null };
  phone: string | null;
  phone_verified: boolean;
  phone_verified_at: string | null;
}

export interface TelegramLink {
  deep_link: string;
  bot_username: string;
  expires_in: number;
}

const PROVIDERS_OFF: AuthProviders = {
  password: true,
  google: { enabled: false, client_id: "" },
  telegram: { enabled: false, bot_username: "" },
};

// One request per page load: the answer only changes with a redeploy.
let providersRequest: Promise<AuthProviders> | null = null;

export const identityService = {
  /** Never rejects: when the server can't say, extra providers stay hidden. */
  providers(): Promise<AuthProviders> {
    providersRequest ??= api
      .get<{ data: AuthProviders }>("/auth/providers/")
      .then(({ data }) => data.data)
      .catch(() => {
        providersRequest = null; // try again next time
        return PROVIDERS_OFF;
      });
    return providersRequest;
  },
  async googleSignIn(credential: string, language: string): Promise<Tokens & { created: boolean }> {
    const { data } = await api.post<{ data: Tokens & { created: boolean } }>("/auth/google/", {
      credential,
      language,
    });
    return data.data;
  },
  async security(): Promise<SecurityOverview> {
    const { data } = await api.get<{ data: SecurityOverview }>("/me/security/");
    return data.data;
  },
  async changePassword(currentPassword: string, newPassword: string): Promise<number> {
    const { data } = await api.post<{ data: { revoked_sessions: number } }>("/me/password/", {
      current_password: currentPassword,
      new_password: newPassword,
    });
    return data.data.revoked_sessions;
  },
  async requestEmailChange(newEmail: string, password: string): Promise<string> {
    const { data } = await api.post<{ data: { pending_email: string } }>("/me/email/", {
      new_email: newEmail,
      password,
    });
    return data.data.pending_email;
  },
  async cancelEmailChange(): Promise<void> {
    await api.delete("/me/email/");
  },
  async confirmEmailChange(token: string): Promise<Account> {
    const { data } = await api.post<{ data: Account }>("/auth/email/confirm/", { token });
    return data.data;
  },
  async linkGoogle(credential: string): Promise<SecurityOverview> {
    const { data } = await api.post<{ data: SecurityOverview }>("/me/google/", { credential });
    return data.data;
  },
  async unlinkGoogle(): Promise<SecurityOverview> {
    const { data } = await api.delete<{ data: SecurityOverview }>("/me/google/");
    return data.data;
  },
  async startPhoneVerification(): Promise<TelegramLink> {
    const { data } = await api.post<{ data: TelegramLink }>("/me/phone/telegram/");
    return data.data;
  },
  async removePhone(): Promise<SecurityOverview> {
    const { data } = await api.delete<{ data: SecurityOverview }>("/me/phone/");
    return data.data;
  },
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
