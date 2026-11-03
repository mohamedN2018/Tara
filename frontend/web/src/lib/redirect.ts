/** Accept only same-origin paths: a leading "/", never "//" or "/\" (protocol-relative). */
export function safeRedirect(target: unknown, fallback = "/home"): string {
  if (typeof target !== "string" || !target.startsWith("/")) return fallback;
  if (target.startsWith("//") || target.startsWith("/\\")) return fallback;
  return target;
}
