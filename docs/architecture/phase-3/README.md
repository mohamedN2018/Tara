# Phase 3 — Posts, Feed & Media (Report)

> Status: **implemented**. Adds three microservices — **Media**, **Post**, and
> **Feed** — and the platform's first **large-scale fan-out**: a created post is
> distributed to recipients' feeds asynchronously via the event bus, with the
> feed kept readable even if the Post service is down.

---

## 1. Architecture changes

- Three new independently deployable services (own DB, API, events, pipeline):
  **Media** (`media_db`), **Post** (`post_db`), **Feed** (`feed_db`).
- **Signed-URL media flow:** clients upload/download directly to object storage
  (MinIO/S3) via presigned URLs; large payloads never touch the API tier. Media
  is the only context that talks to storage. Async (placeholder) processing
  pipeline: `upload → processing → ready` emitting `media.uploaded/processed/failed`.
- **Audience-aware posts:** post visibility (`public/friends/followers/only_me`)
  is enforced at read time by resolving the viewer↔author relationship through
  the **Graph internal API** behind a circuit breaker (degrades to "not visible"
  if Graph is down). Blocks hide content (404).
- **Fan-out-on-write feed:** the Feed service consumes `post.created`, asks Graph
  for the author's followers+friends (new internal `/fanout/{id}` endpoint), and
  writes a **denormalized FeedItem snapshot** into each recipient's feed — so the
  feed read path needs **no synchronous call to Post** (resilient by design).
  Celebrity fan-out is capped (`FANOUT_MAX_RECIPIENTS`) with a logged drop, not
  silent truncation; fan-out-on-read for large accounts is a Phase-9 follow-up.
- **Second multi-consumer event:** `user.blocked` is now consumed by Profile,
  Post, and Feed; `post.created` drives Feed; `user.unfollowed` prunes feeds.

## 2. Files created / changed

**Graph (extended):** `internal_views.py` + `internal_urls.py` — added
`/internal/v1/fanout/{account_id}` for Feed.

**Media** (`services/media/`): `config/*`, `media_app/{models,storage,services,
tasks,events,serializers,views,internal_views,urls,internal_urls,apps}.py`,
tests, Dockerfile, entrypoint (creates bucket), packaging.

**Post** (`services/post/`): `config/*`, `posts/{models,clients,events,services,
serializers,views,urls,handlers,apps}.py`, `consume_events`, tests, packaging.

**Feed** (`services/feed/`): `config/*`, `feed/{models,clients,events,services,
serializers,views,urls,handlers,apps}.py`, `consume_events`, tests, packaging.

**Infra:** `postgres/init` (+media_db/post_db/feed_db), `compose` (+8 services:
media/post/feed web, relays, consumers; Traefik routes; MinIO dep + bucket),
`prometheus.yml` (+3 targets), `.env.example` (+DBs, storage, secrets).

## 3. Services added / changed

| Service | Role | Port | Notes |
|---------|------|------|-------|
| **media** + `media-relay` | uploads/metadata + processing | 8003 | signed URLs; relay also runs `process_media` |
| **post** + `post-relay` + `post-consumer` | posts/comments/reactions/saves | 8004 | audience via Graph; consumes `user.blocked` |
| **feed** + `feed-relay` + `feed-consumer` | home feed | 8005 | fan-out-on-write; consumes `post.created`, `user.unfollowed`, `user.blocked` |
| graph | (extended) | 8002 | + internal fan-out endpoint |

## 4. Database changes

- **`media_db`**: `media_asset`, `media_variant`, `upload_session` + outbox/processed.
- **`post_db`**: `post`, `post_media`, `post_reaction` (unique per user),
  `comment` (self-FK replies), `share`, `hashtag`+`post_hashtag`, `mention`,
  `saved_collection`, `saved_item` (unique per owner+item), `post_report`,
  `blocked_pair` + platform tables.
- **`feed_db`**: `feed_item` (unique recipient+post; denormalized snapshot;
  index on recipient+post_created_at) + outbox/processed.
- Counts (`reaction_count`, etc.) updated with `F()` expressions to avoid races.

## 5. API endpoints (live)

**Media** (`/api/v1/`): `POST media/uploads/sign`,
`POST media/uploads/{id}/complete`, `GET media/{id}`, `GET media/{id}/download-url`;
internal `GET /internal/v1/media/{id}`.

**Post** (`/api/v1/`): `POST posts`, `GET/PATCH/DELETE posts/{id}`,
`POST/DELETE posts/{id}/reactions`, `GET/POST posts/{id}/comments`,
`POST comments/{id}/replies`, `POST posts/{id}/share`,
`POST/DELETE posts/{id}/save`, `POST posts/{id}/report`, `GET/POST saved`.

