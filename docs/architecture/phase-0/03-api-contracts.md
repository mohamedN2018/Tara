# 03 — API Contracts

Conventions that **every** service follows so the web app, future iOS, and
future Android clients share one predictable contract.

## 1. Versioning & base path

- All REST endpoints live under `/api/v1/`. Breaking changes → `/api/v2/`.
- Versions run in parallel during deprecation windows (min 6 months).
- OpenAPI 3.1 spec auto-generated per service via **drf-spectacular**, merged
  into one published spec at the gateway: `/api/v1/openapi.json` + Swagger UI.
- A `Tara-Api-Version` response header echoes the resolved version.

## 2. Authentication

- **Access token:** JWT, ~15 min TTL, `Authorization: Bearer <token>`.
- **Refresh token:** opaque/rotating. Web: `httpOnly; Secure; SameSite=Strict`
  cookie. Mobile: returned in body, stored in secure keystore. Rotation with
  **reuse detection** (a replayed refresh token revokes the whole family).
- `POST /auth/refresh/` issues a new access (+ rotated refresh).
- Services verify tokens **locally** against Identity's JWKS (cached); they do
  not call Identity per request.

## 3. Request conventions

| Concern | Rule |
|--------|------|
| Content type | `application/json` (uploads use signed URLs / multipart to Media only) |
| Idempotency | Unsafe writes (POST creating resources, payments-like) accept `Idempotency-Key: <uuid>`. Same key + same body within TTL → same response, executed once. |
| Correlation | Clients may send `X-Request-Id`; gateway generates one if absent and propagates it through events & logs. |
| Locale | `Accept-Language: ar` / `en` drives localized strings; content is not translated. |
| Conditional | `ETag` / `If-None-Match` on cacheable GETs. |

## 4. Pagination

- **Cursor pagination** is the default for feeds, messages, comments,
  notifications, listings, search — anything timeline-like or high-volume.

```jsonc
// GET /api/v1/feed/?limit=20
{
  "data": [ /* items */ ],
  "page": {
    "next_cursor": "eyJjI...",   // opaque; null when no more
    "prev_cursor": null,
    "has_more": true
  }
}
```

- Cursors are **opaque base64** encoding `(sort_key, tiebreaker_id)` — never raw
  offsets. Stable under inserts. `limit` capped (default 20, max 100).
