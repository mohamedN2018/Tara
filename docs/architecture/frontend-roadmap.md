# Tara Frontend — Status and Roadmap

What the web app (`frontend/web`) does today against the live APIs, what is
deliberately left out, and what remains. Real API data only, Arabic RTL by
default with English LTR (`ar.ts` and `en.ts` are kept in parity by a unit test).

Last updated: 2026-11-03.

## ✅ Built and verified in a browser on the live stack

**Account** — register, email verification, login, forgot/reset password,
active sessions with revoke, settings (theme, language, quiet hours, per-kind
in-app notification toggles).

**Feed and posts** — home feed with live `feed.item.added` (one summary event
per fan-out), composer with audience, photos, polls and `@mention`
autocomplete; edit, delete, report; reactions; comments paged with "view more",
replies with notifications to the parent comment's author; saved posts and
listings paged. Text renders clickable `#hashtags` (search shows only posts the
viewer may see), `@mentions` (profile links, and a notification to mentioned
people who can open the post) and links. Link previews are built by the server
(text only). Sharing creates a real post with the original embedded as a card;
a share never reaches further than the original, and readers outside the
original's audience see "This post isn't available".

**Profiles and Pages** — profile overview, intro/work/education/links, photos,
friends, edit modal with avatar/cover and per-field privacy (Everyone /
Friends / Only me). Pages: browse and search, "My pages", create, view, edit
(owners/admins also publish or hide as draft), team list with roles, add by
handle, change role, remove, leave.

**Chat** — DMs and groups (create from friends, rename, add/remove members,
make/remove admin, leave; members are updated live), inbox ordered by latest
activity, image and voice messages (record with MediaRecorder, upload, play),
replies, reactions (live via `chat.message.reacted`), pin/unpin with a pinned
bar, mute for 1h/8h/1 week (no notification or toast while muted), typing,
presence, and "Seen" that survives a reload (per-member read state).

**Social graph** — follow, friends (requests/sent/all, mutual), followers /
following / blocked lists with unblock.

**Marketplace** — browse/mine/saved, categories, create and publish, detail,
contact seller, seller transitions.

**Notifications** — list with actor avatars and paging, live toasts, Web Push
(Settings → Browser notifications) when VAPID keys are configured.

**Ads** — advertiser dashboard (campaigns, pause/resume, ad sets, creatives,
spend, impressions, clicks, CTR per campaign and creative), ad review queue for
`ad_reviewer`/`admin`, sponsored card in the feed that reports impression and
click with the serve token it was given.

**Admin** — service health, moderation queue (sorted by report count), role
management (grant/revoke `admin`, `moderator`, `ad_reviewer`, `analyst` by
email; Identity holds the roles), feature flags (add, toggle, rollout %).

**PWA** — manifest and icons (installable; "Install" in Settings when the
browser offers it), service worker that caches the whole build so the app
starts offline, and push display in the app's language. The service worker runs
only in production builds (`npm run build`), not in `vite` dev.

## 🧪 How it is tested

- Unit (Vitest): token refresh, sockets, chat ordering/receipts/reactions,
  rich text tokenizing, feed hydration and the sponsored slot, VAPID key
  decoding, i18n parity.
- E2E (Playwright, live stack): `auth`, `names`, `posts`, `profile`, `chat`,
  `chat-features`, `lists`, `social`, `growth`, and `pwa`. `pwa.spec.ts` needs a
  production preview on :4173 and skips without one. `growth.spec.ts` runs
  `docker exec tara-identity-1 python manage.py create_admin` to make an admin.

## ⚠️ Known limits

- Web Push: automated Chromium refuses real push subscriptions, so the e2e
  test stubs `PushManager.subscribe` (real P-256 keys, an FCM URL) and checks
  the server's real send to FCM and its handling of the answer. Delivery to a
  real browser has not been seen end to end.
- Offline: the shell and its code load from cache and the app reports it is
  offline, but no data is cached, so signed-in pages stay empty until the
  connection returns.
- Link previews have no image on purpose: loading a remote image would give
  every reader's IP address to whoever wrote the post.
- Group members can be added from friends in the UI; the API accepts any
  account that hasn't blocked the admin (as DMs do).
- Push has one on/off switch per browser. The backend already honours a
  per-kind `push` channel in preferences, but there is no UI for it.
- Ads: budgets are tracked numbers, with no payment. Ad set `targeting` is
  stored but not evaluated. Creatives have no image upload in the dashboard.
- The `analyst` role reaches the token, but nothing uses it yet.
- Role changes reach the token on the next refresh (access tokens live for
  minutes); an existing access token keeps its old roles until it expires.

## 🛣️ Next

1. Pages as authors: post as a page (`author_type=page`), page avatar/cover
   upload, follow a page.
2. Per-kind push toggles in Settings; quiet-hours UI already exists.
3. Offline data: cache the last feed page and conversations for reading.
4. Ads: creative images, targeting, and an analyst view of campaign stats.
5. Split `MessagesView` and `PostCard` further (both grew with this work), and
   an accessibility pass on the new dialogs and menus.

## 🧩 Cross-cutting (quality & infra)

- **Production media serving**: the dev `/__s3` Vite proxy is dev-only;
  production goes through the web container's `/tara-media/` route.
- **Celery queue isolation**: per-service default queues are in place
  (`<service>.tasks`); web push runs on the notification relay worker.
- Deploy needs `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` and `VAPID_SUBJECT` for
  the notification service, and `ADS_AUTO_APPROVE` now defaults to off.
