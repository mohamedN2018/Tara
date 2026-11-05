// Needs a production build, since the service worker registers only there:
//   VITE_STORAGE_PROXY=true npm run build && npx vite preview --port 4173 --host 127.0.0.1
// (the flag routes presigned uploads through the local storage proxy, as in dev)
import { execSync } from "node:child_process";

import { expect, request, test } from "@playwright/test";

import { API, apiAs, pageAs, sharedAccounts } from "./helpers";

const PREVIEW = process.env.E2E_PREVIEW_URL ?? "http://127.0.0.1:4173";

test.beforeAll(async () => {
  const api = await request.newContext();
  const up = await api.get(PREVIEW).then((r) => r.ok(), () => false);
  await api.dispose();
  test.skip(!up, `no production preview at ${PREVIEW}`);
});

test("the build is installable and its shell works offline", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  await page.goto(`${PREVIEW}/home`);

  const href = await page.locator('link[rel="manifest"]').getAttribute("href");
  const manifest = await (await page.request.get(`${PREVIEW}${href}`)).json();
  expect(manifest.display).toBe("standalone");
  expect(manifest.icons.map((i: { sizes: string }) => i.sizes)).toEqual(expect.arrayContaining(["192x192", "512x512"]));
  for (const icon of manifest.icons) {
    expect((await page.request.get(`${PREVIEW}${icon.src}`)).status()).toBe(200);
  }

  await page.evaluate(() => navigator.serviceWorker.ready);
  await expect
    .poll(() => page.evaluate(() => !!navigator.serviceWorker.controller))
    .toBe(true)
    .catch(async () => page.reload());

  await page.reload();
  await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true);

  await page.context().setOffline(true);
  // Any route loads from the cache: the app itself starts and says it is offline.
  await page.goto(`${PREVIEW}/settings`);
  await expect(page.getByText("أنت غير متصل. جارٍ إعادة الاتصال…")).toBeVisible();
  const cached = await page.evaluate(async () => (await caches.keys()).sort());
  expect(cached).toEqual(["tara-assets-v3", "tara-prefs", "tara-shell-v3"]);
  await page.context().setOffline(false);
});

test("a delivered push shows a localised notification that opens the app", async ({ browser }) => {
  const context = await browser.newContext();
  await context.grantPermissions(["notifications"], { origin: PREVIEW });
  const page = await context.newPage();
  await page.goto(`${PREVIEW}/`);
  await page.evaluate(() => navigator.serviceWorker.ready);

  // Deliver a push the way a push service would, through the browser itself.
  const cdp = await context.newCDPSession(page);
  await cdp.send("ServiceWorker.enable");
  // The registration whose worker is activated and running, not one mid-update.
  const registrationId = await new Promise<string>((resolve) => {
    cdp.on("ServiceWorker.workerVersionUpdated", ({ versions }) => {
      const live = versions.find(
        (v: { scriptURL: string; status: string; runningStatus: string }) =>
          v.scriptURL.startsWith(PREVIEW) && v.status === "activated" && v.runningStatus === "running",
      );
      if (live) resolve(live.registrationId);
    });
  });
  const payload = { kind: "follow", url: "/notifications", tag: "probe-follow", body: "started following you" };
  const deliver = (data: object) =>
    cdp.send("ServiceWorker.deliverPushMessage", { origin: PREVIEW, registrationId, data: JSON.stringify(data) });

  // A focused Tara window shows the push live, so the worker tells that window
  // instead of raising an OS notification on top of it.
  await page.evaluate(() => {
    const w = window as unknown as { __pushes: unknown[] };
    w.__pushes = [];
    navigator.serviceWorker.addEventListener("message", (e) => w.__pushes.push(e.data));
  });
  await deliver({ ...payload, notification_id: "n-focused" });
  await expect
    .poll(() => page.evaluate(() => (window as unknown as { __pushes: unknown[] }).__pushes))
    .toEqual([{ type: "tara.push", kind: "follow", notification_id: "n-focused" }]);
  expect(await page.evaluate(async () => (await (await navigator.serviceWorker.ready).getNotifications()).length)).toBe(0);

  // With no Tara window open, the push becomes a localised OS notification.
  await page.goto("about:blank");
  await deliver(payload);
  await page.goto(`${PREVIEW}/`);

  await expect
    .poll(() =>
      page.evaluate(async () => {
        const registration = await navigator.serviceWorker.ready;
        return (await registration.getNotifications({ tag: "probe-follow" })).map((n) => [n.title, n.body]);
      }),
    )
    .toEqual([["تارا", "لديك متابع جديد"]]);

  const urls = await page.evaluate(async () => {
    const shell = await caches.open("tara-shell-v3");
    const assets = await caches.open("tara-assets-v3");
    return [...(await shell.keys()), ...(await assets.keys())].map((r) => new URL(r.url).pathname);
  });
  expect(urls.some((u) => u.startsWith("/api/") || u.startsWith("/tara-media/"))).toBe(false);
});

