import { defineStore } from "pinia";
import { ref } from "vue";

// A best-effort id → display-name directory. The backend exposes no bulk
// id→name lookup, so we accumulate names from every response that carries them
// (search results, profiles you visit, the current user) and persist them in
// localStorage so names fill in across the app and across sessions. Anything
// not yet known falls back to a short id — we never invent a name.
interface Entry {
  name: string;
  avatar?: string | null;
  handle?: string;
}

const KEY = "tara.directory";

function load(): Record<string, Entry> {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "{}");
    return raw && typeof raw === "object" ? raw : {};
  } catch {
    return {};
  }
}

export const useDirectoryStore = defineStore("directory", () => {
  const entries = ref<Record<string, Entry>>(load());
  let saveTimer: number | null = null;

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
    const next: Entry = {
      name,
      avatar: avatar ?? prev?.avatar ?? null,
      handle: handle ?? prev?.handle,
    };
    if (prev && prev.name === next.name && prev.avatar === next.avatar && prev.handle === next.handle) {
      return;
    }
    entries.value[id] = next;
    persist();
  }

  const nameOf = (id?: string | null): string | undefined => (id ? entries.value[id]?.name : undefined);
  const avatarOf = (id?: string | null): string | null =>
    (id && entries.value[id]?.avatar) || null;
  const handleOf = (id?: string | null): string | undefined =>
    id ? entries.value[id]?.handle : undefined;

  // Convenience for UI: a real name when known, else a short id.
  const label = (id?: string | null, len = 8): string =>
    (id && entries.value[id]?.name) || (id ? id.slice(0, len) : "");

  return { entries, remember, nameOf, avatarOf, handleOf, label };
});