- Small bounded collections (e.g. a user's links) may use simple lists.

## 5. Standard envelopes

**Success (single):**
```json
{ "data": { "id": "...", "type": "post", "attributes": { } } }
```

**Success (collection):** as in §4.

**Error (uniform across all services):**
```json
{
  "error": {
    "code": "validation_error",
    "message": "Human-readable, localized summary.",
    "request_id": "req_01H...",
    "details": [
      { "field": "title", "code": "required", "message": "Title is required." }
    ]
  }
}
```

- `code` is a **stable machine string** (clients switch on it), never a raw
  message. Canonical codes: `validation_error`, `unauthenticated`,
  `permission_denied`, `not_found`, `conflict`, `rate_limited`,
  `idempotency_conflict`, `dependency_unavailable`, `internal_error`.
- HTTP status maps: 400/401/403/404/409/422/429/503/500 accordingly.
- `dependency_unavailable` (503) is returned for **degradation** states and
  carries `Retry-After`.

## 6. Filtering, sorting, search

- Filtering via explicit query params (`?status=active&category=...`),
  validated by serializers. No arbitrary ORM passthrough.
- Sorting via `?sort=-created_at` (whitelist per endpoint).
- Free-text search via the Search service (`/search`), not ad-hoc `icontains`.

## 7. Rate limiting

- Edge: per-IP global ceiling (Traefik).
- App: per-user + per-endpoint token bucket in Redis. On exceed → `429` with
  `Retry-After` and `X-RateLimit-{Limit,Remaining,Reset}` headers.
- Auth endpoints get stricter buckets + login-abuse protection + CAPTCHA hook.

## 8. Object-level permissions

- Every resource enforces **object-level authorization** (DRF object
  permissions), not just authentication.
- Examples: only conversation participants read its messages; private media
  requires a signed URL tied to the requester; only friends see friends-only
  posts; admin/moderation endpoints require RBAC roles.

## 9. Endpoint catalog (representative; full OpenAPI generated in code)

### Identity
```
POST   /api/v1/auth/register/
POST   /api/v1/auth/login/
POST   /api/v1/auth/logout/
POST   /api/v1/auth/refresh/
POST   /api/v1/auth/verify-email/
POST   /api/v1/auth/password/forgot/
POST   /api/v1/auth/password/reset/
GET    /api/v1/auth/sessions/
DELETE /api/v1/auth/sessions/{id}/
```

### Profiles & Pages
```
GET    /api/v1/me/
PATCH  /api/v1/me/
GET    /api/v1/users/{handle}/
GET    /api/v1/users/{handle}/posts/
GET    /api/v1/users/{handle}/friends/
GET    /api/v1/users/{handle}/followers/
GET    /api/v1/users/{handle}/following/
POST   /api/v1/users/{id}/block/
DELETE /api/v1/users/{id}/block/
POST   /api/v1/pages/
GET    /api/v1/pages/{handle}/
PATCH  /api/v1/pages/{id}/
POST   /api/v1/pages/{id}/members/
PATCH  /api/v1/pages/{id}/members/{member_id}/
```

### Friends & Follows
```
POST   /api/v1/friends/requests/
POST   /api/v1/friends/requests/{id}/accept/
POST   /api/v1/friends/requests/{id}/reject/
DELETE /api/v1/friends/{user_id}/
POST   /api/v1/follows/{user_id}/
DELETE /api/v1/follows/{user_id}/
```

### Posts, comments, reactions
```
GET    /api/v1/feed/
POST   /api/v1/posts/
GET    /api/v1/posts/{id}/
PATCH  /api/v1/posts/{id}/
DELETE /api/v1/posts/{id}/
POST   /api/v1/posts/{id}/reactions/
DELETE /api/v1/posts/{id}/reactions/{reaction_id}/
POST   /api/v1/posts/{id}/comments/
POST   /api/v1/comments/{id}/replies/
POST   /api/v1/posts/{id}/save/
DELETE /api/v1/posts/{id}/save/
POST   /api/v1/posts/{id}/share/
POST   /api/v1/posts/{id}/report/
```

### Media (signed-URL flow — no large bodies through the API)
```
POST   /api/v1/media/uploads/sign/      // → { upload_url, media_id, fields }
POST   /api/v1/media/uploads/{id}/complete/
GET    /api/v1/media/{id}/              // metadata + variant URLs
GET    /api/v1/media/{id}/download-url/ // short-lived signed download URL
POST   /api/v1/media/resolve/           // {ids: [..≤100]} → detail payloads the viewer may see; others absent (own throttle scope `media_resolve`)
GET    /api/v1/media/{id}/playback/     // tokenised HLS playlist URL, poster, MP4 fallback
POST   /api/v1/media/playback/resolve/  // {ids: [..≤100]} → playback for each watchable video; others absent
```

### Chat
```
GET    /api/v1/conversations/
POST   /api/v1/conversations/
GET    /api/v1/conversations/{id}/messages/
POST   /api/v1/conversations/{id}/messages/
POST   /api/v1/conversations/{id}/voice-messages/
POST   /api/v1/messages/{id}/reactions/
POST   /api/v1/messages/{id}/read/
POST   /api/v1/conversations/{id}/mute/
```

### Marketplace
```
GET    /api/v1/marketplace/listings/
POST   /api/v1/marketplace/listings/
GET    /api/v1/marketplace/listings/{id}/
PATCH  /api/v1/marketplace/listings/{id}/
POST   /api/v1/marketplace/listings/{id}/save/
POST   /api/v1/marketplace/listings/{id}/report/
GET    /api/v1/marketplace/categories/
GET    /api/v1/marketplace/sellers/{id}/        // seller summary; 404 when hidden or no public listings
GET    /api/v1/marketplace/sellers/{id}/shop/   // always 200 {has_shop}: the profile's Shop tab
```

### Notifications & devices
```
GET    /api/v1/notifications/
POST   /api/v1/notifications/read/
POST   /api/v1/devices/push-token/
GET    /api/v1/notifications/preferences/
PATCH  /api/v1/notifications/preferences/
```

### Search
```
GET    /api/v1/search/?type=users|posts|pages|listings|hashtags&q=...
GET    /api/v1/search/autocomplete/?q=...
```

### Ads (advertiser-facing)
```
POST   /api/v1/ads/advertisers/
POST   /api/v1/ads/campaigns/
POST   /api/v1/ads/campaigns/{id}/ad-sets/
POST   /api/v1/ads/ad-sets/{id}/creatives/
GET    /api/v1/ads/campaigns/{id}/report/
```

### Admin & Moderation (RBAC-gated)
```
GET    /api/v1/admin/users/
GET    /api/v1/admin/reports/
POST   /api/v1/admin/moderation/cases/{id}/action/
GET    /api/v1/admin/service-health/
GET    /api/v1/admin/feature-flags/
PATCH  /api/v1/admin/feature-flags/{key}/
```

## 10. Real-time (WebSocket) contract

- Endpoint: `wss://<host>/ws/v1/`. Auth via access token in the connection
  (subprotocol or first `auth` frame), re-validated periodically.
- Client→server frames: `subscribe`, `unsubscribe`, `typing`, `ping`.
- Server→client frames carry the **same event envelope as doc 04** so web and
  mobile parse one shape. Example `chat.message.created` pushed to participants.
- Reconnect with exponential backoff + jitter; on prolonged failure, clients
  fall back to REST polling for messages/notifications.

## 11. Mobile-readiness checklist (baked into the contract)

- Versioned, stable, documented (OpenAPI) endpoints.
- Cursor pagination everywhere timeline-like.
- Upload via signed URLs (resumable-friendly), not multipart through the API.
- `POST /devices/push-token/` for APNs/FCM tokens.
- Token refresh flow + device/session management.
- Consistent error envelope + machine codes.
- Deep-link-friendly canonical resource URLs.
- No web-only assumptions in business logic (no reliance on cookies for API
  auth on mobile — bearer tokens work everywhere).
