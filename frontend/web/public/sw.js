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
//
// The payload (services/notification/notifications/push.py) carries ids, a
// count, the deep link and, for messages, the text unless previews are off.

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
    "listing.inquiry": "لديك استفسار جديد عن إعلانك",
    "page.follow": "لصفحتك متابع جديد",
    "ad.review": "تمت مراجعة إعلانك",
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
    "listing.inquiry": "Someone asked about your listing",
    "page.follow": "Your page has a new follower",
    "ad.review": "Your ad was reviewed",
  },
};

// Arabic counted nouns: 2 is dual, 3-10 plural, 11+ singular accusative.
function arCount(n, dual, plural, single) {
  if (n === 2) return dual;
  const lastTwo = n % 100;
  return lastTwo >= 3 && lastTwo <= 10 ? `${n} ${plural}` : `${n} ${single}`;
}

// Grouped rows: "{n}" is the number of people (Arabic: "{people}" / "{followers}").
const GROUPED = {
  ar: {
    "post.reaction": "تفاعل {people} مع منشورك",
    "post.comment": "علّق {people} على منشورك",
    "post.share": "شارك {people} منشورك",
    follow: "لديك {followers}",
  },
  en: {
    "post.reaction": "{n} people reacted to your post",
    "post.comment": "{n} people commented on your post",
    "post.share": "{n} people shared your post",
    follow: "You have {n} new followers",
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

function bodyFor(data, lang) {
  const text = TEXT[lang];
  if (data.kind === "message" && data.body) return data.body;
  const grouped = GROUPED[lang][data.kind];
  const n = Number(data.count);
  if (grouped && n > 1) {
    return grouped
      .replace("{n}", String(n))
      .replace("{people}", arCount(n, "شخصان", "أشخاص", "شخصًا"))
      .replace("{followers}", arCount(n, "متابعان جديدان", "متابعين جدد", "متابعًا جديدًا"));
  }
  return text[data.kind] ?? text.fallback;
}

// A same-origin path with its query and hash ("/posts/1?comment=2"), or the list.
function safePath(url) {
  try {
    const target = new URL(url ?? "/notifications", self.location.origin);
    if (target.origin !== self.location.origin) return "/notifications";
    return target.pathname + target.search + target.hash;
  } catch {
    return "/notifications";
  }
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
      // A focused Tara window already shows it live (list, badge, toast): tell
      // that window instead of raising an OS notification on top of it.
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      const focused = windows.find((client) => client.focused && client.visibilityState === "visible");
      if (focused) {
        focused.postMessage({ type: "tara.push", kind: data.kind, notification_id: data.notification_id });
        return;
      }
      const lang = await language();
      await self.registration.showNotification(TEXT[lang].title, {
        body: bodyFor(data, lang),
        icon: "/icons/icon-192.png",
        badge: "/icons/badge-96.png",
        tag: data.tag,
        renotify: Boolean(data.tag) && data.kind === "message",
        lang,
        dir: lang === "ar" ? "rtl" : "ltr",
        data: { url: safePath(data.url) },
      });
    })(),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  // Only ever open this app, and keep "?comment=" and "#..." so the link lands exactly.
  const path = safePath(event.notification.data?.url);
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
