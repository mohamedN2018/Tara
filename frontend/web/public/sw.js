// Tara service worker: offline shell and Web Push. Plain JS: it is served as is.
// API calls, sockets and signed media URLs always go to the network.

const VERSION = "v2";
const SHELL_CACHE = `tara-shell-${VERSION}`;
const ASSET_CACHE = `tara-assets-${VERSION}`;
const PREFS_CACHE = "tara-prefs"; // written by the app: src/i18n/index.ts
const MAX_ASSETS = 300;
const SHELL_FILES = [
  "/index.html",
  "/manifest.webmanifest",
  "/theme-init.js",
  "/icons/tara-mark.svg",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];
const NEVER_CACHED = ["/api/", "/ws/", "/tara-media/", "/__s3/", "/sw.js"];

// Every hashed bundle of this build (written by vite.config.ts), so the first
// install already works offline on any route.
async function buildAssets() {
  const response = await fetch("/precache.json", { cache: "no-store" });
  return response.ok ? response.json() : [];
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const shell = await caches.open(SHELL_CACHE);
      await shell.addAll(SHELL_FILES);
      const assets = await caches.open(ASSET_CACHE);
      await assets.addAll(await buildAssets());
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keep = [SHELL_CACHE, ASSET_CACHE, PREFS_CACHE];
      const names = await caches.keys();
      await Promise.all(names.filter((n) => !keep.includes(n)).map((n) => caches.delete(n)));
      await self.clients.claim();
    })(),
  );
});

async function trim(cache) {
  const keys = await cache.keys();
  await Promise.all(keys.slice(0, Math.max(0, keys.length - MAX_ASSETS)).map((k) => cache.delete(k)));
}

async function navigation(request) {
  const shell = await caches.open(SHELL_CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) await shell.put("/index.html", response.clone());
    return response;
  } catch {
    return (await shell.match("/index.html")) ?? Response.error();
  }
}

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok) {
    await cache.put(request, response.clone());
    await trim(cache);
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (NEVER_CACHED.some((prefix) => url.pathname.startsWith(prefix))) return;

  if (request.mode === "navigate") event.respondWith(navigation(request));
  else if (url.pathname.startsWith("/assets/")) event.respondWith(cacheFirst(request, ASSET_CACHE));
  else if (SHELL_FILES.includes(url.pathname)) event.respondWith(cacheFirst(request, SHELL_CACHE));
});

// ---- Web Push ----------------------------------------------------------------

const TEXT = {
  ar: {
    title: "تارا",
    fallback: "لديك إشعار جديد",
    "post.reaction": "تفاعل أحدهم مع منشورك",
    "post.comment": "علّق أحدهم على منشورك",
    "post.share": "شارك أحدهم منشورك",
    "comment.reply": "ردّ أحدهم على تعليقك",
    mention: "أشار إليك أحدهم",
    "friend.request": "لديك طلب صداقة جديد",
    "friend.accepted": "تم قبول طلب صداقتك",
    follow: "لديك متابع جديد",
    message: "لديك رسالة جديدة",
    "listing.status": "تغيّرت حالة إعلانك",
  },
  en: {
    title: "Tara",
    fallback: "You have a new notification",
    "post.reaction": "Someone reacted to your post",
    "post.comment": "Someone commented on your post",
    "post.share": "Someone shared your post",
    "comment.reply": "Someone replied to your comment",
    mention: "Someone mentioned you",
    "friend.request": "You have a new friend request",
    "friend.accepted": "Your friend request was accepted",
    follow: "You have a new follower",
    message: "You have a new message",
    "listing.status": "Your listing's status changed",
  },
};

// The app's language; the browser's if the app never said.
async function language() {
  try {
    const saved = await (await caches.open(PREFS_CACHE)).match("/__locale");
    if (saved) return (await saved.text()) === "en" ? "en" : "ar";
  } catch {
    // Fall through.
  }
  return self.navigator.language?.startsWith("ar") ? "ar" : "en";
}

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data?.json() ?? {};
  } catch {
    // Show the generic text.
  }
  event.waitUntil(
    (async () => {
      const text = TEXT[await language()];
      const body = data.kind === "message" && data.body ? data.body : (text[data.kind] ?? text.fallback);
      await self.registration.showNotification(text.title, {
        body,
        icon: "/icons/icon-192.png",
        badge: "/icons/badge-96.png",
        tag: data.tag,
        data: { url: data.url ?? "/notifications" },
      });
    })(),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url ?? "/notifications", self.location.origin);
  // Only ever open this app.
  const path = target.origin === self.location.origin ? target.pathname : "/notifications";
  event.waitUntil(
    (async () => {
      const open = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of open) {
        if ("navigate" in client) {
          await client.focus();
          return client.navigate(path);
        }
      }
      return self.clients.openWindow(path);
    })(),
  );
});