**Feed** (`/api/v1/`): `GET feed` (cursor, newest-first).

**Graph internal:** `GET /internal/v1/fanout/{account_id}`.

## 6. Event contracts

**Published (v1):** `media.uploaded/processed/failed` (Media);
`post.created/updated/deleted`, `post.reacted`, `post.commented`,
`comment.replied`, `post.shared`, `post.reported` (Post);
`feed.item.added` (Feed, per recipient).

**Consumed:** `post.created` (Feed→fan-out), `user.unfollowed` (Feed→prune),
`user.blocked`/`user.unblocked` (Post & Feed→hide/prune). `post.created` payload
carries the snapshot fields Feed needs, so Feed never calls Post synchronously.

## 7. Tests

- **Media:** sign→complete→process→ready flow + `media.uploaded`/`media.processed`
  events; size-limit rejection; **private media 404 to non-owner**; download-url
  requires ready (409); internal endpoint requires service token.
- **Post:** create emits `post.created` + hashtag/mention extraction;
  empty-post rejected; **audience visibility** (public/friends hidden↔visible/
  only_me/blocked) with Graph mocked; reaction idempotent + count; comment+reply
  events + count; save/unsave idempotent; report emits event.
- **Feed:** **public fan-out** reaches followers+friends+author (idempotent on
  re-delivery); only_me skips Graph; **home feed endpoint** returns snapshots
  (cursor envelope); unfollow prunes the author's items.
- **Quality gates:** `ruff check` + `ruff format --check` clean (183 files);
  `docker compose config` valid.

## 8. Commands

```bash
make up        # now also builds media/post/feed (+relays, +consumers)
make migrate   # identity; profile/graph/media/post/feed auto-migrate on first boot
# direct dev access:  media :8003  post :8004  feed :8005  (/api/v1/docs/)
# MinIO console http://localhost:9001 (bucket 'tara-media' auto-created)
```

## 9. Risks

| Risk | Mitigation |
|------|------------|
| Fan-out-on-write blows up for celebrity accounts | Cap + logged drop now; fan-out-on-read in Phase 9; partition_key set for ordering. |
| `feed.item.added` per recipient = event volume | Acceptable at current scale; revisit batching/aggregation when realtime (Phase 4) consumes it. |
| Post visibility depends on Graph availability | Circuit breaker + safe default (hidden) + local block read-model. |
| Media processing is a **placeholder** (no real transcode/thumbnail) | Clearly labeled; original preserved; `media.failed` retry state; real pipeline is a later phase. |
| Media attach trusts client-supplied `media_ids` | Ownership enforced at Media; Post→Media verification can be added when needed. |
| Feed read returns stale snapshots after edits | Acceptable (eventual); a `post.updated` consumer can refresh snapshots later. |

## 10. Rollback notes

- Additive: 3 new services + 3 new DBs + 8 compose services + 1 Graph internal
  endpoint. Rollback = revert the Phase-3 commit / drop `services/{media,post,
  feed}` and their compose blocks; earlier services untouched (Graph change is
  purely additive — a new internal route).
- Data: `media_db`/`post_db`/`feed_db` are independent; `feed_db` is fully
  rebuildable from `post.created` replay. `make clean` wipes dev volumes.
- Disable: stop `feed-consumer` to pause fan-out without data loss (events stay
  queued/outboxed); stop `post-consumer` to pause block-sync.

## 11. Completion checklist

- [x] Media: signed upload/download, metadata, async (placeholder) processing, events
- [x] Media: object-level auth (private media), internal lookup API
- [x] Post: text/image/video/share/link/poll types; audience visibility via Graph
- [x] Post: reactions, comments + nested replies, shares, saved collections, reports
- [x] Post: hashtag + mention extraction; outbox events; `user.blocked` consumer
- [x] Feed: fan-out-on-write on `post.created` with denormalized snapshots
- [x] Feed: cursor-paginated home feed; unfollow/block pruning; celebrity cap
- [x] Graph internal fan-out endpoint
- [x] Infra: per-service DBs, MinIO bucket, compose services, Traefik, Prometheus
- [x] `ruff` clean (183 files); `docker compose config` valid
- [x] **Verified: Media 5/5, Post 10/10, Feed 4/4 green against PostgreSQL**;
      `ruff` clean (183 files); `docker compose config` valid.
- [ ] **Your approval to proceed to Phase 4 — Chat & Real-Time.** ← gate

### Verification notes

Run on the host venv against a Dockerized Postgres (the in-container image build
is blocked in this sandbox by the corporate-CA/TLS limitation noted in
[Phase 1](../phase-1/README.md) — not a code issue; CI builds images). No bugs
required fixing in this run; the only pre-test fixups were lint nits
(`set()` generator → set comprehension).

