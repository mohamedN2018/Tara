// Names and avatars of the people the signed-in owner blocked, for their own
// Blocked lists (Settings > Content preferences, Connections). The shared
// directory can't name them: /users/lookup/ leaves out anyone blocked either
// way, so every row read "Unknown user". POST /profile/me/blocked/lookup/
// answers only the caller's own blocks. Kept out of the directory store on
// purpose, so a blocked person is never named anywhere else in the app.
import { reactive } from "vue";

import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import type { UserCard } from "@/services/profile";

const BATCH = 100;
const cards = reactive<Record<string, UserCard | null>>({});

// A block made a moment ago reaches profile's copy of the block list through an
// event, so a miss is asked again once after a short pause.
const RETRY_MS = 2000;

export async function loadBlockedCards(ids: string[], retry = true): Promise<void> {
  const missing = ids.filter((id) => !cards[id]);
  const misses: string[] = [];
  for (let i = 0; i < missing.length; i += BATCH) {
    const batch = missing.slice(i, i + BATCH);
    try {
      const { data } = await api.post<{ data: UserCard[] }>("/profile/me/blocked/lookup/", { ids: batch });
      const found = new Map(data.data.map((c) => [c.account_id, c]));
      for (const id of batch) {
        cards[id] = found.get(id) ?? null;
        if (!found.has(id)) misses.push(id);
      }
    } catch {
      // Left unknown: the row shows the neutral label and can still be unblocked.
    }
  }
  if (retry && misses.length) setTimeout(() => void loadBlockedCards(misses, false), RETRY_MS);
}

export function blockedLabel(id: string): string {
  const card = cards[id];
  if (card) return card.display_name || card.handle;
  return id in cards ? i18n.global.t("profile.unknownUser") : "…";
}

export function blockedAvatar(id: string): string | null {
  return cards[id]?.avatar_media_id ?? null;
}

export function blockedHandle(id: string): string | null {
  return cards[id]?.handle ?? null;
}

/** Sign-out: nothing may carry over to the next account. */
export function clearBlockedCards(): void {
  for (const id of Object.keys(cards)) delete cards[id];
}
