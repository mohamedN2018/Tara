const BASE = "https://tara.invalid";

/**
 * A same-origin path, or null. Parsed the way the browser parses an href, so
 * "//host", "/\host" and "/<tab>/host" (all protocol-relative once tabs are
 * stripped and backslashes turned into slashes) are refused, not only spotted.
 */
export function sameOriginPath(target: unknown): string | null {
  if (typeof target !== "string" || !target.startsWith("/")) return null;
  try {
    const url = new URL(target, BASE);
    return url.origin === BASE ? url.pathname + url.search + url.hash : null;
  } catch {
    return null;
  }
}

/** Where to go after sign-in: a same-origin path from `?redirect=`, else `fallback`. */
export function safeRedirect(target: unknown, fallback = "/home"): string {
  return sameOriginPath(target) ?? fallback;
}
