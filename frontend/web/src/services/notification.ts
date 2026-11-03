import { api } from "@/lib/api";
import type { CursorPage, Notification } from "@/types";

// { kind: { channel: enabled } }, e.g. { follow: { in_app: false } }.
export type NotificationPrefs = Record<string, Record<string, boolean>>;

export interface NotificationPreferences {
  prefs: NotificationPrefs;
  quiet_hours: { start?: string; end?: string; timezone?: string };
}

export const notificationService = {
  async getPreferences(): Promise<NotificationPreferences> {
    const { data } = await api.get<{ data: NotificationPreferences }>("/notifications/preferences/");
    return { prefs: data.data?.prefs ?? {}, quiet_hours: data.data?.quiet_hours ?? {} };
  },
  async updatePreferences(payload: Partial<NotificationPreferences>): Promise<NotificationPreferences> {
    const { data } = await api.patch<{ data: NotificationPreferences }>(
      "/notifications/preferences/",
      payload,
    );
    return { prefs: data.data?.prefs ?? {}, quiet_hours: data.data?.quiet_hours ?? {} };
  },

  async list(cursor?: string): Promise<CursorPage<Notification>> {
    const { data } = await api.get<CursorPage<Notification>>("/notifications/", {
      params: { cursor },
    });
    return data;
  },

  async unreadCount(): Promise<number> {
    const { data } = await api.get<{ data: { unread: number } }>("/notifications/unread-count/");
    return data.data.unread;
  },

  // Single endpoint: POST /notifications/read/ with {ids, all}.
  async markRead(id: string): Promise<void> {
    await api.post("/notifications/read/", { ids: [id], all: false });
  },

  async markAllRead(): Promise<void> {
    await api.post("/notifications/read/", { ids: [], all: true });
  },
};
