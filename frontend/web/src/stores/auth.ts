import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { api } from "@/lib/api";
import { tokenStore } from "@/lib/tokens";
import { realtime } from "@/lib/ws";
import type { Account, Profile, Tokens } from "@/types";

interface AuthResponse {
  account: Account;
  tokens: Tokens;
}

export const useAuthStore = defineStore("auth", () => {
  const account = ref<Account | null>(null);
  const profile = ref<Profile | null>(null);
  const ready = ref(false);

  const isAuthenticated = computed(() => !!account.value);
  const roles = computed<string[]>(() => (account.value as { roles?: string[] })?.roles ?? []);
  const isStaff = computed(() => roles.value.some((r) => r === "admin" || r === "moderator"));

  function applyTokens(t: Tokens) {
    tokenStore.set(t.access_token, t.refresh_token);
  }

  async function login(email: string, password: string) {
    const { data } = await api.post<{ data: AuthResponse }>("/auth/login/", { email, password });
    applyTokens(data.data.tokens);
    account.value = data.data.account;
    await loadProfile();
    realtime.connect();
  }

  async function register(payload: {
    email: string;
    password: string;
    handle: string;
    display_name: string;
  }) {
    const { data } = await api.post<{ data: AuthResponse }>("/auth/register/", payload);
    applyTokens(data.data.tokens);
    account.value = data.data.account;
    await loadProfile();
    realtime.connect();
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
