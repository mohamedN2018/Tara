import { defineStore } from "pinia";
import { ref } from "vue";

import { realtime } from "@/lib/ws";

// Real presence from the realtime gateway. The gateway only answers for people
// we are allowed to see (DM peers and friends) and only pushes their
// transitions to us, so asking about anyone else simply yields "offline".
//
// Components just call `isOnline(id)` / `lastSeen(id)`: the first call for an
// id registers it, and registered ids are queried in one batch, re-queried on
// reconnect and every minute (a crashed tab never announces that it left).
// `connected` reflects our OWN live socket.

export interface PresenceState {
  online: boolean;
  lastSeen: string | null;
}

const QUERY_BATCH = 100;
const REFRESH_MS = 60_000;

export const usePresenceStore = defineStore("presence", () => {
  const connected = ref(false);
  const states = ref<Record<string, PresenceState>>({});
  const watched = new Set<string>();
  let pending = new Set<string>();
  let flushTimer: number | null = null;
  let bound = false;

  function query(ids: string[]): void {
    for (let i = 0; i < ids.length; i += QUERY_BATCH) {
      realtime.send({ action: "presence.query", account_ids: ids.slice(i, i + QUERY_BATCH) });
    }
  }

  function schedule(): void {
    if (flushTimer !== null || pending.size === 0) return;
    flushTimer = window.setTimeout(() => {
      flushTimer = null;
      const ids = [...pending];
      pending = new Set();
      query(ids);
    }, 50);
  }

  /** Start following these accounts (idempotent). */
  function watch(ids: Array<string | null | undefined>): void {
    for (const id of ids) {
      if (id && !watched.has(id)) {
        watched.add(id);
        pending.add(id);
      }
    }
    schedule();
  }

  function apply(id: unknown, online: unknown, lastSeen: unknown): void {
    if (typeof id !== "string" || !id) return;
    states.value = {
      ...states.value,
      [id]: { online: online === true, lastSeen: typeof lastSeen === "string" ? lastSeen : null },
    };
  }

  function isOnline(userId: string | null | undefined): boolean {
    if (!userId) return false;
    watch([userId]);
    return states.value[userId]?.online === true;
  }

  /** ISO time the account was last seen, when known and not online now. */
  function lastSeen(userId: string | null | undefined): string | null {
    if (!userId) return null;
    watch([userId]);
    const state = states.value[userId];
    return state && !state.online ? state.lastSeen : null;
  }

  /** Bind once to the realtime stream. Safe to call repeatedly. */
  function bind(): void {
    if (bound) return;
    bound = true;
    connected.value = realtime.status === "open";
    realtime.on("_status", (f) => {
      connected.value = f.status === "open";
    });
    realtime.on("presence.changed", (f) => apply(f.account_id, f.online, f.last_seen));
    realtime.on("presence.state", (f) => {
      const list = Array.isArray(f.states) ? (f.states as Record<string, unknown>[]) : [];
      for (const s of list) apply(s.account_id, s.online, s.last_seen);
    });
    // Pushes sent while we were away are lost: ask again.
    realtime.on("_reconnected", () => query([...watched]));
    window.setInterval(() => {
      if (realtime.status === "open") query([...watched]);
    }, REFRESH_MS);
  }

  return { connected, states, isOnline, lastSeen, watch, bind };
});
