import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { api } from "@/lib/api";
import { tokenStore } from "@/lib/tokens";
import { realtime } from "@/lib/ws";
import type { Account, Profile, Tokens } from "@/types";

// register returns the new account in "pending" state (email verification
// required before sign-in); it does NOT return tokens.
interface RegisterResult {
  account_id: string;
  email: string;
  status: string;
}

export const useAuthStore = defineStore("auth", () => {
  const account = ref<Account | null>(null);
  const profile = ref<Profile | null>(null);
  const ready = ref(false);

  const isAuthenticated = computed(() => !!account.value);
  const roles = ref<string[]>([]);
  const isStaff = computed(() => roles.value.some((r) => r === "admin" || r === "moderator"));

  // RBAC roles live in the access-token JWT (not in /me/). Decode them locally.
  function decodeRoles(token: string | null): string[] {
    if (!token) return [];
    try {
      const part = token.split(".")[1];
      const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
      const pad = b64.length % 4 ? "=".repeat(4 - (b64.length % 4)) : "";
      const json = JSON.parse(atob(b64 + pad)) as { roles?: unknown };
      return Array.isArray(json.roles) ? (json.roles as string[]) : [];
    } catch {
      return [];
    }
  }

  function applyTokens(t: Tokens) {
    tokenStore.set(t.access_token, t.refresh_token);
    roles.value = decodeRoles(t.access_token);
  }

  // login returns the tokens directly (flat). The account is fetched from /me/.
  async function login(email: string, password: string) {
    const { data } = await api.post<{ data: Tokens }>("/auth/login/", { email, password });
    applyTokens(data.data);
    await loadAccount();
    await loadProfile();
    realtime.connect();
  }

  async function loadAccount() {
    const { data } = await api.get<{ data: Account }>("/me/");
    account.value = data.data;
  }

  /** Register a new account. Returns it in "pending" state — the caller should
   *  prompt for email verification, then sign in (no auto-login). */
  async function register(payload: {
    email: string;
    password: string;
    handle: string;
    display_name: string;
  }): Promise<RegisterResult> {
    const { data } = await api.post<{ data: RegisterResult }>("/auth/register/", payload);
    return data.data;
  }

  async function loadProfile() {
    try {
      const { data } = await api.get<{ data: Profile }>("/profile/me/");
      profile.value = data.data;
    } catch {
      // Profile service may be degraded; auth still succeeds.
      profile.value = null;
    }
  }

  /** Restore a session on app boot from a persisted refresh token. */
  async function bootstrap() {
    if (tokenStore.access || tokenStore.refresh) {
      try {
        const { data } = await api.get<{ data: Account }>("/me/");
        account.value = data.data;
        roles.value = decodeRoles(tokenStore.access);
        await loadProfile();
        realtime.connect();
      } catch {
        tokenStore.clear();
        account.value = null;
      }
    }
    ready.value = true;
  }

  async function logout() {
    try {
      await api.post("/auth/logout/", { refresh_token: tokenStore.refresh });
    } catch {
      // Best-effort server-side revocation.
    }
    tokenStore.clear();
    account.value = null;
    profile.value = null;
    roles.value = [];
    realtime.close();
  }

  return {
    account,
    profile,
    ready,
    isAuthenticated,
    roles,
    isStaff,
    login,
    register,
    loadProfile,
    bootstrap,
    logout,
  };
});
