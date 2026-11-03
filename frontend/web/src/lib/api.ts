// Axios client for the edge gateway. Attaches the access token, and on 401
// performs a refresh-token rotation, then retries the request. Only a rejected
// refresh ends the session: network failures and 5xx must leave it intact.
import axios, {
  type AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from "axios";

import type { ApiError, Tokens } from "@/types";

import { isTokenExpired, tokenStore, withRefreshLock } from "./tokens";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8080/api/v1";
const TIMEOUT_MS = 20_000;

export const api: AxiosInstance = axios.create({
  baseURL: BASE,
  withCredentials: true,
  timeout: TIMEOUT_MS,
});

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const access = tokenStore.access;
  if (access) config.headers.set("Authorization", `Bearer ${access}`);
  return config;
});

/**
 * "ok": a usable access token is stored.
 * "invalid": the server rejected the refresh token; the session is over.
 * "unavailable": network/timeout/5xx/429; the session may well still be valid.
 */
export type RefreshResult = "ok" | "invalid" | "unavailable";

let refreshing: Promise<RefreshResult> | null = null;

async function rotate(staleAccess: string | null): Promise<RefreshResult> {
  // Another tab may have rotated while this one waited for the lock. Spending
  // the refresh token again would trip the server's reuse detection.
  const current = tokenStore.access;
  if (current && current !== staleAccess && !isTokenExpired(current)) return "ok";

  const refreshToken = tokenStore.refresh;
  if (!refreshToken) return "invalid";
  try {
    const resp = await axios.post<{ data: Tokens }>(
      `${BASE}/auth/refresh/`,
      { refresh_token: refreshToken },
      { timeout: TIMEOUT_MS },
    );
    // Logged out (or signed in again) while this was in flight: the answer
    // belongs to a session that is over and must not bring it back.
    if (tokenStore.refresh !== refreshToken) return tokenStore.access ? "ok" : "invalid";
    const t = resp.data.data;
    tokenStore.set(t.access_token, t.refresh_token);
    return "ok";
  } catch (error) {
    if ((error as AxiosError).response?.status === 401) {
      if (tokenStore.refresh === refreshToken) tokenStore.clear();
      return "invalid";
    }
    return "unavailable";
  }
}

/** Rotate tokens: single-flight within the tab, serialised across tabs. */
export function refreshSession(staleAccess: string | null): Promise<RefreshResult> {
  if (!refreshing) {
    refreshing = withRefreshLock(() => rotate(staleAccess)).finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

/** Make sure the stored access token is usable, refreshing it if it has expired. */
export function ensureFreshAccess(): Promise<RefreshResult> {
  const access = tokenStore.access;
  if (access && !isTokenExpired(access)) return Promise.resolve("ok");
  return refreshSession(access);
}

/** Tell the app the session is over (the refresh token was rejected). */
export function notifyUnauthorized() {
  onUnauthorized();
}

// Calls where a 401 is the answer itself, not a sign of an expired access token.
const NO_REFRESH = /\/auth\/(login|register|refresh|logout|google)\/?(\?.*)?$/;
export const skipsRefresh = (url?: string): boolean => NO_REFRESH.test(url ?? "");

api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retried?: boolean };
    if (error.response?.status === 401 && original && !original._retried && !skipsRefresh(original.url)) {
      original._retried = true;
      const sent = original.headers.get("Authorization");
      const result = await refreshSession(typeof sent === "string" ? sent.replace(/^Bearer /, "") : null);
      if (result === "ok") return api(original);
      if (result === "invalid") notifyUnauthorized();
    }
    return Promise.reject(error);
  },
);

/** Extract the uniform error envelope (falls back to a code from the status). */
export function apiError(error: unknown): ApiError {
  const e = error as AxiosError<{ error?: ApiError }>;
  const envelope = e?.response?.data?.error;
  if (envelope?.code) return envelope;
  const status = e?.response?.status;
  if (status === undefined) return { code: "network_error", message: "Network error. Please try again." };
  if (status === 429) return { code: "rate_limited", message: "Too many requests." };
  if (status >= 500) return { code: "server_error", message: "Server error." };
  return { code: "request_failed", message: "Request failed." };
}

/** The HTTP status of a failed request; undefined when it never got an answer. */
export function httpStatus(error: unknown): number | undefined {
  return (error as AxiosError)?.response?.status;
}

/** True when a failure means the server rejected the credentials themselves. */
export function isAuthFailure(error: unknown): boolean {
  return httpStatus(error) === 401;
}
