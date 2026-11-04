import { api } from "@/lib/api";
import type { WebPushSubscription } from "@/lib/pwa";
import type { CursorPage, Notification } from "@/types";

export type NotificationChannel = "in_app" | "push";

// { kind or category: { channel: enabled } }, e.g. { follow: { in_app: false } }.
export type NotificationPrefs = Record<string, Partial<Record<NotificationChannel, boolean>>>;

/** `prefs` with one switch set, or unset (back to inherited) when `value` is undefined. */
export function withSwitch(
  prefs: NotificationPrefs,
  key: string,
  channel: NotificationChannel,
  value: boolean | undefined,
): NotificationPrefs {
  const entry = { ...prefs[key] };
  if (value === undefined) delete entry[channel];
  else entry[channel] = value;
  return { ...prefs, [key]: entry };
}

export interface QuietHours {
  start?: string;
  end?: string;
  timezone?: string;
}

export interface NotificationPreferences {
  prefs: NotificationPrefs;
  quiet_hours: QuietHours;
  message_previews: boolean;
}

// PATCH merges server-side: send only what changed. `null` clears one override.
export interface PreferenceChanges {
  prefs?: Record<string, Partial<Record<NotificationChannel, boolean | null>>>;
  quiet_hours?: QuietHours;
  message_previews?: boolean;
}

export interface NotificationKindInfo {
  kind: string;
  category: string;
  defaults: Record<NotificationChannel, boolean>;
  aggregates: boolean;
  resolutions: string[];
}

export interface NotificationRegistry {
  categories: string[];
  kinds: NotificationKindInfo[];
}

export interface ListOptions {
  cursor?: string | null;
  unread?: boolean;
  category?: string;
  /** One kind, filtered on the server (e.g. "system.notice"). */
  kind?: string;
}

function normalisePrefs(raw: Partial<NotificationPreferences> | undefined): NotificationPreferences {
  const prefs = Object.fromEntries(
    Object.entries(raw?.prefs ?? {}).filter(([, channels]) => channels && typeof channels === "object"),
  );
  return { prefs, quiet_hours: raw?.quiet_hours ?? {}, message_previews: raw?.message_previews !== false };
}

export const notificationService = {
  async pushConfig(): Promise<{ enabled: boolean; public_key: string }> {
    const { data } = await api.get<{ data: { enabled: boolean; public_key: string } }>(
      "/devices/push-config/",
    );
    return data.data;
  },
  async registerWebPush(subscription: WebPushSubscription): Promise<void> {
    await api.post("/devices/push-token/", { platform: "web", subscription });
  },
  async unregisterWebPush(endpoint: string): Promise<void> {
    await api.delete("/devices/push-token/", { data: { endpoint } });
  },

  async getPreferences(): Promise<NotificationPreferences> {
    const { data } = await api.get<{ data: NotificationPreferences }>("/notifications/preferences/");
    return normalisePrefs(data.data);
  },
  async updatePreferences(changes: PreferenceChanges): Promise<NotificationPreferences> {
    const { data } = await api.patch<{ data: NotificationPreferences }>(
      "/notifications/preferences/",
      changes,
    );
    return normalisePrefs(data.data);
  },
  async registry(): Promise<NotificationRegistry> {
    const { data } = await api.get<{ data: NotificationRegistry }>("/notifications/kinds/");
    return data.data;
  },

  async list(options: ListOptions | string = {}): Promise<CursorPage<Notification>> {
    const opts = typeof options === "string" ? { cursor: options } : options;
    const { data } = await api.get<CursorPage<Notification>>("/notifications/", {
      params: {
        cursor: opts.cursor || undefined,
        unread: opts.unread ? "1" : undefined,
        category: opts.category || undefined,
        kind: opts.kind || undefined,
      },
    });
    return data;
  },

  async get(id: string): Promise<Notification> {
    const { data } = await api.get<{ data: Notification }>(`/notifications/${id}/`);
    return data.data;
  },

  async remove(id: string): Promise<void> {
    await api.delete(`/notifications/${id}/`);
  },

  async resolve(id: string, resolution: string): Promise<Notification> {
    const { data } = await api.post<{ data: Notification }>(`/notifications/${id}/resolve/`, {
      resolution,
    });
    return data.data;
  },

  async unreadCount(): Promise<number> {
    const { data } = await api.get<{ data: { unread: number } }>("/notifications/unread-count/");
    return data.data.unread;
  },

  // Single endpoint: POST /notifications/read/ with {ids, all}; at most 100 ids.
  async markRead(ids: string | string[]): Promise<void> {
    const list = (Array.isArray(ids) ? ids : [ids]).slice(0, 100);
    await api.post("/notifications/read/", { ids: list, all: false });
  },

  async markAllRead(): Promise<void> {
    await api.post("/notifications/read/", { ids: [], all: true });
  },
};
