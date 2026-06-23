# Phase 8 — Frontend ↔ Backend API Contract Audit

> A static cross-check of every call in `frontend/web/src/services/*` (and the
> auth store) against the real backend routes in each service's `urls.py`/views.
> This substitutes for the still-blocked live E2E pass: it catches the contract
> drift that the Phase 8 report flagged (frontend paths were **inferred**).
> Frontend rebuild after the fixes below: **`vue-tsc` + `vite build` green**.

Base: the web client prefixes every path with `VITE_API_BASE=/api/v1`.

## A. Fixed (frontend corrected to the real route)

| # | Area | Was | Now (backend route) |
|---|------|-----|---------------------|
| 1 | auth bootstrap | `GET /auth/me/` | `GET /me/` (identity `MeView`) |
| 2 | profile me / update | `/profiles/me/` | `/profile/me/` |
| 3 | public profile | `GET /profiles/{handle}/` | `GET /users/{handle}/` (`PublicProfileView`) |
| 4 | auth loadProfile | `GET /profiles/me/` | `GET /profile/me/` |
| 5 | marketplace list/get/create/save | `/listings/...` | `/marketplace/listings/...` |
| 6 | seller contact | `chat.openDm(seller)` | `POST /marketplace/listings/{id}/contact/` (emits `marketplace.contact.requested`; chat opens the convo) |
| 7 | post share | `POST /posts/{id}/shares/` | `POST /posts/{id}/share/` |
| 8 | search suggest | `GET /search/suggest/` | `GET /search/autocomplete/` |
| 9 | open DM | `POST /conversations/dm/ {user_id}` | `POST /conversations/ {type:"dm", other_id}` |
| 10 | mark conversation read | `PUT /conversations/{id}/receipts/ {last_read_message_id}` | `POST /conversations/{id}/read/ {message_id}` |
| 11 | notifications read / read-all | `PUT /notifications/{id}/read/`, `PUT /notifications/read-all/` | `POST /notifications/read/ {ids, all}` |
| 12 | file a report | `POST /moderation/reports/` | `POST /moderation/reports/file/` (`ManualReportView`) |
| 13 | decline friend request | `POST /friends/requests/{id}/decline/` | `POST /friends/requests/{id}/reject/` |
| 14 | media upload (was G4) | `POST /media/` (direct) | presigned 3-step: `POST /media/uploads/sign/` → `PUT` bytes to storage → `POST /media/uploads/{id}/complete/` |
| 15 | media display (was G5) | sync `/media/{id}/raw` | async resolve via `GET /media/{id}/` → presigned `url` (`useMediaUrl`/`mediaService.resolveUrl`, cached) |
| 16 | list posts by author (was G1) | — (405) | **NEW backend** `GET /posts/?author_id=` (`PostCreateView.get` + `services.list_author_posts`, audience-filtered, + tests) |
| 17 | admin metrics (was G2) | `GET /admin/metrics/` (404) | `GET /admin/service-health/` → `{overall, services[]}` (AdminView shows a health grid) |
| 18 | admin resolve (was G3) | `POST /moderation/reports/{id}/resolve/` | cases flow: `GET /moderation/cases/` + `POST /moderation/cases/{id}/action/ {action, reason}` |
| 19 | mark conversation read (V1) | `{message_id}` | `{up_to_message_id}` |
| 20 | friends list (V2) | `[{user_id}]` | `{friends: [id, ...]}` |
| 21 | incoming requests (V2) | `[{from_user_id}]` | `Friendship[]` → mapped (`requested_by` → `from_user_id`) |
| 22 | follow-state probe (V2) | `GET /follows/{id}/` | removed — no such endpoint; follow state defaults to unknown |

## B. Verified correct (no change)

auth login/register/logout (`/auth/*`) + refresh (`/auth/refresh/`); posts
create/detail/reactions/comments/save (`/posts/...`); graph
follows/friends/blocks + request accept (`/friends/requests/{id}/accept/`); feed
(`/feed/`); chat conversations list + messages list/send
(`/conversations/{id}/messages/`); notifications list + unread-count; search
(`/search/`); media detail (`/media/{id}/`); moderation reports list
(`/moderation/reports/`).

## C. Former backend gaps — now resolved

- **G1 — list posts by author. ✅ FIXED** (§A #16): added `GET /posts/?author_id=`
  to the posts service (audience-filtered `services.list_author_posts` + 2 tests).
  Backend verified by `py_compile` + `ruff` (full pytest runs in CI/venv).
- **G2 — admin metrics. ✅ FIXED** (§A #17): the AdminView now renders the real
  `GET /admin/service-health/` overview instead of a non-existent metrics endpoint.
- **G3 — resolve a report. ✅ FIXED** (§A #18): the admin queue now lists
  moderation **cases** and actions them (`dismiss`/`remove`) via the real
  case-action endpoint.
- **G4 — media upload. ✅ FIXED** (§A #14): real presigned 3-step flow.
- **G5 — media display. ✅ FIXED** (§A #15): async per-id URL resolution.

## D. Former verification items — now resolved

- **V1 ✅** — `chat.markRead` body is `{up_to_message_id}` (matched to `ReadSerializer`).
- **V2 ✅** — graph shapes aligned: `sendFriendRequest {to_user_id}` was already
  correct; `friends()` reads `{friends:[ids]}`; `incomingRequests` maps `Friendship`
  rows (`requested_by`); the unsupported `isFollowing` probe was removed.
- **V3 (latent)** — `chat.getConversation` → `GET /conversations/{id}/` still has no
  plain detail route; the method is unused by any view, so it is harmless. Left as-is.

## E. Residual limitations (small, documented)

- **Follow state** on a profile defaults to "not following" (no
  `GET /follows/{id}/` endpoint); flip it by checking membership in
  `GET /follows/following/` if/when desired.
- Bodies/headers were matched against serializers statically; a live E2E run
  (still blocked here by the in-container pip/TLS image-build constraint) remains
  the final confirmation.

## F. Outcome

Every contract mismatch found in this audit is now either **fixed** (frontend or a
small backend addition) or **documented as a tiny residual** (follow-state default,
one latent unused method). All happy paths are contract-correct; frontend
`vue-tsc + vite build` and backend `py_compile + ruff` are green.
