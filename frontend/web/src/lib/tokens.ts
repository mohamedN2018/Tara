// Token storage. Dev/SPA flow keeps the refresh token client-side (the API also
// sets an httpOnly cookie for production web; see docs ADR-005). Decoupled from
// the Pinia store to avoid circular imports in the axios interceptor.
const ACCESS_KEY = "tara.access";
const REFRESH_KEY = "tara.refresh";

export const tokenStore = {
  access: localStorage.getItem(ACCESS_KEY),
  refresh: localStorage.getItem(REFRESH_KEY),

  set(access: string, refresh: string) {
    this.access = access;
    this.refresh = refresh;
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  },

  clear() {
    this.access = null;
    this.refresh = null;
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};
