import { defineStore } from "pinia";
import { ref } from "vue";

import { i18n } from "@/i18n";
import { profileService, type UserCard } from "@/services/profile";

// A best-effort id → display-name directory. Reading a name asks for it: unknown
// ids are collected and resolved through /users/lookup/ in debounced batches, so
// the UI never has to show an id. Entries only ever come from API responses, and
// are persisted so names show instantly next time. Users the server won't
// describe (blocked, deleted) fall back to a neutral label — never a raw id.
interface Entry {
  name: string;
  avatar?: string | null;
  handle?: string;
  at: number;
}

// v2: the old key could hold names taken from the `?name=` URL param.
const KEY = "tara.directory.v2";
const LEGACY_KEY = "tara.directory";
const BATCH_SIZE = 100;
const DEBOUNCE_MS = 40;
const MAX_AGE_MS = 60 * 60 * 1000;
const FAILURE_COOLDOWN_MS = 5000;

function load(): Record<string, Entry> {
  try {
    localStorage.removeItem(LEGACY_KEY);
    const raw = JSON.parse(localStorage.getItem(KEY) || "{}");
    return raw && typeof raw === "object" ? raw : {};
  } catch {
    return {};
  }
}

export const useDirectoryStore = defineStore("directory", () => {
  const entries = ref<Record<string, Entry>>(load());
  const unavailable = ref<Record<string, true>>({});
  let saveTimer: number | null = null;

  const queued = new Set<string>();
  const inflight = new Set<string>();
  let flushTimer: number | null = null;
  let cooldownUntil = 0;
  let generation = 0;

  function persist() {
    if (saveTimer) window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => {
      try {
        localStorage.setItem(KEY, JSON.stringify(entries.value));
      } catch {
        // storage may be unavailable (private mode)
      }
    }, 500);
  }

  function remember(
    id?: string | null,
    name?: string | null,
    avatar?: string | null,
    handle?: string | null,
  ) {
    if (!id || !name) return;
    const prev = entries.value[id];
    entries.value[id] = {
      name,
      avatar: avatar === undefined ? (prev?.avatar ?? null) : avatar,
      handle: handle ?? prev?.handle,
      at: Date.now(),
    };
    if (unavailable.value[id]) delete unavailable.value[id];
    persist();
  }

  function rememberCard(card: UserCard) {
    remember(card.account_id, card.display_name || card.handle, card.avatar_media_id, card.handle);
  }

  async function lookup(ids: string[]) {
    const started = generation;
    ids.forEach((id) => inflight.add(id));
    try {
      const cards = await profileService.lookup(ids);
      if (started !== generation) return;
      cards.forEach(rememberCard);
      const found = new Set(cards.map((c) => c.account_id));
      for (const id of ids) {
        if (found.has(id)) continue;
        unavailable.value[id] = true;
        if (entries.value[id]) delete entries.value[id];
      }
    } catch {
      cooldownUntil = Date.now() + FAILURE_COOLDOWN_MS;
    } finally {
      ids.forEach((id) => inflight.delete(id));
    }
  }

  function flush() {
    flushTimer = null;
    const ids = [...queued];
    queued.clear();
    for (let i = 0; i < ids.length; i += BATCH_SIZE) void lookup(ids.slice(i, i + BATCH_SIZE));
  }

  /** Ask for an id unless we already have it. Render-safe: mutates no reactive state. */
  function request(id: string) {
    const entry = entries.value[id];
    if (entry && Date.now() - entry.at < MAX_AGE_MS) return;
    if (unavailable.value[id] || queued.has(id) || inflight.has(id)) return;
    if (Date.now() < cooldownUntil) return;
    queued.add(id);
    if (flushTimer === null) flushTimer = window.setTimeout(flush, DEBOUNCE_MS);
  }

  function nameOf(id?: string | null): string | undefined {
    if (!id) return undefined;
    request(id);
    return entries.value[id]?.name;
  }
  function avatarOf(id?: string | null): string | null {
    if (!id) return null;
    request(id);
    return entries.value[id]?.avatar ?? null;
  }

  // Convenience for UI: a real name when known, a placeholder while it loads,
  // and a neutral label when the server won't say.
  function label(id?: string | null): string {
    if (!id) return "";
    return nameOf(id) || (unavailable.value[id] ? i18n.global.t("profile.unknownUser") : "…");
  }

  /** Forget everything (logout): nothing may carry over to the next account. */
  function clear() {
    generation += 1;
    if (saveTimer) window.clearTimeout(saveTimer);
    if (flushTimer) window.clearTimeout(flushTimer);
    saveTimer = null;
    flushTimer = null;
    queued.clear();
    inflight.clear();
    entries.value = {};
    unavailable.value = {};
    try {
      localStorage.removeItem(KEY);
    } catch {
      // storage may be unavailable (private mode)
    }
  }

  return { entries, remember, nameOf, avatarOf, label, clear };
});
