// Pure message-list helpers. The API pages newest first; the UI keeps a single
// list oldest first, so "last" is always the true newest message.
import type { ConversationMemberState, Message, MessageReaction } from "@/types";

function compare(a: Message, b: Message): number {
  const diff = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
  if (diff !== 0) return diff;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

export function oldestFirst(messages: Message[]): Message[] {
  return [...messages].sort(compare);
}

/** Merge by id (incoming wins), keeping the list oldest first with no duplicates. */
export function mergeMessages(existing: Message[], incoming: Message[]): Message[] {
  const byId = new Map(existing.map((m) => [m.id, m]));
  for (const m of incoming) byId.set(m.id, m);
  return oldestFirst([...byId.values()]);
}

/** One member's reaction changed. A null `type` means it was removed. */
export function applyReaction(
  reactions: MessageReaction[],
  accountId: string,
  type: string | null,
): MessageReaction[] {
  const others = reactions.filter((r) => r.account_id !== accountId);
  return type ? [...others, { account_id: accountId, type }] : others;
}

/** Reaction counts by type, most used first. */
export function reactionSummary(reactions: MessageReaction[]): { type: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const r of reactions) counts.set(r.type, (counts.get(r.type) ?? 0) + 1);
  return [...counts].map(([type, count]) => ({ type, count })).sort((a, b) => b.count - a.count);
}

/** Has any other member read my latest message? */
export function isSeenByOthers(
  messages: Message[],
  states: ConversationMemberState[],
  myId: string,
): boolean {
  return states.some(
    (s) => s.account_id !== myId && isSeen(messages, s.last_read_message_id, myId),
  );
}

/**
 * Has the peer read my latest message? The receipt must be in the loaded list;
 * a receipt for a message at or after mine means mine was read too.
 */
export function isSeen(messages: Message[], readUpToId: string | null, myId: string): boolean {
  if (!readUpToId) return false;
  const readIndex = messages.findIndex((m) => m.id === readUpToId);
  if (readIndex < 0) return false;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].sender_id === myId) return readIndex >= i;
  }
  return false;
}

// ---- delivery ticks -------------------------------------------------------------

export type DeliveryStatus = "sent" | "delivered" | "read";

/**
 * Ticks for one of my messages, from the other members' sequence pointers.
 * In a group a message is read (or delivered) only once every other member is
 * there. Messages without a sequence (sent before numbering) show "sent".
 */
export function deliveryStatus(
  message: Message,
  states: ConversationMemberState[],
  myId: string,
): DeliveryStatus | null {
  if (message.sender_id !== myId || message.deleted) return null;
  const seq = message.seq;
  const others = states.filter((s) => s.account_id !== myId);
  if (seq == null || others.length === 0) return "sent";
  if (others.every((s) => (s.last_read_seq ?? 0) >= seq)) return "read";
  const reached = (s: ConversationMemberState) =>
    Math.max(s.last_delivered_seq ?? 0, s.last_read_seq ?? 0) >= seq;
  return others.every(reached) ? "delivered" : "sent";
}

/** Move a member's pointer forward; a late or replayed frame never moves it back. */
export function advancePointer(
  state: ConversationMemberState,
  field: "last_read_seq" | "last_delivered_seq",
  seq: number | null | undefined,
): void {
  if (typeof seq !== "number") return;
  if ((state[field] ?? 0) < seq) state[field] = seq;
  if (field === "last_read_seq" && (state.last_delivered_seq ?? 0) < seq) {
    state.last_delivered_seq = seq;
  }
}

// ---- message lifecycle windows (mirror the chat service settings) --------------------

export const EDIT_WINDOW_MS = 15 * 60 * 1000;
export const DELETE_WINDOW_MS = 60 * 60 * 1000;

function within(createdAt: string, windowMs: number, now: number): boolean {
  return now - new Date(createdAt).getTime() <= windowMs;
}

export function canEdit(m: Message, myId: string, now = Date.now()): boolean {
  return (
    m.sender_id === myId &&
    !m.deleted &&
    !m.forwarded &&
    m.type !== "system" &&
    within(m.created_at, EDIT_WINDOW_MS, now)
  );
}

export function canDeleteForEveryone(m: Message, myId: string, now = Date.now()): boolean {
  return m.sender_id === myId && !m.deleted && within(m.created_at, DELETE_WINDOW_MS, now);
}

/** Drop one message (removed by moderation: it disappears, no tombstone). */
export function withoutMessage(messages: Message[], id: string): Message[] {
  return messages.filter((m) => m.id !== id);
}

// ---- attachments ----------------------------------------------------------------

export type AttachmentKind = "image" | "video" | "file";

export const MAX_VIDEO_BYTES = 64 * 1024 * 1024;
export const MAX_FILE_BYTES = 25 * 1024 * 1024;
export const ATTACH_ACCEPT = "image/*,video/mp4,video/webm,application/pdf";

/** What a picked file becomes in chat, or null when chat does not take it. */
export function attachmentKind(file: { type: string }): AttachmentKind | null {
  const type = file.type.toLowerCase();
  if (type.startsWith("image/")) return "image";
  if (type === "video/mp4" || type === "video/webm") return "video";
  if (type === "application/pdf") return "file";
  return null;
}

export function tooLarge(kind: AttachmentKind, bytes: number): boolean {
  if (kind === "video") return bytes > MAX_VIDEO_BYTES;
  if (kind === "file") return bytes > MAX_FILE_BYTES;
  return false;
}

export function formatBytes(bytes: number | null | undefined, locale = "en"): string {
  if (!bytes || bytes < 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit === 0 || value >= 10 ? 0 : 1;
  return `${value.toLocaleString(locale, { maximumFractionDigits: digits })} ${units[unit]}`;
}

/** Badge text for an unread count. */
export function badgeText(count: number): string {
  return count > 99 ? "99+" : String(count);
}
