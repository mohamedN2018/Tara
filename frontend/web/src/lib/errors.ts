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

// A media id a service refused to attach (avatar, cover, ad image). Profile
// sends it as the error code, ads as a validation detail: both are read.
const MEDIA_KEYS: Record<string, string> = {
  media_not_owned: "errors.mediaNotOwned",
  media_kind_not_allowed: "errors.mediaKind",
  media_not_ready: "errors.mediaNotReady",
};

/** i18n key for a refused media attachment, or null when the failure is something else. */
export function mediaErrorKey(error: unknown): string | null {
  const { code, details = [] } = apiError(error);
  const hit = [code, ...details.map((d) => d.code)].find((c) => c in MEDIA_KEYS);
  return hit ? MEDIA_KEYS[hit] : null;
}

/** i18n key for a backend error code. */
export function errorKey(code: string): string {
  return `errors.${CODES.has(code) ? code : "unknown"}`;
}

/** Localised text for a failure. `overrides` maps a code to a more specific key. */
export function errorMessage(error: unknown, overrides: Record<string, string> = {}): string {
  const { code } = apiError(error);
  return i18n.global.t(overrides[code] ?? errorKey(code));
}
