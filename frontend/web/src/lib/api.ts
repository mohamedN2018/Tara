// Axios client for the edge gateway. Attaches the access token, and on 401
// performs a single-flight refresh-token rotation, then retries the request.
import axios, {
  type AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from "axios";

import type { ApiError, Tokens } from "@/types";

import { tokenStore } from "./tokens";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8080/api/v1";

export const api: AxiosInstance = axios.create({ baseURL: BASE, withCredentials: true });

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  if (tokenStore.access) {
    config.headers.set("Authorization", `Bearer ${tokenStore.access}`);
  }
  return config;
});

let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (!tokenStore.refresh) return false;
  if (!refreshing) {
    refreshing = axios
      .post<{ data: Tokens }>(`${BASE}/auth/refresh/`, { refresh_token: tokenStore.refresh })
      .then((resp) => {
        const t = resp.data.data;
        tokenStore.set(t.access_token, t.refresh_token);
        return true;
      })
      .catch(() => {
        tokenStore.clear();
        return false;
      })
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retried?: boolean };
    const isAuthCall = original?.url?.includes("/auth/");
    if (error.response?.status === 401 && original && !original._retried && !isAuthCall) {
      original._retried = true;
      if (await tryRefresh()) {
        return api(original);
      }
      onUnauthorized();
    }
    return Promise.reject(error);
  },
);

/** Extract the uniform error envelope (falls back to a generic message). */
export function apiError(error: unknown): ApiError {
  const e = error as AxiosError<{ error?: ApiError }>;
  return (
    e?.response?.data?.error ?? {
      code: "network_error",
      message: "Network error. Please try again.",
    }
  );
}