// Automated Chromium refuses real push subscriptions ("Registration failed -
// permission denied"), so PushManager.subscribe is replaced by one that returns
// a well-formed subscription with real P-256 keys for a push-service URL. Every
// other step is real, including the server encrypting and sending to that URL.
test("settings subscribe this browser, and the server delivers to it", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const page = await pageAs(browser, a, PREVIEW);
  await page.context().grantPermissions(["notifications"], { origin: PREVIEW });
  const endpoint = `https://fcm.googleapis.com/fcm/send/e2e-${Date.now()}`;
  await page.addInitScript((url) => {
    const b64 = (buf: ArrayBuffer) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    let current: unknown = null;
    PushManager.prototype.getSubscription = async () => current as PushSubscription;
    PushManager.prototype.subscribe = async () => {
      const pair = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
      const p256dh = b64(await crypto.subtle.exportKey("raw", pair.publicKey));
      const auth = b64(crypto.getRandomValues(new Uint8Array(16)).buffer);
      current = {
        endpoint: url,
        toJSON: () => ({ endpoint: url, keys: { p256dh, auth } }),
        unsubscribe: async () => {
          current = null;
          return true;
        },
      };
      return current as PushSubscription;
    };
  }, endpoint);
  await page.goto(`${PREVIEW}/settings/notifications`);
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload();

  const section = page.getByTestId("push-settings");
  const registered = page.waitForResponse((r) => r.url().includes("/devices/push-token/"));
  await section.getByRole("button", { name: "تفعيل" }).click();
  expect((await registered).status()).toBe(201);
  await expect(section).toContainText("مفعّلة في هذا المتصفح.");

  // A real notification goes out through pywebpush to that URL. FCM answers for
  // an unknown registration, and the server records the outcome.
  const tokens = () =>
    execSync(
      `docker exec tara-notification-1 python manage.py shell -c "from notifications.models import PushDeviceToken as T, NotificationDeliveryLog as L; print(T.objects.filter(account_id='${a.id}', platform='web').count(), list(L.objects.filter(notification__recipient_id='${a.id}', channel='push').order_by('-created_at').values_list('status', flat=True)[:1]))"`,
    ).toString().trim().split(/\r?\n/).pop();
  expect(tokens()).toMatch(/^1 /);
  // Other tests flip Alice's follow notifications; start from the defaults (on).
  await (await apiAs(a)).patch(`${API}/notifications/preferences/`, { data: { prefs: {} } });
  const bob = await apiAs(b);
  await bob.delete(`${API}/follows/${a.id}/`);
  await bob.post(`${API}/follows/${a.id}/`);
  // FCM rejects the made-up registration: the server either drops it (404/410)
  // or logs the failed attempt. Both prove a real send happened.
  await expect.poll(tokens, { timeout: 30_000 }).toMatch(/^0 |'failed'|'expired'/);

  await page.reload();
  await expect(section.getByRole("button", { name: "تفعيل" })).toBeVisible();
});
