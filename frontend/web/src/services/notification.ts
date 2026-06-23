import { api } from "@/lib/api";
import type { CursorPage, Notification } from "@/types";

export const notificationService = {
  async list(cursor?: string): Promise<CursorPage<Notification>> {
    const { data } = await api.get<CursorPage<Notification>>("/notifications/", {
      params: { cursor },
    });
    return data;
  },

  async unreadCount(): Promise<number> {
    const { data } = await api.get<{ data: { count: number } }>("/notifications/unread-count/");
    return data.data.count;
  },

  // Single endpoint: POST /notifications/read/ with {ids, all}.
  async markRead(id: string): Promise<void> {
    await api.post("/notifications/read/", { ids: [id], all: false });
  },

  async markAllRead(): Promise<void> {
    await api.post("/notifications/read/", { ids: [], all: true });
  },
};
