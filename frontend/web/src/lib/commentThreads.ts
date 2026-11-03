// Two-level comment threads, as the post service stores them since 1.3:
// a root has `parent_id = null`; every reply has `parent_id = <root>` and
// `reply_to_id = <the comment answered>`, which may be another reply. Roots are
// paged by `/posts/<id>/comments/` and each thread's replies by
// `/comments/<root>/replies/`, so a reply never shows up without its root.

import type { Comment } from "@/services/post";

export interface Thread {
  replies: Comment[];
  cursor: string | null;
  loaded: boolean;
  open: boolean;
}

export const emptyThread = (): Thread => ({ replies: [], cursor: null, loaded: false, open: false });

/** Existing items keep their place (refreshed with newer data); new ones are appended. */
export function mergeById<T extends { id: string }>(existing: T[], incoming: T[]): T[] {
  const fresh = new Map(incoming.map((c) => [c.id, c]));
  const kept = existing.map((c) => fresh.get(c.id) ?? c);
  const known = new Set(existing.map((c) => c.id));
  return kept.concat(incoming.filter((c) => !known.has(c.id)));
}

/**
 * Whose name to show as "@name" before a reply: the author answered, when the
 * reply answers another reply. A reply to the root needs no label (the thread
 * already shows it), and neither does a root.
 */
export function replyTargetAuthor(c: Comment): string | null {
  if (!c.parent_id || !c.reply_to_id || c.reply_to_id === c.parent_id) return null;
  return c.reply_to_author_id ?? null;
}

/** The thread a new comment belongs to: its root, or itself when it is a root. */
export function threadRootId(c: Comment): string {
  return c.parent_id ?? c.id;
}

/** Put a reply the server just created into its thread and bump the root's count. */
export function addReply(
  roots: Comment[],
  threads: Record<string, Thread>,
  created: Comment,
): { roots: Comment[]; threads: Record<string, Thread> } {
  const rootId = threadRootId(created);
  const thread = threads[rootId] ?? emptyThread();
  const already = thread.replies.some((r) => r.id === created.id);
  return {
    roots: already
      ? roots
      : roots.map((r) => (r.id === rootId ? { ...r, reply_count: (r.reply_count ?? 0) + 1 } : r)),
    threads: {
      ...threads,
      [rootId]: { ...thread, open: true, replies: mergeById(thread.replies, [created]) },
    },
  };
}

/** Drop a deleted comment: a root takes its whole thread with it. */
export function removeComment(
  roots: Comment[],
  threads: Record<string, Thread>,
  removed: Comment,
): { roots: Comment[]; threads: Record<string, Thread> } {
  if (!removed.parent_id) {
    const rest = { ...threads };
    delete rest[removed.id];
    return { roots: roots.filter((r) => r.id !== removed.id), threads: rest };
  }
  const rootId = removed.parent_id;
  const thread = threads[rootId];
  return {
    roots: roots.map((r) =>
      r.id === rootId ? { ...r, reply_count: Math.max(0, (r.reply_count ?? 0) - 1) } : r,
    ),
    threads: thread
      ? { ...threads, [rootId]: { ...thread, replies: thread.replies.filter((c) => c.id !== removed.id) } }
      : threads,
  };
}

/** Replace one comment wherever it is (after an edit or a reaction). */
export function replaceComment(
  roots: Comment[],
  threads: Record<string, Thread>,
  updated: Comment,
): { roots: Comment[]; threads: Record<string, Thread> } {
  const swap = (list: Comment[]) => list.map((c) => (c.id === updated.id ? updated : c));
  if (!updated.parent_id) return { roots: swap(roots), threads };
  const thread = threads[updated.parent_id];
  return {
    roots,
    threads: thread ? { ...threads, [updated.parent_id]: { ...thread, replies: swap(thread.replies) } } : threads,
  };
}

/** What `locateComment` needs from the list that shows the comments. */
export interface CommentLocator {
  hasRoot(id: string): boolean;
  /** Load the next page of roots. False at the end or on failure. */
  moreRoots(): Promise<boolean>;
  roots(): Comment[];
  thread(rootId: string): Thread;
  /** Open a thread and load its next page of replies. False on failure. */
  loadReplies(rootId: string): Promise<boolean>;
  setOpen(rootId: string, open: boolean): void;
}

// Bounds for a link whose comment is far down, or gone: requests, not items.
export const LOCATE_ROOT_PAGES = 10;
export const LOCATE_REPLY_PAGES = 30;

/**
 * Make one comment present in the list: a root (paging roots until it shows up)
 * or a reply (its thread opened and paged until it shows up). `rootHint` is the
 * reply's root when the link knows it; otherwise threads with replies are
 * searched in order and closed again when the reply is not there. True if found.
 */
export async function locateComment(
  src: CommentLocator,
  id: string,
  rootHint?: string | null,
): Promise<boolean> {
  const wanted = rootHint && rootHint !== id ? rootHint : id;
  for (let pages = 0; !src.hasRoot(wanted) && pages < LOCATE_ROOT_PAGES; pages++) {
    if (!(await src.moreRoots())) break;
  }
  if (src.hasRoot(id)) return true;

  let budget = LOCATE_REPLY_PAGES;
  const inThread = (rootId: string) => src.thread(rootId).replies.some((r) => r.id === id);
  const scan = async (rootId: string): Promise<boolean> => {
    const wasOpen = src.thread(rootId).open;
    while (!inThread(rootId)) {
      const thread = src.thread(rootId);
      if (thread.loaded && !thread.cursor) break;
      if (budget <= 0) break;
      budget -= 1;
      if (!(await src.loadReplies(rootId))) break;
    }
    const found = inThread(rootId);
    src.setOpen(rootId, found || wasOpen);
    return found;
  };

  if (wanted !== id && src.hasRoot(wanted)) return scan(wanted);
  for (const root of [...src.roots()]) {
    if (budget <= 0) break;
    if ((root.reply_count ?? 0) > 0 && (await scan(root.id))) return true;
  }
  return false;
}
