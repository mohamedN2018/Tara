import { defineStore } from "pinia";
import { ref } from "vue";

import { realtime } from "@/lib/ws";
import { notificationService } from "@/services/notification";

export const useNotificationStore = defineStore("notifications", () => {
  const unread = ref(0);
  let bound = false;

  async function refresh() {
    try {
      unread.value = await notificationService.unreadCount();
    } catch {
      // Notification service may be degraded; keep last known count.
    }
  }

  /** Bind once: live increments arrive over the realtime gateway. */
  function bind() {
    if (bound) return;
    bound = true;
    realtime.on("notification", () => {
      unread.value += 1;
    });
  }

  function clear() {
    unread.value = 0;
  }

  return { unread, refresh, bind, clear };
});
