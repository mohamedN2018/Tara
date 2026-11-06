/**
 * The optional topic picker after sign-up (Tara Intelligence WP 6.6, owner decision 11).
 *
 * Sign-up remembers the new account's id in this browser; the first sign-in of that
 * account (or sign-up itself, when the account is active at once) opens
 * `/welcome/topics`, which asks the server whether the account has onboarded
 * (`onboarded_at`) and goes on to Home when it has. Only the id is kept here.
 */

const KEY = "tara.pickTopics";

export function markTopicsToPick(accountId: string | undefined | null): void {
  if (!accountId) return;
  try {
    localStorage.setItem(KEY, accountId);
  } catch {
    // Storage may be unavailable (private mode): the picker is optional anyway.
  }
}

export function topicsToPick(accountId: string | undefined | null): boolean {
  if (!accountId) return false;
  try {
    return localStorage.getItem(KEY) === accountId;
  } catch {
    return false;
  }
}

export function topicsPicked(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // Nothing to forget.
  }
}

/** Where to go after sign-in: the picker first when this account has it pending. */
export function afterSignIn(accountId: string | undefined | null, target: string): string | { path: string; query: { next: string } } {
  return topicsToPick(accountId) ? { path: "/welcome/topics", query: { next: target } } : target;
}
