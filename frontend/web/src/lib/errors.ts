// Backend error `code`s are stable machine strings; the `message` next to them is
// English-only, so user-facing text always comes from i18n (`errors.<code>`).
import { i18n } from "@/i18n";

import { apiError } from "./api";

const CODES = new Set([
  "validation_error",
  "parse_error",
  "unauthenticated",
  "authentication_failed",
  "permission_denied",
  "not_found",
  "method_not_allowed",
  "conflict",
  "idempotency_conflict",
  "unsupported_media_type",
  "rate_limited",
  "throttled",
  "dependency_unavailable",
  "internal_error",
  "server_error",
  "network_error",
]);

/** i18n key for a backend error code. */
export function errorKey(code: string): string {
  return `errors.${CODES.has(code) ? code : "unknown"}`;
}

/** Localised text for a failure. `overrides` maps a code to a more specific key. */
export function errorMessage(error: unknown, overrides: Record<string, string> = {}): string {
  const { code } = apiError(error);
  return i18n.global.t(overrides[code] ?? errorKey(code));
}
