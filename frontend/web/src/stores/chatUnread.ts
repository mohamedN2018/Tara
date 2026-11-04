import { defineStore } from "pinia";
import { ref } from "vue";

import { realtime } from "@/lib/ws";
import { chatService } from "@/services/chat";

// The messages badge (navbar icon, sidebar, bottom bar): how many conversations
// have unread messages, archived and muted ones left out (the server decides).
// It also tells the server that messages reached this device, which is what
// turns the sender's single tick into "delivered".

const DEBOUNCE_MS = 400;

export const useChatUnreadStore = defineStore("chatUnread", () => {
  const conversations = ref(0);
  const messages = ref(0);
  // Message requests waiting for an answer: shown on the "Message requests" entry only.
  const requests = ref(0);
  let bound = false;
  let timer: number | null = null;
  let deliverPending = false;

  async function refresh(): Promise<void> {
    try {
      const summary = await chatService.unread();
      conversations.value = summary.conversations;
      messages.value = summary.messages;
      requests.value = summary.requests ?? 0;
    } catch {
      // Chat may be degraded; keep the last known count.
    }
  }

  /** Coalesce bursts of frames into one delivered + one unread call. */
  function schedule(deliver: boolean): void {
    deliverPending = deliverPending || deliver;
    if (timer !== null) return;
    timer = window.setTimeout(async () => {
      timer = null;
      const shouldDeliver = deliverPending;
      deliverPending = false;
      if (shouldDeliver) await chatService.markDelivered().catch(() => undefined);
      await refresh();
    }, DEBOUNCE_MS);
  }

  function bind(myId: () => string): void {
    if (bound) return;
    bound = true;
    realtime.on("chat.message.created", (f) => schedule(f.sender !== myId()));
    // My own read (any tab) changes my badge; other people's reads do not.
    realtime.on("chat.message.read", (f) => {
      if (f.reader === myId()) schedule(false);
    });
    realtime.on("chat.message.deleted", () => schedule(false));
    realtime.on("_reconnected", () => schedule(true));
    schedule(true);
  }

  return { conversations, messages, requests, refresh, bind };
});
