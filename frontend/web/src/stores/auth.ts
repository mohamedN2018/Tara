import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { api, apiError, isAuthFailure } from "@/lib/api";
import { jwtClaims, tokenStore } from "@/lib/tokens";
import { realtime } from "@/lib/ws";
import { useDirectoryStore } from "@/stores/directory";
import type { Account, Profile, Tokens } from "@/types";

// register returns the new account in "pending" state (email verification
// required before sign-in); it does NOT return tokens.
interface RegisterResult {
  account_id: string;
  email: string;
  status: string;
}

const MAX_PROFILE_RETRIES = 5;

export const useAuthStore = defineStore("auth", () => {
  const account = ref<Account | null>(null);
  const profile = ref<Profile | null>(null);
  const ready = ref(false);
  // A stored session exists but the server couldn't be reached to restore it.
  const sessionUnavailable = ref(false);
  let profileRetries = 0;

  const isAuthenticated = computed(() => !!account.value);
  const roles = ref<string[]>([]);
  const isStaff = computed(() => roles.value.some((r) => r === "admin" || r === "moderator"));

  // RBAC roles live in the access-token JWT (not in /me/). Decode them locally.
  function decodeRoles(token: string | null): string[] {
    const claimed = jwtClaims(token)?.roles;
    return Array.isArray(claimed) ? (claimed as string[]) : [];
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
    language: string;
  }): Promise<RegisterResult> {
    const { data } = await api.post<{ data: RegisterResult }>("/auth/register/", payload);
    return data.data;
  }

  async function loadProfile() {
    try {
      const { data } = await api.get<{ data: Profile }>("/profile/me/");
      profile.value = data.data;
      profileRetries = 0;
    } catch (e) {
      // Profile service may be degraded; auth still succeeds.
      profile.value = null;
      // Profiles are provisioned from an event after registration, so a brand
      // new account can log in before its profile exists.
      if (apiError(e).code === "not_found" && profileRetries < MAX_PROFILE_RETRIES) {
        profileRetries += 1;
        window.setTimeout(() => {
          if (account.value && !profile.value) void loadProfile();
        }, profileRetries * 1000);
      }
    }
  }

  /** Restore a session on app boot from a persisted refresh token. */
  async function bootstrap() {
    sessionUnavailable.value = false;
    if (tokenStore.access || tokenStore.refresh) {
      try {
        await loadAccount();
        roles.value = decodeRoles(tokenStore.access);
        await loadProfile();
        realtime.connect();
      } catch (e) {
        account.value = null;
        // Only a real 401 ends the session. Network errors and 5xx keep the
        // tokens so the next attempt can still restore it.
        if (isAuthFailure(e)) tokenStore.clear();
        else sessionUnavailable.value = true;
      }
    }
    ready.value = true;
  }

  /**
   * End the session in this browser, then hard-reload: only a fresh page
   * guarantees no KeepAlive view or store state reaches the next account.
   * `remote: false` skips revoking a session the server already rejected.
   */
  async function logout({ remote = true }: { remote?: boolean } = {}) {
    if (remote) {
      try {
        await api.post("/auth/logout/", { refresh_token: tokenStore.refresh });
      } catch {
        // Best-effort server-side revocation.
      }
    }
    tokenStore.clear();
    realtime.close();
    useDirectoryStore().clear();
    try {
      localStorage.removeItem("tara.recentSearches");
    } catch {
      // Storage may be unavailable (private mode).
    }
    window.location.assign("/login");
  }

  return {
    account,
    profile,
    ready,
    sessionUnavailable,
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
