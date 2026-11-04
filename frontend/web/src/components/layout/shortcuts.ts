import { groupPath, groupsService } from "@/services/groups";
import { pageService } from "@/services/pages";

/** One "Your shortcuts" entry: a page the viewer manages or a group they belong to. */
export interface Shortcut {
  kind: "page" | "group";
  id: string;
  name: string;
  to: string;
  mediaId: string | null;
}

export const MAX_SHORTCUTS = 10;

/**
 * The viewer's shortcuts, from the real APIs: their pages (`/pages/?mine=1`)
 * first, then the groups they are an active member of (`/groups/?scope=mine`).
 * Either source failing just leaves its half out.
 */
export async function loadShortcuts(limit = MAX_SHORTCUTS): Promise<Shortcut[]> {
  const [pages, groups] = await Promise.all([
    pageService.list({ mine: true }).then((p) => p.data).catch(() => []),
    groupsService.list("mine").then((p) => p.data).catch(() => []),
  ]);
  const fromPages: Shortcut[] = pages.map((p) => ({
    kind: "page",
    id: p.id,
    name: p.name,
    to: `/pages/${p.handle}`,
    mediaId: p.avatar_media_id,
  }));
  const fromGroups: Shortcut[] = groups
    .filter((g) => !g.viewer?.state || g.viewer.state === "active")
    .map((g) => ({ kind: "group", id: g.id, name: g.name, to: groupPath(g), mediaId: g.cover_media_id }));
  return [...fromPages, ...fromGroups].slice(0, limit);
}

// Every view mounts its own shell, so the list is reused for a short while
// instead of being fetched again on each navigation.
const CACHE_MS = 60_000;
let cache: { owner: string; at: number; value: Promise<Shortcut[]> } | null = null;

/** `loadShortcuts`, shared across shells for a minute and per account. */
export function cachedShortcuts(owner: string): Promise<Shortcut[]> {
  if (cache && cache.owner === owner && Date.now() - cache.at < CACHE_MS) return cache.value;
  const value = loadShortcuts();
  cache = { owner, at: Date.now(), value };
  return value;
}

export function clearShortcutsCache(): void {
  cache = null;
}
