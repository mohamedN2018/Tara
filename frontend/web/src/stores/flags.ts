// Feature flags as the client sees them (admin service, readable by any signed-in
// account). Staff edit them in the console's Feature flags section.
//
// A flag is on for an account when it is enabled and the account's bucket
// (a stable hash of account id and key, 0-99) is below its rollout percentage,
// so the same account keeps the same answer and N% means N% of accounts.
//
// Menu destinations: a flag named `ui.<menu item id>` (for example
// `ui.marketplace`) decides who sees that item in every menu. With no such flag
// the item shows as before. Staff-only items are never hidden by a flag.
// This only shapes what the app shows; the server enforces access on its own.
import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";

import { MENU_CATALOG, UI_FLAG_PREFIX, setFlaggedOff } from "@/components/layout/menuCatalog";
import { api } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

export interface ClientFlag {
  key: string;
  enabled: boolean;
  rollout_pct: number;
}

/** FNV-1a over `accountId:key`, folded to 0-99. */
export function bucket(accountId: string, key: string): number {
  let hash = 0x811c9dc5;
  const text = `${accountId}:${key}`;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash % 100;
}

export function flagOn(flag: ClientFlag, accountId: string): boolean {
  if (!flag.enabled) return false;
  const pct = Math.max(0, Math.min(100, Number(flag.rollout_pct) || 0));
  return pct >= 100 || bucket(accountId, flag.key) < pct;
}

/** Menu item ids a `ui.<id>` flag switches off for this account. */
export function hiddenMenuItems(flags: Record<string, ClientFlag>, accountId: string): string[] {
  return MENU_CATALOG.filter((item) => !item.caps)
    .map((item) => item.id)
    .filter((id) => {
      const flag = flags[`${UI_FLAG_PREFIX}${id}`];
      return !!flag && !flagOn(flag, accountId);
    });
}

export const useFlagsStore = defineStore("flags", () => {
  const flags = ref<Record<string, ClientFlag>>({});
  const accountId = ref("");
  const loaded = ref(false);

  async function load(id: string) {
    accountId.value = id;
    if (!id) {
      flags.value = {};
      loaded.value = false;
      setFlaggedOff([]);
      return;
    }
    try {
      const { data } = await api.get<{ data: ClientFlag[] }>("/admin/feature-flags/");
      if (accountId.value !== id) return; // signed out or switched meanwhile
      const next: Record<string, ClientFlag> = {};
      for (const f of Array.isArray(data?.data) ? data.data : []) {
        if (f && typeof f.key === "string") next[f.key] = f;
      }
      flags.value = next;
      loaded.value = true;
    } catch {
      // Flags unreachable: everything shows as if no flag existed.
      flags.value = {};
    }
    setFlaggedOff(hiddenMenuItems(flags.value, id));
  }

  /** Whether `key` is on for the signed-in account; `fallback` when no such flag exists. */
  function isOn(key: string, fallback = true): boolean {
    const flag = flags.value[key];
    return flag ? flagOn(flag, accountId.value) : fallback;
  }

  return { flags, loaded, load, isOn };
});

/** A reactive flag check for components. */
export function useFlag(key: string, fallback = true) {
  const store = useFlagsStore();
  return computed(() => store.isOn(key, fallback));
}

/** Keep flags in step with the signed-in account (called once from main.ts). */
export function installFlagSync(): void {
  const auth = useAuthStore();
  const store = useFlagsStore();
  watch(
    () => auth.account?.id ?? "",
    (id) => void store.load(id),
    { immediate: true },
  );
}
