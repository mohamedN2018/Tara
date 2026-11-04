// One live notification list shared by the navbar dropdown and the Notifications
// page (QTech useNotifications.js: a singleton list with upsert by id).
//
// * Live: the realtime `notification.created` frame carries ids only, so the row
//   is fetched by id and upserted (an aggregate that grew moves to the top).
// * Sync: reads, dismissals and resolutions are broadcast to the other tabs of
//   this browser; other devices catch up on reconnect and whenever the tab is
//   shown again. `notification.read` / `notification.deleted` frames are handled
//   too, for when the realtime bridge forwards those events (follow-up).
// * The unread badge always comes from the server, never from loaded rows.
// * Filters (the page's Unread and category chips) are answered by the server
//   (`unread=1`, `category=`) into a second list, so the dropdown keeps the
//   unfiltered one; reads, dismissals and resolutions apply to both.
import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { realtime } from "@/lib/ws";
import { playPing } from "@/lib/sound";
import { notificationService, type QuietHours } from "@/services/notification";
import type { Notification } from "@/types";

const CHANNEL = "tara.notifications";
const COUNT_DEBOUNCE_MS = 250;

type SyncMessage =
  | { type: "read"; ids: string[]; at: string }
  | { type: "read-all"; at: string }
  | { type: "deleted"; ids: string[] }
  | { type: "upsert"; item: Notification };

const sortKey = (n: Notification) => n.last_event_at ?? n.created_at;

export interface NotificationFilter {
  unread: boolean;
  category: string;
}

/** Whether a row belongs in a filtered list. */
export function matchesFilter(n: Notification, f: NotificationFilter): boolean {
  if (f.unread && n.read_at) return false;
  if (f.category && n.category !== f.category) return false;
  return true;
}

const isIdList = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === "string");

/** Another tab's message, checked: a malformed one is dropped, never applied. */
export function parseSync(data: unknown): SyncMessage | null {
  if (!data || typeof data !== "object") return null;
  const m = data as Record<string, unknown>;
  const at = typeof m.at === "string" ? m.at : "";
  if (m.type === "read" && isIdList(m.ids) && at) return { type: "read", ids: m.ids, at };
  if (m.type === "read-all" && at) return { type: "read-all", at };
  if (m.type === "deleted" && isIdList(m.ids)) return { type: "deleted", ids: m.ids };
  const item = m.item as Partial<Notification> | undefined;
  if (m.type === "upsert" && item && typeof item.id === "string" && typeof item.kind === "string") {
    return { type: "upsert", item: item as Notification };
  }
  return null;
}

/** Every open tab has its own socket: only the one being looked at pings. */
function ping(quiet: QuietHours) {
  if (document.visibilityState === "visible") playPing(quiet);
}

