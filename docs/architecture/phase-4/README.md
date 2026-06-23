# Phase 4 — Chat & Real-Time (Report)

> Status: **implemented**. Adds the **Chat** microservice and the platform's
> first **ASGI/WebSocket** component — the **Realtime gateway** (Django
> Channels) — bridging the event bus to connected clients.

---

## 1. Architecture changes

- **Chat** service (`chat_db`): DMs, group chats, marketplace/page/support
  conversation types; messages (text/image/video/file/audio/voice/share);
  attachments (voice notes reference Media), reactions, read receipts (via
  `last_read_message_id`), mute, pin. Strict object-level rule: **only active
  members** touch a conversation. DMs are deduplicated by a canonical `dm_key`.
- **Realtime gateway** (Channels/ASGI, **no database**): JWT-authenticated
  WebSocket endpoint (`/ws/v1/`), presence (Redis), typing indicators, and a
  Redis **channel layer** so sockets scale horizontally across nodes.
- **Event-bus → socket bridge:** a kombu consumer (`realtime` + the reusable
  `EventWorker`) pushes `message.created/read/reacted`, `notification.created`,
  and `feed.item.added` to the right user groups. Critical state stays in
  Chat/Notification/Feed — the gateway is a stateless fan-out edge, so a missed
  push is recovered by the client via REST/polling (graceful degradation).
- **Cross-service contract:** Chat puts the conversation's `recipients`
  (member ids) into `message.created`, so the gateway fans out to user groups
  **without its own database** — keeping the boundary clean.

## 2. Files created / changed

**Chat** (`services/chat/`): `config/*`, `chat/{models,services,events,
serializers,views,urls,handlers,apps}.py`, `consume_events`, tests, Dockerfile,
packaging.

**Realtime** (`services/realtime/`): `config/{settings,urls,asgi}.py`,
`realtime/{consumers,auth,presence,groups,routing,bridge}.py`, `consume_events`
(bridge), tests (`WebsocketCommunicator`), `Dockerfile` (Daphne), packaging.

**Infra:** `postgres/init` (+chat_db), `compose` (+5 services: chat web/relay/
consumer, realtime, realtime-bridge; Traefik `/api/v1/conversations|messages`
+ `/ws` routes), `prometheus.yml` (+chat, +realtime), `.env.example`.

## 3. Services added / changed

| Service | Role | Port | Notes |
|---------|------|------|-------|
| **chat** + relay + consumer | conversations/messages API | 8006 | own DB; `user.blocked` consumer |
| **realtime** | WebSocket gateway (Daphne/ASGI) | 8010 | **no DB**; Redis channel layer + presence |
| **realtime-bridge** | events → socket push | — | kombu consumer; `processed_model=None` |

## 4. Database changes

- **`chat_db`**: `conversation` (unique `dm_key` for DMs), `conversation_member`
  (unique per conversation+account; `last_read_message_id`, `muted_until`),
  `message` (indexed by conversation+time; month-partition candidate),
  `message_attachment` (voice duration), `message_reaction` (unique per user),
  `pinned_message`, `blocked_pair` + platform tables.
- Realtime gateway: **no database** (`DATABASES = {}`); state in Redis only.

## 5. API endpoints (live)

**Chat** (`/api/v1/`): `GET/POST conversations`,
`GET/POST conversations/{id}/messages`,
`POST conversations/{id}/voice-messages`, `POST conversations/{id}/read`,
`POST conversations/{id}/mute`, `POST conversations/{id}/pin`,
`POST messages/{id}/reactions`.

**Realtime:** `WS /ws/v1/?token=<access>` — client frames `subscribe`,
`unsubscribe`, `typing`, `ping`; server frames carry the event envelope shape
(`connected`, `chat.message.created`, `conversation.typing`, `pong`, …).

## 6. Event contracts

