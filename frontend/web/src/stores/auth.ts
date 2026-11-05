import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { api, apiError, isAuthFailure } from "@/lib/api";
import { releasePush, resumePush } from "@/lib/pwa";
import { browserSessionEnded, forgetSignIn, rememberSignIn } from "@/lib/rememberMe";
import { capabilitiesFromClaims, opensConsole } from "@/lib/capabilities";
import { jwtClaims, tokenStore } from "@/lib/tokens";
import { clearBlockedCards } from "@/lib/blockedCards";
import { realtime } from "@/lib/ws";
import { identityService } from "@/services/identity";
import { clearMediaCache } from "@/services/media";
import { useCallStore } from "@/stores/calls";
import { useDirectoryStore } from "@/stores/directory";
import { useUiStore } from "@/stores/ui";
import type { Account, Profile, Tokens } from "@/types";

// register returns the new account in "pending" state (email verification
// required before sign-in); it does NOT return tokens.
interface RegisterResult {
  account_id: string;
  email: string;
  status: string;
}

/** POST /auth/register/ (plan 08, track 1D). The server checks every rule again. */
export interface RegisterPayload {
  first_name: string;
  last_name: string;
  handle: string;
  email: string;
  password: string;
  password_confirm: string;
  date_of_birth: string; // YYYY-MM-DD
  gender: "" | "female" | "male" | "custom" | "prefer_not_to_say";
  gender_custom: string;
  accept_terms: boolean;
  terms_version: string;
  privacy_version: string;
  language: string;
}

const MAX_PROFILE_RETRIES = 5;

// Per-account conveniences kept in this browser, and whose they are. A session
// can end without a logout (expired, revoked elsewhere), so a sign-in by
// someone else must clear them too, not only the logout button.
const ACCOUNT_KEYS = ["tara.recentSearches", "tara.market.compare"];
const DATA_OWNER_KEY = "tara.dataOwner";

function storedOwner(): string | null {
  try {
    return localStorage.getItem(DATA_OWNER_KEY);
  } catch {
    return null;
  }
}

