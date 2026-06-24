import { defineStore } from "pinia";
import { ref } from "vue";

import { realtime } from "@/lib/ws";

// The realtime gateway does NOT expose a "who is online" feed, so we derive
// presence honestly from real activity: when a frame originating from a user
// arrives (typing / message / reaction / new post), mark them active for a TTL.
// `connected` reflects our OWN live socket. No fabricated/always-on status.
const ACTOR_KEYS = ["actor_id", "sender", "reactor", "reader", "author_id"];

export const usePresenceStore = defineStore("presence", () => {
  const connected = ref(false);
  const active = ref<Record<string, number>>({}); // userId -> expiry (ms epoch)
  let bound = false;

  function markActive(userId: unknown, ttlMs = 90_000): void {
    if (typeof userId !== "string" || !userId) return;
    active.value = { ...active.value, [userId]: Date.now() + ttlMs };
  }

  function isOnline(userId: string | null | undefined): boolean {
    if (!userId) return false;
    const exp = active.value[userId];
    return !!exp && exp > Date.now();
  }

  function prune(): void {
    const now = Date.now();
    const next: Record<string, number> = {};
    for (const [k, v] of Object.entries(active.value)) {
      if (v > now) next[k] = v;
    }
    active.value = next;
  }

  /** Bind once to the realtime stream. Safe to call repeatedly. */
  function bind(): void {
    if (bound) return;
    bound = true;
    connected.value = realtime.status === "open";
    realtime.on("_status", (f) => {
      connected.value = f.status === "open";
    });
    realtime.on("*", (f) => {
      const ttl = f.event === "conversation.typing" ? 12_000 : 90_000;
      for (const key of ACTOR_KEYS) markActive(f[key], ttl);
    });
    window.setInterval(prune, 15_000);
  }

  return { connected, isOnline, markActive, bind };
});