**Published (v1):** `message.created`, `message.read`, `message.reacted`,
`conversation.member.changed` (Chat). `conversation.typing` is **ephemeral**
(WebSocket-only, never persisted/outboxed).

**Consumed:** `user.blocked`/`user.unblocked` (Chat → block handling);
the Realtime bridge consumes `message.created/read/reacted`,
`notification.created`, `feed.item.added` and pushes them to sockets.

## 7. Tests

- **Chat** (Postgres): DM dedup (single canonical thread); **non-member 404**
  (no disclosure); `message.created` carries correct `recipients`; **voice
  message** (type+attachment+duration); blocked user can't DM; group create +
  send; mark-read emits event; react emits event; **outsider can't react (404)**.
- **Realtime** (`WebsocketCommunicator`, in-memory channel layer): connect
  **rejected without/with bad token**; connect + receive a bridged push;
  **typing broadcast** between two subscribed clients; ping/pong.
- **Quality gates:** `ruff` clean (200 files); `docker compose config` valid.

## 8. Commands

```bash
make up   # now also builds chat (+relay,+consumer), realtime, realtime-bridge
# WebSocket (dev):  ws://localhost:8080/ws/v1/?token=<access>   (via Traefik)
#                   ws://localhost:8010/ws/v1/?token=<access>   (direct)
# Chat REST:        http://localhost:8006/api/v1/docs/
```

## 9. Risks

| Risk | Mitigation |
|------|------------|
| Single WS node holds connection state | Redis channel layer → horizontal scaling; source-of-truth in Chat, not the socket. |
| Missed pushes (socket down during event) | Client reconciles via REST (`GET messages`, `GET notifications`); bridge is best-effort. |
| `message.created` carries member list (payload size) | Fine for typical conversations; large groups could move to a conversation-group push later. |
| Presence is best-effort (TTL) | Acceptable; `last_seen` privacy + accuracy hardened in a later phase. |
| Python/Channels per-node connection ceiling | Horizontal scale now; extract a Go/Node gateway later if needed (ADR-006), contract unchanged. |
| Delivery receipts not yet persisted | Read receipts are; delivery is realtime-only for now (documented). |

## 10. Rollback notes

- Additive: 1 new DB (`chat_db`) + 5 compose services + the realtime gateway.
  Rollback = revert the Phase-4 commit / drop `services/{chat,realtime}` and
  their compose blocks; earlier services untouched.
- The Realtime gateway has no database, so there is nothing to migrate or
  restore; stopping it degrades the app to REST/polling only.
- `make clean` wipes dev volumes (incl. `chat_db`).

## 11. Completion checklist

- [x] Chat: DM + group + (page/marketplace/support) conversation types
- [x] Messages: text/image/video/file/audio/voice/share + attachments + replies
- [x] Read receipts, reactions, mute, pin; member-only object-level authz
- [x] DM dedup; `user.blocked` consumer; outbox events with `recipients`
- [x] Realtime: JWT-authenticated WebSocket, presence, typing, subscribe
- [x] Realtime: Redis channel layer (horizontal scaling), no DB
- [x] Event-bus → socket bridge (chat/notification/feed pushes)
- [x] Infra: chat_db, compose services, Traefik `/ws` route, Prometheus
- [x] `ruff` clean (200 files); `docker compose config` valid
- [x] **Verified: Chat 9/9 and Realtime 5/5 green** (Chat on Postgres; Realtime
      via `WebsocketCommunicator` + in-memory channel layer); `ruff` clean (200
      files); `docker compose config` valid.
- [ ] **Your approval to proceed to Phase 5 — Marketplace.** ← gate

### Verification notes

Run on the host venv (Chat against Dockerized Postgres; Realtime needs no DB).
The in-container image build remains blocked in this sandbox by the corporate-CA
TLS limitation noted in [Phase 1](../phase-1/README.md) — not a code issue; CI
builds images. One **test** bug was fixed (asserting the outbox envelope's nested
`payload.recipients`); no service-code changes were needed.
