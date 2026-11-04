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

/** PATCH /me/: the fields the owner may change (settings centre, 3C). */
export type AccountChanges = Partial<
  Pick<
    Account,
    | "language"
    | "theme"
    | "gender"
    | "gender_custom"
    | "birthday_visibility"
    | "gender_visibility"
    | "show_presence"
    | "login_alerts"
  >
>;

export interface TwoFactorStatus {
  enabled: boolean;
  method: "totp" | null;
  enabled_at: string | null;
  recovery_codes_remaining: number;
}

export interface TwoFactorSetup {
  secret: string;
  otpauth_uri: string;
  digits: number;
  period: number;
}

export interface SecurityActivity {
  id: string;
  type: string;
  ip_region: string;
  created_at: string;
}

export interface RecognizedDevice {
  id: string;
  platform: string;
  label: string;
  created_at: string;
  last_seen_at: string;
  ip_region: string;
  active_sessions: number;
  is_current: boolean;
}

/** What the viewer may see of someone's birthday and gender (null: hidden or unset). */
export interface PersonalDetails {
  account_id: string;
  birthday: { month: number; day: number } | null;
  gender: { value: string; custom: string | null } | null;
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
  async googleSignIn(credential: string, language: string, otp = ""): Promise<Tokens & { created: boolean }> {
    const { data } = await api.post<{ data: Tokens & { created: boolean } }>("/auth/google/", {
      credential,
      language,
      ...(otp ? { otp } : {}),
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
  /** `password`: required by the server when the account has one (re-authentication). */
  async linkGoogle(credential: string, password?: string): Promise<SecurityOverview> {
    const { data } = await api.post<{ data: SecurityOverview }>("/me/google/", {
      credential,
      ...(password ? { password } : {}),
    });
    return data.data;
  },
  async unlinkGoogle(password?: string): Promise<SecurityOverview> {
    const { data } = await api.delete<{ data: SecurityOverview }>(
      "/me/google/",
      password ? { data: { password } } : undefined,
    );
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
  /** Returns the verified account's id (for the "Complete your profile" step). */
  async verifyEmail(token: string): Promise<string | undefined> {
    const { data } = await api.post<{ data?: { id?: string } }>("/auth/verify-email/", { token });
    return data?.data?.id;
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

  // ---- Settings centre (plan 08 wave 3C) ----------------------------------
  async updateAccount(changes: AccountChanges): Promise<Account> {
    const { data } = await api.patch<{ data: Account }>("/me/", changes);
    return data.data;
  },
  /** Always resolves the same way: the server never says whether the address exists. */
  async resendVerification(email: string): Promise<void> {
    await api.post("/auth/verify-email/resend/", { email });
  },
  async twoFactor(): Promise<TwoFactorStatus> {
    const { data } = await api.get<{ data: TwoFactorStatus }>("/me/2fa/");
    return data.data;
  },
  async startTwoFactor(password: string): Promise<TwoFactorSetup> {
    const { data } = await api.post<{ data: TwoFactorSetup }>("/me/2fa/setup/", { password });
    return data.data;
  },
  async confirmTwoFactor(code: string): Promise<TwoFactorStatus & { recovery_codes: string[] }> {
    const { data } = await api.post<{ data: TwoFactorStatus & { recovery_codes: string[] } }>(
      "/me/2fa/confirm/",
      { code },
    );
    return data.data;
  },
  async disableTwoFactor(password: string, code: string): Promise<TwoFactorStatus> {
    const { data } = await api.post<{ data: TwoFactorStatus }>("/me/2fa/disable/", { password, code });
    return data.data;
  },
  async newRecoveryCodes(password: string): Promise<TwoFactorStatus & { recovery_codes: string[] }> {
    const { data } = await api.post<{ data: TwoFactorStatus & { recovery_codes: string[] } }>(
      "/me/2fa/recovery-codes/",
      { password },
    );
    return data.data;
  },
  async securityActivity(before?: string): Promise<{ results: SecurityActivity[]; next: string | null }> {
    const { data } = await api.get<{ data: { results: SecurityActivity[]; next: string | null } }>(
      "/me/security/activity/",
      { params: { before } },
    );
    return data.data;
  },
  async devices(): Promise<RecognizedDevice[]> {
    const { data } = await api.get<{ data: RecognizedDevice[] }>("/me/devices/");
    return data.data;
  },
  async removeDevice(id: string): Promise<void> {
    await api.delete(`/me/devices/${id}/`);
  },
  async deactivate(password: string, confirm = ""): Promise<void> {
    await api.post("/me/deactivate/", { password, confirm });
  },
  /** Schedule deletion: hidden and signed out now, erased after the grace period. */
  async deleteAccount(password: string, confirm = ""): Promise<{ deletion_scheduled_for: string }> {
    const { data } = await api.post<{ data: { deletion_scheduled_for: string } }>("/me/delete/", { password, confirm });
    return data.data;
  },
  async personalDetails(accountId: string): Promise<PersonalDetails> {
    const { data } = await api.get<{ data: PersonalDetails }>(`/me/people/${accountId}/personal/`);
    return data.data;
  },
};
