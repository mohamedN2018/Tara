// Service worker registration, the install prompt, and the browser's push subscription.
import { ref } from "vue";

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
