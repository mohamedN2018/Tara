import { defineStore } from "pinia";
import { ref } from "vue";

import { realtime } from "@/lib/ws";
import { notificationService } from "@/services/notification";

export const useNotificationStore = defineStore("notifications", () => {
  const unread = ref(0);
  let bound = false;

  async function refresh() {
    try {
      const count = await notificationService.unreadCount();
      if (Number.isFinite(count) && count >= 0) unread.value = count;
    } catch {
      // Notification service may be degraded; keep last known count.
    }
  }

  /** Bind once: live increments arrive over the realtime gateway. */
  function bind() {
    if (bound) return;
    bound = true;
    // Gateway emits `notification.created` (see realtime bridge).
    realtime.on("notification.created", () => {
      unread.value = (Number.isFinite(unread.value) ? unread.value : 0) + 1;
    });
    // Anything pushed while the socket was down is only recoverable over REST.
    realtime.on("_reconnected", () => void refresh());
  }

  function clear() {
    unread.value = 0;
  }

  return { unread, refresh, bind, clear };
});