export const useAuthStore = defineStore("auth", () => {
  const account = ref<Account | null>(null);
  const profile = ref<Profile | null>(null);
  const ready = ref(false);
  // A stored session exists but the server couldn't be reached to restore it.
  const sessionUnavailable = ref(false);
  let profileRetries = 0;

  const isAuthenticated = computed(() => !!account.value);
  const roles = ref<string[]>([]);
  // Staff capabilities (`caps` claim; derived from `roles` for older tokens).
  const capabilities = ref<Set<string>>(new Set());
  const isStaff = computed(() => opensConsole(capabilities.value));
  const can = (cap: string) => capabilities.value.has(cap);
  const canAny = (caps: readonly string[]) => caps.some(can);

  // RBAC roles live in the access-token JWT (not in /me/). Decode them locally.
  function decodeRoles(token: string | null): string[] {
    const claimed = jwtClaims(token)?.roles;
    return Array.isArray(claimed) ? claimed.filter((r): r is string => typeof r === "string") : [];
  }

  /** Forget the previous account's cached names, recent searches and comparisons. */
  function clearAccountData(nextOwner: string | null = null) {
    useDirectoryStore().clear();
    clearBlockedCards();
    clearMediaCache();
    try {
      ACCOUNT_KEYS.forEach((key) => localStorage.removeItem(key));
      if (nextOwner) localStorage.setItem(DATA_OWNER_KEY, nextOwner);
      else localStorage.removeItem(DATA_OWNER_KEY);
    } catch {
      // Storage may be unavailable (private mode).
    }
  }

  function applyTokens(t: Tokens) {
    tokenStore.set(t.access_token, t.refresh_token);
    roles.value = decodeRoles(t.access_token);
    capabilities.value = capabilitiesFromClaims(jwtClaims(t.access_token));
  }

  // login returns the tokens directly (flat). The account is fetched from /me/.
  // `identifier` is an email or a username (5.6). Unticked `remember`: the
  // session ends when the browser closes (lib/rememberMe.ts). `otp` is the
  // second factor, sent on the retry after a `two_factor_required` answer.
  async function login(identifier: string, password: string, remember = true, otp = "") {
    const { data } = await api.post<{ data: Tokens }>("/auth/login/", {
      identifier,
      password,
      remember,
      ...(otp ? { otp } : {}),
    });
    applyTokens(data.data);
    rememberSignIn(remember);
    await loadAccount();
    await loadProfile();
    realtime.connect();
  }

  /** Sign in (or sign up) with a Google ID token. Returns true for a new account. */
  async function loginWithGoogle(credential: string, language: string, otp = ""): Promise<boolean> {
    const result = await identityService.googleSignIn(credential, language, otp);
    applyTokens(result);
    rememberSignIn(true);
    await loadAccount();
    await loadProfile();
    realtime.connect();
    return result.created;
  }

  async function loadAccount() {
    const { data } = await api.get<{ data: Account }>("/me/");
    account.value = data.data;
    if (storedOwner() !== data.data.id) clearAccountData(data.data.id);
    // Language and theme follow the account across devices (settings centre).
    useUiStore().applyAccount(data.data);
    // Login and boot: drop another account's push subscription, re-bind ours.
    void resumePush(data.data.id);
  }

  /** Register a new account. Returns it in "pending" state — the caller should
   *  prompt for email verification, then sign in (no auto-login). */
  async function register(payload: RegisterPayload): Promise<RegisterResult> {
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
    if (browserSessionEnded()) {
      // Signed in without "Remember me", and the browser has been closed since.
      const refresh = tokenStore.refresh;
      tokenStore.clear();
      forgetSignIn();
      clearAccountData();
      if (refresh) void api.post("/auth/logout/", { refresh_token: refresh }).catch(() => {});
    }
    if (tokenStore.access || tokenStore.refresh) {
      try {
        await loadAccount();
        roles.value = decodeRoles(tokenStore.access);
        capabilities.value = capabilitiesFromClaims(jwtClaims(tokenStore.access));
        await loadProfile();
        realtime.connect();
      } catch (e) {
        account.value = null;
        // Only a real 401 ends the session. Network errors and 5xx keep the
        // tokens so the next attempt can still restore it.
        if (isAuthFailure(e)) {
          tokenStore.clear();
          clearAccountData();
          useUiStore().applyAccount(null);
          void releasePush(); // the session expired while the app was closed
        } else sessionUnavailable.value = true;
      }
    } else {
      // Signed out elsewhere (whose logout cleared the tray): no subscription may outlive the session.
      void releasePush({ clearTray: false });
    }
    ready.value = true;
  }

  /**
   * End the session in this browser, then hard-reload: only a fresh page
   * guarantees no KeepAlive view or store state reaches the next account.
   * `remote: false` skips revoking a session the server already rejected.
   */
  async function logout({ remote = true }: { remote?: boolean } = {}) {
    // Hang up and release the camera, microphone and room before the session goes.
    await useCallStore().reset().catch(() => {});
    // Every logout path: unsubscribe this browser locally first (works without a
    // session), so the next account here never gets this account's pushes.
    await releasePush({ remote }).catch(() => {});
    if (remote) {
      try {
        await api.post("/auth/logout/", { refresh_token: tokenStore.refresh });
      } catch {
        // Best-effort server-side revocation.
      }
    }
    tokenStore.clear();
    forgetSignIn();
    realtime.close();
    clearAccountData();
    // Signed out: theme and language clicks stay in this browser (no PATCH /me/).
    useUiStore().applyAccount(null);
    window.location.assign("/login");
  }

  return {
    account,
    profile,
    ready,
    sessionUnavailable,
    isAuthenticated,
    roles,
    capabilities,
    can,
    canAny,
    isStaff,
    login,
    loginWithGoogle,
    register,
    loadProfile,
    bootstrap,
    logout,
  };
});
