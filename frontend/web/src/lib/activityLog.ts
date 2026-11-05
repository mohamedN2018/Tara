// The activity log's presentation: a sentence key per row, where it links to,
// and grouping rows by local day. Pure, so it is unit tested.
import type { RouteLocationRaw } from "vue-router";

import type { ActivityRow } from "@/services/activity";

/**
 * The i18n key (under `polish.activity.rows`) for a row's sentence. `own` is
 * when the post acted on is mine; `gone` when I can no longer see it.
 */
export function sentenceKey(row: ActivityRow, me: string): string {
  const t = row.target;
  const whose = !t ? "gone" : t.author_type === "user" && t.author_id === me ? "own" : "other";
  switch (row.kind) {
    case "post":
      return row.item_type === "share" ? "shared" : "posted";
    case "save":
      if (row.item_type && row.item_type !== "post") return `saved_${row.item_type}`;
      return `saved_post_${whose}`;
    default:
      return `${row.kind}_${whose}`;
  }
}

export function rowLink(row: ActivityRow): RouteLocationRaw | null {
  if (row.kind === "save" && row.item_id) {
    if (row.item_type === "listing") return `/marketplace/${row.item_id}`;
    if (row.item_type === "page") return { name: "page-by-id", params: { id: row.item_id } };
    if (row.item_type === "video") return `/posts/${row.item_id}`;
  }
  if (!row.target) return null;
  if (row.kind === "comment" && row.item_id) return { path: `/posts/${row.target.post_id}`, query: { comment: row.item_id } };
  return `/posts/${row.target.post_id}`;
}

/** Rows grouped under their local day (YYYY-MM-DD), keeping the server's order. */
export function groupByDay<T extends { created_at: string }>(rows: T[]): { day: string; rows: T[] }[] {
  const out: { day: string; rows: T[] }[] = [];
  for (const row of rows) {
    const d = new Date(row.created_at);
    const day = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const last = out[out.length - 1];
    if (last && last.day === day) last.rows.push(row);
    else out.push({ day, rows: [row] });
  }
  return out;
}
