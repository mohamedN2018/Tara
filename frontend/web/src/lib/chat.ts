// Pure message-list helpers. The API pages newest first; the UI keeps a single
// list oldest first, so "last" is always the true newest message.
import { isHeic } from "@/lib/heic";
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
export const ATTACH_ACCEPT = "image/*,.heic,.heif,video/mp4,video/webm,application/pdf";

/** What a picked file becomes in chat, or null when chat does not take it. */
export function attachmentKind(file: { type: string; name?: string }): AttachmentKind | null {
  const type = file.type.toLowerCase();
  // An iPhone photo can come with no type at all; media converts HEIC to JPEG.
  if (type.startsWith("image/") || isHeic(file)) return "image";
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

/** What to show for a message without text: its type, with an icon. */
export function typePreview(type: string, t: (key: string) => string): string {
  if (type === "image") return `📷 ${t("messages.photo")}`;
  if (type === "voice" || type === "audio") return `🎤 ${t("messages.voiceNote")}`;
  if (type === "video") return `🎬 ${t("messages.video")}`;
  if (type === "file") return `📄 ${t("messages.file")}`;
  return "…";
}

/** A conversation's title: its own, or the other members' names in the UI's list style. */
export function conversationTitle(
  c: { title?: string | null; members: string[] },
  selfId: string | undefined,
  label: (id: string) => string,
  locale: string,
  fallback: string,
): string {
  if (c.title) return c.title;
  const names = c.members.filter((m) => m !== selfId).map(label);
  if (!names.length) return fallback;
  try {
    // "a وb" in Arabic, "a, b" in English.
    return new Intl.ListFormat(locale, { style: "short", type: "unit" }).format(names);
  } catch {
    return names.join(", ");
  }
}

/**
 * The inbox row's second line: "You: hi", "Sam: hi" in groups, the text alone in
 * a DM from the other side, or the attachment type. Empty when there is nothing.
 */
export function lastMessagePreview(
  c: { type: string; last_message?: { sender_id: string; type: string; body: string; deleted: boolean } | null },
  selfId: string | undefined,
  label: (id: string) => string,
  t: (key: string, named?: Record<string, unknown>) => string,
): string {
  const m = c.last_message;
  if (!m) return "";
  if (m.type === "system") return "";
  const text = m.deleted ? t("messages.deleted") : m.body.trim() || typePreview(m.type, t);
  if (selfId && m.sender_id === selfId) return t("messenger.youSaid", { text });
  if (c.type === "group") return t("messenger.theySaid", { name: label(m.sender_id), text });
  return text;
}

/**
 * The same preview split for display: who said it (null in a DM from the other
 * side) and the text. The UI isolates the two (``<bdi>`` and ``dir="auto"``) so
 * an Arabic name in the English UI, or the reverse, cannot reorder the line.
 */
const APP_ID_LINK = /https?:\/\/\S+\/(?:stories|marketplace|posts)\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\S*/gi;

/** One-line previews (inbox rows, notifications) leave out links to a story,
 * listing or post: the thread itself shows them, and the id is noise. */
export function withoutAppLinks(text: string): string {
  return text.replace(APP_ID_LINK, "").replace(/\s{2,}/g, " ").trim();
}

export type BodySegment = { text: string } | { to: string; kind: "story" | "listing" | "post" };
const APP_LINK_KINDS = { stories: "story", marketplace: "listing", posts: "post" } as const;
const URL_RE = /https?:\/\/[^\s<>"]+/gi;
const ID_PATH = /^\/(stories|marketplace|posts)\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/?$/i;

/**
 * A message body split so links to Tara's own story, listing and post pages
 * (same origin only) render as a short in-app link instead of a raw URL full
 * of ids. Everything else, external links included, stays plain text.
 */
export function bodySegments(body: string, origin: string): BodySegment[] {
  const out: BodySegment[] = [];
  let last = 0;
  for (const match of body.matchAll(URL_RE)) {
    let url: URL;
    try {
      url = new URL(match[0]);
    } catch {
      continue;
    }
    const hit = url.origin === origin ? ID_PATH.exec(url.pathname) : null;
    if (!hit) continue;
    const at = match.index ?? 0;
    if (at > last) out.push({ text: body.slice(last, at) });
    out.push({ to: `/${hit[1].toLowerCase()}/${hit[2]}`, kind: APP_LINK_KINDS[hit[1].toLowerCase() as keyof typeof APP_LINK_KINDS] });
    last = at + match[0].length;
  }
  if (last < body.length) out.push({ text: body.slice(last) });
  return out;
}

export function previewParts(
  c: { type: string; last_message?: { sender_id: string; type: string; body: string; deleted: boolean } | null },
  selfId: string | undefined,
  label: (id: string) => string,
  t: (key: string, named?: Record<string, unknown>) => string,
): { who: string | null; text: string } {
  const m = c.last_message;
  if (!m || m.type === "system") return { who: null, text: "" };
  const body = withoutAppLinks(m.body);
  const text = m.deleted ? t("messages.deleted") : body || typePreview(m.type, t);
  if (selfId && m.sender_id === selfId) return { who: t("messenger.you"), text };
  if (c.type === "group") return { who: label(m.sender_id), text };
  return { who: null, text };
}

/**
 * Group "Seen by" avatars: for each message id, the other members whose read
 * pointer stops exactly there (the newest message each one has read). Members
 * whose pointer is unknown or points at a message not loaded are left out.
 */
export function seenByAt(
  messages: { id: string; seq?: number | null; sender_id: string }[],
  states: { account_id: string; last_read_message_id: string | null; last_read_seq?: number }[],
  selfId: string,
): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  if (!messages.length) return out;
  const ids = new Set(messages.map((m) => m.id));
  const withSeq = messages.filter((m) => typeof m.seq === "number");
  for (const s of states) {
    if (s.account_id === selfId) continue;
    let at: string | null = null;
    if (typeof s.last_read_seq === "number" && s.last_read_seq > 0 && withSeq.length) {
      // The newest loaded message at or below the pointer.
      for (const m of withSeq) if ((m.seq as number) <= (s.last_read_seq as number)) at = m.id;
    } else if (s.last_read_message_id && ids.has(s.last_read_message_id)) {
      at = s.last_read_message_id;
    }
    if (!at) continue;
    // Their own message says nothing about what they have seen.
    if (messages.find((m) => m.id === at)?.sender_id === s.account_id) continue;
    (out[at] ??= []).push(s.account_id);
  }
  return out;
}

/**
 * Page and support threads: one member writes, a team answers. The team's
 * replies are sent as the Page (`sender_id` is the page id) or as Tara Support
 * (this fixed id, never a real account).
 */
export const SUPPORT_SENDER_ID = "018f0000-0000-7000-8000-00000000c0de";

export function isTeamThread(c: { type: string } | null | undefined): boolean {
  return !!c && (c.type === "page" || c.type === "support");
}

/** The other side of a team thread: the Page's name, or Tara Support. */
export function teamThreadTitle(c: { type: string; title: string }, t: (key: string) => string): string {
  if (c.type === "support") return t("chatTeam.support");
  return c.title || t("chatTeam.pageFallback");
}

/** A team reply's sender, named as the team (null when it is a person). */
export function teamSenderName(
  c: { type: string; title: string; page_id?: string | null } | null | undefined,
  senderId: string,
  t: (key: string) => string,
): string | null {
  if (!c || !isTeamThread(c)) return null;
  if (senderId === SUPPORT_SENDER_ID || (c.page_id && senderId === c.page_id)) return teamThreadTitle(c, t);
  return null;
}
