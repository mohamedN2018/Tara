# Tara Frontend — Development Roadmap

Status snapshot + a prioritized plan for closing the gap between what the
backend already exposes and what the web app surfaces. Constraint: **frontend
only, no backend changes, real API data only, full Arabic RTL.**

## ✅ Already built & verified
Auth (login/register) · Home feed (real-time `feed.item.added`, composer with
audience + media) · Profile (two-column overview, intro/work/education/links,
photos, friends, completion, edit modal with avatar/cover upload) · Follow &
Friends (real state, requests/sent/all, mutual, counts) · Chat (DMs, image
messages, replies, "Seen" receipts, typing, presence, date dividers) ·
Marketplace (browse/mine/saved, categories, create+publish, detail, contact,
seller transitions) · Notifications (actor avatars, pagination, live toasts) ·
Search (typed tabs, people/posts/listings) · Saved (posts + listings) ·
Settings · Admin (health + moderation queue) · Post detail page · Navbar (apps
grid, create menu, live search) · Name directory · Media pipeline (eager
processing + dev storage proxy).

## ❌ Gaps — backend exists, frontend does not surface it

### Auth / account (identity service)
- Email verification page (`auth/verify-email/`) — register returns `pending`.
- Forgot / reset password (`auth/password/forgot|reset/`).
- Active sessions list + revoke (`auth/sessions/`).

### Profile (profile service)
- **Pages** (business/brand profiles): `pages/`, `pages/<handle>/`, members,
  roles — entirely missing.
- Field-level privacy (`profile/me/privacy/`) — per-field visibility control.

### Chat (chat service)
- **Message reactions** (`messages/<id>/reactions/` + `chat.message.reacted`).
- **Voice messages** (`conversations/<id>/voice-messages/`) — record/send/play.
- **Mute / Pin** conversation (`.../mute`, `.../pin`).
- **Group conversations** (group create) — only DMs surfaced today.

### Posts (post service)
- Edit post (`PostEditSerializer` / PATCH) — only delete exists in UI.
- Report post (endpoint exists; no UI action on PostCard).
- Link previews (`link_preview`), shared-post rendering (`shared_post_id`),
  polls (`type=poll` placeholder), hashtags (tags are extracted server-side),
  @mentions.

### Graph
- Followers / Following / Blocked **list views** (counts shown, lists not).

### Notifications
- Preferences page (`notifications/preferences/`).
- Web Push registration (`devices/push-token/`).

### Admin / moderation / ads
- Admin: feature flags (`admin/feature-flags/`), role management (`admin/roles/`).
- Moderation: file a report UI (`moderation/reports/file/`).
- Ads: advertiser dashboard (`ads/campaigns/`, ad-sets, creatives review).

## 🛣️ Roadmap (recommended order)

### Phase 1 — Finish the core (high value, low effort)
1. Auth completeness: email-verify page, forgot/reset password, sessions list.
2. Post ⋯ menu: **edit** + **report** (alongside existing delete).
3. Chat: **message reactions** (live) + **mute/pin** conversation.
4. Relationship list views: Followers / Following / Blocked (+ unblock).
5. Notification **preferences** page.

### Phase 2 — New surfaces (medium effort)
6. **Pages** (business profiles): browse, view, create, manage members/roles.
7. **Group chats**: create group + group conversation UI.
8. **Voice messages**: record (MediaRecorder) → upload → send → playback.
9. **Field privacy** controls inside the edit-profile modal.
10. **Hashtags & mentions**: clickable `#tag` → search, `@mention` autocomplete.

### Phase 3 — Growth / advanced (higher effort)
11. **Web Push + PWA**: service worker, push-token registration, installable,
    offline shell.
12. Ads **advertiser dashboard** (campaigns / ad-sets / creatives).
13. Admin: feature flags + role management.
14. Posts: link previews, shared-post cards, polls.

## 🧩 Cross-cutting (quality & infra)
- **Frontend tests**: component/unit (Vitest) + a few E2E happy paths.
- **Production media serving**: the dev `/__s3` Vite proxy is dev-only; prod
  needs the gateway to route storage (or a public S3 endpoint).
- **Celery queue isolation** (infra, with sign-off): per-service default queues
  instead of one shared `celery` queue — the proper fix behind the media
  `CELERY_TASK_ALWAYS_EAGER` workaround; affects any service-specific task.
- Accessibility audit (keyboard, ARIA, focus, contrast).
- Consistency pass on empty/error/loading states + i18n completeness.
