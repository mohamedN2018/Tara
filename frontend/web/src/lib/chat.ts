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
