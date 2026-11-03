// Service worker registration, the install prompt, and the browser's push subscription.
import { ref } from "vue";

import { notificationService } from "@/services/notification";

interface InstallPromptEvent extends Event {
  prompt(): Promise<void>;
}

let installEvent: InstallPromptEvent | null = null;
export const canInstall = ref(false);

export function setUpPwa() {
  // Vite's dev server has no build output for it to cache, and would serve stale code.
  if (import.meta.env.PROD && "serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // The app works the same without it.
      });
    });
  }
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installEvent = event as InstallPromptEvent;
    canInstall.value = true;
  });
  window.addEventListener("appinstalled", () => {
    installEvent = null;
    canInstall.value = false;
  });
}

export async function installApp() {
  await installEvent?.prompt();
  installEvent = null;
  canInstall.value = false;
}

export function pushSupported(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

export async function pushRegistration(): Promise<ServiceWorkerRegistration | null> {
  if (!pushSupported()) return null;
  return (await navigator.serviceWorker.getRegistration()) ?? null;
}

/** The VAPID public key in the form PushManager wants. */
export function vapidKeyBytes(key: string): Uint8Array {
  const base64 = (key + "=".repeat((4 - (key.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

export interface WebPushSubscription {
  endpoint: string;
  keys: { p256dh: string; auth: string };
}

export function subscriptionJson(subscription: PushSubscription): WebPushSubscription {
  const { endpoint, keys } = subscription.toJSON();
  return { endpoint: endpoint ?? "", keys: { p256dh: keys?.p256dh ?? "", auth: keys?.auth ?? "" } };
}

// ---- Push subscription lifecycle ---------------------------------------------------
//
// One browser subscription can only ever belong to one account. Lessons from
// QTech's mobile/push.js, plus what a shared browser needs:
//  * Permission is asked for only from a control the user pressed (enablePush).
//  * Every logout path unsubscribes the browser LOCALLY first (releasePush). A
//    server call alone fails once the session has expired, and the old account's
//    pushes would keep arriving for whoever signs in next.
//  * On login and boot (resumePush) a subscription owned by another account is
//    dropped; this account's own is re-bound to the server (browsers rotate
//    subscriptions silently); and an account that had push on in this browser
//    gets it back without a prompt, since permission is already granted.

const OWNER_KEY = "tara.push.owner"; // account the current subscription belongs to
const WANTED_KEY = "tara.push.wanted"; // accounts that turned push on in this browser
const LOGOUT_SERVER_WAIT_MS = 1500;

function readOwner(): string | null {
  try {
    return localStorage.getItem(OWNER_KEY);
  } catch {
    return null;
  }
}
function writeOwner(accountId: string | null) {
  try {
    if (accountId) localStorage.setItem(OWNER_KEY, accountId);
    else localStorage.removeItem(OWNER_KEY);
  } catch {
    // Storage unavailable: resumePush then treats the subscription as foreign (safe side).
  }
}
function readWanted(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(WANTED_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}
function setWanted(accountId: string, wanted: boolean) {
  const next = readWanted().filter((id) => id !== accountId);
  if (wanted) next.push(accountId);
  try {
    localStorage.setItem(WANTED_KEY, JSON.stringify(next.slice(-10)));
  } catch {
    // Best effort.
  }
}

function permission(): NotificationPermission {
  try {
    return Notification.permission;
  } catch {
    return "default";
  }
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  try {
    const registration = await pushRegistration();
    return (await registration?.pushManager.getSubscription()) ?? null;
  } catch {
    return null;
  }
}

/** True when this browser is subscribed for `accountId` right now. */
export async function pushActiveFor(accountId: string | null | undefined): Promise<boolean> {
  if (!accountId) return false;
  return !!(await currentSubscription()) && readOwner() === accountId;
}

async function subscribeAndRegister(accountId: string, publicKey: string): Promise<boolean> {
  const registration = await pushRegistration();
  if (!registration || !publicKey) return false;
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: vapidKeyBytes(publicKey),
  });
  try {
    await notificationService.registerWebPush(subscriptionJson(subscription));
  } catch (e) {
    await subscription.unsubscribe().catch(() => {}); // never claim one the server refused
    throw e;
  }
  writeOwner(accountId);
  return true;
}

export type EnableResult = "on" | "off" | "denied" | "unavailable";

/** Ask for permission and subscribe. Call only from a user gesture. */
export async function enablePush(accountId: string): Promise<EnableResult> {
  if (!pushSupported()) return "unavailable";
  const config = await notificationService.pushConfig();
  if (!config.enabled) return "unavailable";
  const granted = permission() === "granted" || (await Notification.requestPermission()) === "granted";
  if (!granted) return permission() === "denied" ? "denied" : "off";
  // A subscription left by another account must not be re-used for this one.
  const existing = await currentSubscription();
  if (existing && readOwner() !== accountId) await existing.unsubscribe().catch(() => false);
  if (!(await subscribeAndRegister(accountId, config.public_key))) return "unavailable";
  setWanted(accountId, true);
  return "on";
}

/** The user turned push off here: browser first, then the server (best effort). */
export async function disablePush(accountId: string): Promise<void> {
  setWanted(accountId, false);
  const subscription = await currentSubscription();
  writeOwner(null);
  if (!subscription) return;
  const endpoint = subscription.endpoint;
  await subscription.unsubscribe().catch(() => false);
  // The endpoint is already dead if this fails; the server drops it on the next 410.
  await notificationService.unregisterWebPush(endpoint).catch(() => {});
}

/** Message previews left in the OS tray must not be read by the next account. */
async function closeShownNotifications(): Promise<void> {
  try {
    const registration = await navigator.serviceWorker?.getRegistration();
    (await registration?.getNotifications())?.forEach((n) => n.close());
  } catch {
    // No worker, or the browser keeps no list: nothing to close.
  }
}

/**
 * Logout, on every path (button, expired session, another tab signing out).
 * Unsubscribes locally first, which works with no session at all, so the next
 * account on this browser never receives the previous account's pushes. The
 * account stays "wanted", so its push comes back on its next login here.
 * `remote` also tells the server, briefly, while the session is still valid.
 * `clearTray` closes the notifications already shown (message previews); a boot
 * with no session at all has no session ending here, and leaves them.
 */
export async function releasePush({
  remote = false,
  clearTray = true,
}: { remote?: boolean; clearTray?: boolean } = {}): Promise<void> {
  if (clearTray) await closeShownNotifications();
  const subscription = await currentSubscription();
  writeOwner(null);
  if (!subscription) return;
  const endpoint = subscription.endpoint;
  await subscription.unsubscribe().catch(() => false);
  if (!remote) return;
  await Promise.race([
    notificationService.unregisterWebPush(endpoint).catch(() => {}),
    new Promise((resolve) => window.setTimeout(resolve, LOGOUT_SERVER_WAIT_MS)),
  ]);
}

/**
 * Login and boot: make the subscription match the signed-in account. Never prompts.
 * Returns whether this browser ends up subscribed for `accountId`.
 */
export async function resumePush(accountId: string): Promise<boolean> {
  if (!pushSupported()) return false;
  try {
    let subscription = await currentSubscription();
    if (subscription && readOwner() !== accountId) {
      // Someone else's (or from before ownership was recorded): drop it.
      await subscription.unsubscribe().catch(() => false);
      writeOwner(null);
      subscription = null;
    }
    if (permission() !== "granted") return false;
    if (subscription) {
      // Re-bind: a browser can rotate or the server can have dropped the row.
      await notificationService.registerWebPush(subscriptionJson(subscription));
      return true;
    }
    if (!readWanted().includes(accountId)) return false;
    const config = await notificationService.pushConfig();
    return config.enabled ? await subscribeAndRegister(accountId, config.public_key) : false;
  } catch {
    return false;
  }
}
