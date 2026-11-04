// Shared handlers for notification rows (dropdown and page): open, mark read,
// dismiss, and the inline actions, which call the owning service's real API
// (graph) first and then store the outcome on the notification.
import { useI18n } from "vue-i18n";

import type { InlineAction } from "@/components/notifications/kinds";
import { apiError } from "@/lib/api";
import { graphService } from "@/services/graph";
import { groupsService } from "@/services/groups";
import { notificationService } from "@/services/notification";
import { useNotificationStore } from "@/stores/notifications";
import { useToastStore } from "@/stores/toasts";
import type { Notification } from "@/types";

export function useNotificationActions() {
  const { t } = useI18n();
  const store = useNotificationStore();
  const toasts = useToastStore();

  function open(n: Notification) {
    if (!n.read_at) store.markRead(n.id).catch(() => {}); // navigation goes ahead regardless
  }

  async function read(id: string) {
    await store.markRead(id).catch((e) => toasts.error(e));
  }

  async function dismiss(id: string) {
    await store.remove(id).catch((e) => toasts.error(e));
  }

  async function act(n: Notification, action: InlineAction) {
    await store.withBusy(n.id, async () => {
      try {
        if (action === "accept" || action === "decline") {
          const requestId = String(n.data?.request_id ?? "");
          try {
            if (action === "accept") await graphService.acceptFriendRequest(requestId);
            else await graphService.declineFriendRequest(requestId);
          } catch (e) {
            // Withdrawn, already answered elsewhere, or blocked since: say so and settle it.
            if (apiError(e).code === "not_found") {
              await store.resolve(n.id, "expired");
              toasts.push({ text: t("notifications.resolutions.expired"), icon: "error" });
              return;
            }
            throw e;
          }
          await store.resolve(n.id, action === "accept" ? "accepted" : "declined");
        } else if (action === "follow_back" && n.actor_id) {
          await graphService.follow(n.actor_id);
          await store.resolve(n.id, "followed_back");
        } else if (action === "join" || action === "decline_invite") {
          const ref = String(n.data?.group_handle || n.data?.group_id || "");
          try {
            if (action === "join") await groupsService.join(ref);
            else await groupsService.cancelJoin(ref);
          } catch (e) {
            // The invitation was withdrawn or the group is gone.
            if (apiError(e).code === "not_found") {
              await store.resolve(n.id, "expired");
              toasts.push({ text: t("notifications.resolutions.expired"), icon: "error" });
              return;
            }
            throw e;
          }
          await store.resolve(n.id, action === "join" ? "joined" : "declined");
        }
      } catch (e) {
        toasts.error(e);
      }
    });
  }

  /**
   * "Turn off notifications like this": the in-app and push switches of this
   * kind go off in Settings. `undo` sends null, so the default applies again.
   */
  async function turnOff(n: Notification): Promise<boolean> {
    try {
      await notificationService.updatePreferences({ prefs: { [n.kind]: { in_app: false, push: false } } });
      return true;
    } catch (e) {
      toasts.error(e);
      return false;
    }
  }

  async function undoTurnOff(n: Notification): Promise<boolean> {
    try {
      await notificationService.updatePreferences({ prefs: { [n.kind]: { in_app: null, push: null } } });
      return true;
    } catch (e) {
      toasts.error(e);
      return false;
    }
  }

  return { open, read, dismiss, act, turnOff, undoTurnOff };
}
