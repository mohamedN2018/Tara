// Maps identity's account-security error codes to i18n keys under
// `accountSecurity.*`, so the forms can show a message next to the right field.
import { apiError } from "./api";
import { errorKey } from "./errors";

/** The `code` of the first error detail (optionally for one field). */
export function detailCode(error: unknown, field?: string): string | undefined {
  const details = apiError(error).details ?? [];
  return details.find((d) => !field || d.field === field)?.code;
}

const DETAIL_KEYS: Record<string, string> = {
  invalid_password: "accountSecurity.errors.wrongPassword",
  no_password: "accountSecurity.errors.noPassword",
  weak_password: "accountSecurity.errors.weakPassword",
  same_password: "accountSecurity.errors.samePassword",
  same_email: "accountSecurity.errors.sameEmail",
  invalid_google_credential: "accountSecurity.google.failed",
};

const CODE_KEYS: Record<string, string> = {
  account_exists: "accountSecurity.google.accountExists",
  already_linked: "accountSecurity.google.alreadyLinked",
  last_login_method: "accountSecurity.google.lastMethod",
  conflict: "accountSecurity.errors.conflict",
};

/** i18n key for a failed account-security call. */
export function securityErrorKey(error: unknown, overrides: Record<string, string> = {}): string {
  const { code } = apiError(error);
  if (overrides[code]) return overrides[code];
  const detail = detailCode(error);
  if (code === "validation_error" && detail && DETAIL_KEYS[detail]) return DETAIL_KEYS[detail];
  return CODE_KEYS[code] ?? errorKey(code);
}

/** Which field a validation failure belongs to, if any. */
export function errorField(error: unknown): string | undefined {
  const details = apiError(error).details ?? [];
  return details[0]?.field ?? undefined;
}