export const useNotificationStore = defineStore("notifications", () => {
  const unread = ref(0);
  const items = ref<Notification[]>([]);
  const loaded = ref(false);
  const loading = ref(false);
  const error = ref(false);
  const cursor = ref<string | null>(null);
  const hasMore = ref(false);
  const loadingMore = ref(false);
  const quietHours = ref<QuietHours>({});
  const busy = ref<Record<string, boolean>>({});

  // The filtered list (only while a filter is on).
  const filter = ref<NotificationFilter>({ unread: false, category: "" });
  const filtered = ref<Notification[]>([]);
  const filteredCursor = ref<string | null>(null);
  const filteredHasMore = ref(false);
  const filteredLoading = ref(false);
  const filteredError = ref(false);
  const filteredLoadingMore = ref(false);
  let filterGeneration = 0;
  const filtering = computed(() => filter.value.unread || !!filter.value.category);

  let bound = false;
  // Bumped by load(): a loadMore() or head refresh started before it is stale.
  let listGeneration = 0;
  let channel: BroadcastChannel | null = null;
  let countTimer: number | null = null;
  const fetching = new Map<string, Promise<void>>();
  const unsubs: Array<() => void> = [];

  const hasUnreadLoaded = computed(() => items.value.some((n) => !n.read_at));

  async function refresh() {
    try {
      const count = await notificationService.unreadCount();
      if (Number.isFinite(count) && count >= 0) unread.value = count;
    } catch {
      // Notification service may be degraded; keep last known count.
    }
  }

  function refreshSoon() {
    if (countTimer !== null) return;
    countTimer = window.setTimeout(() => {
      countTimer = null;
      void refresh();
    }, COUNT_DEBOUNCE_MS);
  }

  function placed(list: Notification[], item: Notification): Notification[] {
    const rest = list.filter((n) => n.id !== item.id);
    const key = sortKey(item);
    const at = rest.findIndex((n) => sortKey(n) < key);
    rest.splice(at === -1 ? rest.length : at, 0, item);
    return rest;
  }

  function upsert(item: Notification) {
    items.value = placed(items.value, item);
    if (!filtering.value) return;
    // A row already shown stays (marking it read must not make it jump away);
    // a new one joins only when it matches.
    if (filtered.value.some((n) => n.id === item.id) || matchesFilter(item, filter.value)) {
      filtered.value = placed(filtered.value, item);
    }
  }

  function find(id: string): Notification | undefined {
    return items.value.find((n) => n.id === id) ?? filtered.value.find((n) => n.id === id);
  }

  function post(message: SyncMessage) {
    try {
      channel?.postMessage(message);
    } catch {
      // A closed channel: other tabs catch up when shown.
    }
  }

  function applyRead(ids: string[], at: string) {
    const set = new Set(ids);
    const mark = (n: Notification) => (set.has(n.id) && !n.read_at ? { ...n, read_at: at } : n);
    items.value = items.value.map(mark);
    filtered.value = filtered.value.map(mark);
  }

  function applyUnread(id: string) {
    const unmark = (n: Notification) => (n.id === id ? { ...n, read_at: null } : n);
    items.value = items.value.map(unmark);
    filtered.value = filtered.value.map(unmark);
  }

  function applyDeleted(ids: string[]) {
    const set = new Set(ids);
    items.value = items.value.filter((n) => !set.has(n.id));
    filtered.value = filtered.value.filter((n) => !set.has(n.id));
  }

  /** Switch the page's filter; the server answers it (later pages included). */
  async function setFilter(next: NotificationFilter) {
    filter.value = { ...next };
    if (!filtering.value) {
      ++filterGeneration;
      filtered.value = [];
      filteredCursor.value = null;
      filteredHasMore.value = false;
      filteredError.value = false;
      filteredLoading.value = false;
      return;
    }
    await loadFiltered();
  }

  async function loadFiltered() {
    const generation = ++filterGeneration;
    filteredLoading.value = true;
    filteredError.value = false;
    try {
      const page = await notificationService.list({ unread: filter.value.unread, category: filter.value.category });
      if (generation !== filterGeneration) return;
      filtered.value = page.data;
      filteredCursor.value = page.page.next_cursor;
      filteredHasMore.value = page.page.has_more;
    } catch {
      if (generation === filterGeneration) filteredError.value = true;
    } finally {
      if (generation === filterGeneration) filteredLoading.value = false;
    }
  }

  async function loadMoreFiltered() {
    if (!filteredCursor.value || filteredLoadingMore.value) return;
    const generation = filterGeneration;
    filteredLoadingMore.value = true;
    try {
      const page = await notificationService.list({
        cursor: filteredCursor.value,
        unread: filter.value.unread,
        category: filter.value.category,
      });
      if (generation !== filterGeneration) return;
      const known = new Set(filtered.value.map((n) => n.id));
      filtered.value = [...filtered.value, ...page.data.filter((n) => !known.has(n.id))];
      filteredCursor.value = page.page.next_cursor;
      filteredHasMore.value = page.page.has_more;
    } finally {
      filteredLoadingMore.value = false;
    }
  }

  async function load() {
    const generation = ++listGeneration;
    loading.value = true;
    error.value = false;
    try {
      const page = await notificationService.list();
      if (generation !== listGeneration) return;
      // Keep rows announced while the page was loading.
      const fresh = new Set(page.data.map((n) => n.id));
      const newest = page.data[0] ? sortKey(page.data[0]) : "";
      const live = items.value.filter((n) => !fresh.has(n.id) && !!newest && sortKey(n) > newest);
      items.value = [...live, ...page.data];
      cursor.value = page.page.next_cursor;
      hasMore.value = page.page.has_more;
      loaded.value = true;
    } catch {
      if (generation === listGeneration) error.value = true;
    } finally {
      if (generation === listGeneration) loading.value = false;
    }
  }

  /**
   * Catch up on the newest rows without dropping the pages already scrolled
   * through (tab shown again, socket reconnected).
   */
  async function refreshHead() {
    const generation = listGeneration;
    try {
      const page = await notificationService.list();
      if (generation === listGeneration) page.data.forEach(upsert);
    } catch {
      // The next visibility change or reconnect tries again.
    }
  }

  async function ensureLoaded() {
    if (!loaded.value && !loading.value) await load();
  }

  async function loadMore() {
    if (!cursor.value || loadingMore.value) return;
    const generation = listGeneration;
    loadingMore.value = true;
    try {
      const page = await notificationService.list({ cursor: cursor.value });
      // The list was reloaded meanwhile: this page follows a cursor it no longer has.
      if (generation !== listGeneration) return;
      const known = new Set(items.value.map((n) => n.id));
      items.value = [...items.value, ...page.data.filter((n) => !known.has(n.id))];
      cursor.value = page.page.next_cursor;
      hasMore.value = page.page.has_more;
    } finally {
      loadingMore.value = false;
    }
  }

  /** A row was created or grew: fetch it once, however many frames announce it. */
  function fetchOne(id: string): Promise<void> {
    const pending = fetching.get(id);
    if (pending) return pending;
    const job = (async () => {
      try {
        const before = items.value.find((n) => n.id === id);
        const item = await notificationService.get(id);
        upsert(item);
        post({ type: "upsert", item });
        const isNews = !item.read_at && (!before || sortKey(item) !== sortKey(before));
        if (isNews) ping(quietHours.value);
      } catch {
        // Gone already (dismissed, deleted post) or the service is degraded.
      } finally {
        fetching.delete(id);
      }
    })();
    fetching.set(id, job);
    return job;
  }

  async function markRead(id: string) {
    const item = find(id);
    if (!item || item.read_at) return;
    const at = new Date().toISOString();
    applyRead([id], at);
    unread.value = Math.max(0, unread.value - 1);
    try {
      await notificationService.markRead(id);
      post({ type: "read", ids: [id], at });
    } catch (e) {
      applyUnread(id);
      unread.value += 1;
      throw e;
    }
  }

  async function markAllRead() {
    const at = new Date().toISOString();
    const previous = items.value;
    const previousFiltered = filtered.value;
    const previousCount = unread.value;
    items.value = items.value.map((n) => (n.read_at ? n : { ...n, read_at: at }));
    filtered.value = filtered.value.map((n) => (n.read_at ? n : { ...n, read_at: at }));
    unread.value = 0;
    try {
      await notificationService.markAllRead();
      post({ type: "read-all", at });
    } catch (e) {
      items.value = previous;
      filtered.value = previousFiltered;
      unread.value = previousCount;
      throw e;
    }
  }

  async function remove(id: string) {
    const item = find(id);
    if (!item) return;
    applyDeleted([id]);
    if (!item.read_at) unread.value = Math.max(0, unread.value - 1);
    try {
      await notificationService.remove(id);
      post({ type: "deleted", ids: [id] });
    } catch (e) {
      upsert(item);
      if (!item.read_at) unread.value += 1;
      throw e;
    }
  }

  /** Store an inline action's outcome on the server (the row also becomes read). */
  async function resolve(id: string, resolution: string) {
    const was = find(id);
    const item = await notificationService.resolve(id, resolution);
    upsert(item);
    if (was && !was.read_at) unread.value = Math.max(0, unread.value - 1);
    post({ type: "upsert", item });
    return item;
  }

  async function withBusy<T>(id: string, fn: () => Promise<T>): Promise<T> {
    busy.value = { ...busy.value, [id]: true };
    try {
      return await fn();
    } finally {
      const rest = { ...busy.value };
      delete rest[id];
      busy.value = rest;
    }
  }

  function onSync(message: SyncMessage) {
    if (message.type === "read") {
      applyRead(message.ids, message.at);
    } else if (message.type === "read-all") {
      items.value = items.value.map((n) => (n.read_at ? n : { ...n, read_at: message.at }));
      filtered.value = filtered.value.map((n) => (n.read_at ? n : { ...n, read_at: message.at }));
    } else if (message.type === "deleted") {
      applyDeleted(message.ids);
    } else if (message.type === "upsert") {
      upsert(message.item);
    }
    refreshSoon();
  }

  function onWorkerMessage(event: MessageEvent) {
    const message = event.data as { type?: string; notification_id?: unknown } | null;
    if (message?.type !== "tara.push") return;
    refreshSoon();
    // Usually the realtime frame got here first; fetchOne de-duplicates.
    if (typeof message.notification_id === "string" && loaded.value) void fetchOne(message.notification_id);
  }

  function onVisible() {
    if (document.visibilityState !== "visible") return;
    void refresh();
    if (loaded.value) void refreshHead();
  }

  async function loadQuietHours() {
    try {
      quietHours.value = (await notificationService.getPreferences()).quiet_hours;
    } catch {
      // No quiet hours known: the ping (off by default) is the only thing affected.
    }
  }

  /** Bind once: live rows over the realtime gateway, other tabs over BroadcastChannel. */
  function bind() {
    if (bound) return;
    bound = true;
    unsubs.push(
      realtime.on("notification.created", (frame) => {
        const id = frame.notification_id;
        refreshSoon();
        if (typeof id === "string" && (loaded.value || items.value.length)) void fetchOne(id);
        else if (typeof id === "string") ping(quietHours.value);
      }),
      // Not forwarded by the realtime bridge yet (follow-up); harmless until then.
      realtime.on("notification.read", (frame) => {
        if (frame.all) onSync({ type: "read-all", at: new Date().toISOString() });
        else if (isIdList(frame.notification_ids))
          onSync({ type: "read", ids: frame.notification_ids, at: new Date().toISOString() });
      }),
      realtime.on("notification.deleted", (frame) => {
        if (isIdList(frame.notification_ids)) onSync({ type: "deleted", ids: frame.notification_ids });
      }),
      // Anything pushed while the socket was down is only recoverable over REST.
      realtime.on("_reconnected", () => {
        void refresh();
        if (loaded.value) void refreshHead();
      }),
    );
    if (typeof BroadcastChannel !== "undefined") {
      channel = new BroadcastChannel(CHANNEL);
      channel.onmessage = (event: MessageEvent<unknown>) => {
        const message = parseSync(event.data);
        if (message) onSync(message);
      };
    }
    // The service worker hands a push to a focused window instead of the OS (sw.js).
    navigator.serviceWorker?.addEventListener("message", onWorkerMessage);
    document.addEventListener("visibilitychange", onVisible);
    void loadQuietHours();
  }

  return {
    unread,
    items,
    loaded,
    loading,
    error,
    hasMore,
    loadingMore,
    quietHours,
    busy,
    hasUnreadLoaded,
    filter,
    filtering,
    filtered,
    filteredHasMore,
    filteredLoading,
    filteredError,
    filteredLoadingMore,
    setFilter,
    loadFiltered,
    loadMoreFiltered,
    refresh,
    load,
    ensureLoaded,
    loadMore,
    upsert,
    fetchOne,
    markRead,
    markAllRead,
    remove,
    resolve,
    withBusy,
    onSync,
    bind,
  };
});
