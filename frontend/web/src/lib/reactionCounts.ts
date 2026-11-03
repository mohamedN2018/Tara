import { REACTIONS } from "@/lib/reactions";

export type ReactionCounts = Record<string, number>;

/** Counts after the viewer's reaction goes from `prev` to `next` (null = none). */
export function applyReactionChange(
  counts: ReactionCounts,
  prev: string | null,
  next: string | null,
): ReactionCounts {
  if (prev === next) return counts;
  const out = { ...counts };
  if (prev) {
    out[prev] = Math.max(0, (out[prev] ?? 0) - 1);
    if (!out[prev]) delete out[prev];
  }
  if (next) out[next] = (out[next] ?? 0) + 1;
  return out;
}

/** The most used types first (catalogue order breaks ties), at most `limit`. */
export function topReactions(counts: ReactionCounts, limit = 3): string[] {
  const order = REACTIONS.map((r) => r.key);
  return Object.entries(counts)
    .filter(([key, n]) => n > 0 && order.includes(key))
    .sort(([a, x], [b, y]) => y - x || order.indexOf(a) - order.indexOf(b))
    .slice(0, limit)
    .map(([key]) => key);
}
