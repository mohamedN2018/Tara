import type { Notification } from "@/types";

/** A row counts as "New" in the dropdown for this long after its last event. */
export const NEW_WINDOW_MS = 24 * 60 * 60 * 1000;
/** Rows the dropdown shows first, and how many more each "See previous" adds. */
export const DROPDOWN_PAGE = 8;

const when = (n: Notification) => Date.parse(n.last_event_at ?? n.created_at);

/**
 * The dropdown's rows: all of them, or with "Unread" only the unread ones plus
 * those that were unread when the chip was switched on (`keep`), so marking a
 * row read never makes it jump away under the pointer.
 */
export function dropdownRows(items: Notification[], unreadOnly: boolean, keep: ReadonlySet<string>): Notification[] {
  return unreadOnly ? items.filter((n) => !n.read_at || keep.has(n.id)) : items;
}

/**
 * "New" (the last day) and "Earlier", keeping the list's order. A row with an
 * unreadable time goes to Earlier.
 */
export function splitByRecency(
  rows: Notification[],
  now: number = Date.now(),
): { fresh: Notification[]; earlier: Notification[] } {
  const fresh: Notification[] = [];
  const earlier: Notification[] = [];
  for (const n of rows) {
    const at = when(n);
    (Number.isFinite(at) && now - at < NEW_WINDOW_MS ? fresh : earlier).push(n);
  }
  return { fresh, earlier };
}
