/**
 * The "Complete your profile" step after sign-up (plan 08, track 1D).
 *
 * Sign-up and email verification remember the new account's id in this
 * browser; once that account signs in, /home offers a profile photo until it
 * is added or dismissed. Only the id is kept, nothing about the person.
 */

const KEY = "tara.completeProfile";

export function markProfileToComplete(accountId: string | undefined | null): void {
  if (!accountId) return;
  try {
    localStorage.setItem(KEY, accountId);
  } catch {
    // Storage may be unavailable (private mode): the step is a convenience.
  }
}

export function profileToComplete(accountId: string | undefined | null): boolean {
  if (!accountId) return false;
  try {
    return localStorage.getItem(KEY) === accountId;
  } catch {
    return false;
  }
}

export function profileCompleted(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // Nothing to forget.
  }
}
