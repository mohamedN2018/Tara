// Token storage. Dev/SPA flow keeps the refresh token client-side (the API also
// sets an httpOnly cookie for production web; see docs ADR-005). Decoupled from
// the Pinia store to avoid circular imports in the axios interceptor.
//
// localStorage is the only source of truth: refresh tokens are single-use and
// shared by every tab, so a value cached in memory goes stale as soon as another
// tab rotates it, and replaying it makes the server revoke the whole session.
const ACCESS_KEY = "tara.access";
const REFRESH_KEY = "tara.refresh";
const REFRESH_LOCK = "tara.auth.refresh";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export const tokenStore = {
  get access(): string | null {
    return read(ACCESS_KEY);
  },

  get refresh(): string | null {
    return read(REFRESH_KEY);
  },

  set(access: string, refresh: string) {
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  },

  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

/** Notify when ANOTHER tab changes the tokens. Returns an unsubscribe fn. */
export function onTokensChangedElsewhere(handler: () => void): () => void {
  const listener = (event: StorageEvent) => {
    // A null key means localStorage.clear().
    if (event.key === null || event.key === ACCESS_KEY || event.key === REFRESH_KEY) handler();
  };
  window.addEventListener("storage", listener);
  return () => window.removeEventListener("storage", listener);
}

/** Decode a JWT payload locally. Returns null when it isn't readable. */
export function jwtClaims(token: string | null): Record<string, unknown> | null {
  if (!token) return null;
  try {
    const part = token.split(".")[1];
    const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
    const pad = b64.length % 4 ? "=".repeat(4 - (b64.length % 4)) : "";
    const claims: unknown = JSON.parse(atob(b64 + pad));
    return claims && typeof claims === "object" ? (claims as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/** True when the token is missing, unreadable, or expires within `skewSeconds`. */
export function isTokenExpired(token: string | null, skewSeconds = 30): boolean {
  const exp = jwtClaims(token)?.exp;
  return typeof exp !== "number" || exp * 1000 <= Date.now() + skewSeconds * 1000;
}

/**
 * Run `fn` while holding a lock shared by every tab, so only one rotates the
 * refresh token at a time. navigator.locks needs a secure context (https or
 * localhost); elsewhere this is only safe within the tab.
 */
export function withRefreshLock<T>(fn: () => Promise<T>): Promise<T> {
  if (typeof navigator !== "undefined" && navigator.locks) {
    return navigator.locks.request(REFRESH_LOCK, fn) as Promise<T>;
  }
  return fn();
}
