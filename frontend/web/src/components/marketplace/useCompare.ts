// Listings picked for comparison (up to 4). A per-viewer convenience, so it lives
// in localStorage; every access is guarded because storage can be blocked.
import { computed, ref } from "vue";

export const MAX_COMPARE = 4;
const KEY = "tara.market.compare";

function read(): string[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.filter((x): x is string => typeof x === "string").slice(0, MAX_COMPARE)
      : [];
  } catch {
    return [];
  }
}

function write(ids: string[]): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(ids));
  } catch {
    /* storage unavailable: the selection lasts for this page only */
  }
}

const selected = ref<string[]>(read());

export function useCompare() {
  const isFull = computed(() => selected.value.length >= MAX_COMPARE);

  function has(id: string): boolean {
    return selected.value.includes(id);
  }

  /** Returns false when the list is full and ``id`` is not already in it. */
  function toggle(id: string): boolean {
    if (has(id)) {
      selected.value = selected.value.filter((x) => x !== id);
    } else {
      if (isFull.value) return false;
      selected.value = [...selected.value, id];
    }
    write(selected.value);
    return true;
  }

  function remove(id: string): void {
    if (!has(id)) return;
    selected.value = selected.value.filter((x) => x !== id);
    write(selected.value);
  }

  function clear(): void {
    selected.value = [];
    write([]);
  }

  return { selected, isFull, has, toggle, remove, clear };
}

/** For tests: reload from storage. */
export function _reloadCompare(): void {
  selected.value = read();
}
