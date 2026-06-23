# 04 — Event Contracts

Asynchronous events are the backbone of cross-context communication. This
document fixes the envelope, the catalog, and the reliability mechanics.

## 1. Envelope (versioned, immutable)

Every event on the bus uses this shape:

```jsonc
{
  "event_id": "01J8Z...",          // UUIDv7, globally unique, dedupe key
  "event_type": "chat.message.created",
  "event_version": 1,               // integer; bump on breaking payload change
  "occurred_at": "2026-06-23T12:34:56.789Z", // ISO-8601 UTC, when fact happened
  "producer": "chat-service",       // emitting service
  "actor_id": "uuid|null",          // account/page that caused it (null = system)
  "subject_id": "uuid",             // primary resource the event is about
  "correlation_id": "req_01H...",   // ties event to originating request/trace
  "causation_id": "event_id|null",  // the event that caused this one (chains)
  "partition_key": "conversation:uuid", // ordering/sharding key
  "payload": { }                    // type-specific, additive-only within a version
}
```

Rules:
- **Additive evolution:** within a version you may only *add* optional fields.
  Removing/renaming/retyping a field requires `event_version + 1`. Consumers
  ignore unknown fields.
- **Events are facts, past tense.** Names are `noun.verb` in past tense.
- **No PII beyond IDs** in payloads unless strictly required; never secrets,
  tokens, passwords, or raw message bodies on broad topics.
- `partition_key` guarantees per-entity ordering (e.g. all events for one
  conversation land on the same partition/queue shard, in order).

## 2. Outbox pattern (reliable publishing)

Events are **never** published directly inside the business transaction. Instead:

```
┌─ DB transaction ────────────────────────────┐
│  1. write business rows (e.g. Message)       │
│  2. INSERT into outbox_event (same tx)        │
└──────────────────────────────────────────────┘
            │  (committed atomically)
            ▼
   Outbox relay (Celery beat / dedicated poller)
            │  reads unpublished rows in order
            ▼
   Publish to broker  ──► mark outbox row published
            │  (at-least-once)
            ▼
   Consumers (idempotent via event_id dedupe)
```

- Guarantees **at-least-once** delivery with **exactly-once effect** (consumers
  dedupe on `event_id` via an `idempotency`/`processed_events` table).
- The relay is **idempotent and resumable**: a crash mid-publish re-publishes;
  duplicates are harmless because consumers dedupe.
- `OutboxEvent` table lives in **each producing service's own DB** (see doc 05).

## 3. Consumer reliability

| Mechanism | Behavior |
|-----------|----------|
| **Idempotency** | Consumer records `event_id` in a `processed_events` table; re-delivery is a no-op. |
| **Retry** | Transient failure → retry with exponential backoff + jitter (e.g. 5 attempts). |
| **DLQ** | After max retries, message → **dead-letter queue** with full envelope + error + attempt count. |
| **Replay** | Operators can re-drive DLQ messages after a fix; ordering preserved by `partition_key`. |
| **Poison detection** | A handler that always throws is quarantined, alerted, not infinitely retried. |
| **Ordering** | Per `partition_key` only (not global). Handlers tolerate out-of-order across keys. |

## 4. Transport & topic layout

- **Phase 1–6:** RabbitMQ. Topic exchange `tara.events`; routing key =
  `event_type`. Each consuming service binds a durable queue with the patterns
  it needs (`post.*`, `*.reported`, …). Per-queue DLX → `tara.events.dlq`.
- **Phase 7+ firehose:** Kafka/Redpanda topics for `ad.impression.recorded`,
  `ad.click.recorded`, and analytics ingest (high volume, replayable,
  partitioned). Domain events may migrate to Kafka topics later behind the same
  `EventPublisher` abstraction. (See [ADR-003](09-decision-log.md).)
- The producer code calls a single `EventPublisher.publish(event)`; the
  transport is swappable without touching business logic.

## 5. Event catalog (v1)

### Identity
| Event | Subject | Key payload | Main consumers |
|-------|---------|-------------|----------------|
| `account.registered` | account | handle?, email_verified=false | Profile (create profile), Notification |
| `account.verified` | account | — | Profile, Notification |
| `account.suspended` | account | reason, until? | Profile, Graph, Post, Chat (restrict) |
| `session.created` | session | device, ip_region | Notification (new-login alert), Security |
| `session.revoked` | session | — | Realtime (drop sockets) |

### Profile & Pages
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `profile.updated` | account | changed_fields, public_snapshot | Search, Feed/Post/Chat (refresh author cache) |
| `page.created` | page | handle, category | Search |
| `page.member.changed` | page | member_id, role, action | Notification, Audit |

### Social Graph
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `friendship.requested` | request | from, to | Notification |
| `friendship.accepted` | friendship | a, b | Notification, Feed (edge), Search (mutuals) |
| `friendship.removed` | friendship | a, b | Feed |
| `user.followed` | follow | follower, target(type) | Notification, Feed (edge) |
| `user.unfollowed` | follow | follower, target | Feed |
| `user.blocked` | block | blocker, blocked | Post, Chat, Feed (hide/sever) |
| `user.unblocked` | block | blocker, blocked | Post, Chat, Feed |

### Posts
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `post.created` | post | author, audience, media_ids, hashtags, mentions | Feed (fan-out), Search, Notification (mentions) |
| `post.updated` | post | changed | Feed, Search |
| `post.deleted` | post | — | Feed, Search |
| `post.reacted` | post | reactor, reaction_type | Notification |
| `post.commented` | comment | post_id, author | Notification, Feed (signal) |
| `comment.replied` | comment | parent_id, author | Notification |
| `post.shared` | share | sharer, post_id | Feed, Notification |
| `post.reported` | report | reporter, reason | Moderation |

### Feed
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `feed.item.added` | feed_item | recipient, post_id | Realtime (new-post indicator) |

### Media
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `media.uploaded` | media | owner, kind, bytes | File Processing |
| `media.processed` | media | variants, waveform?, duration? | Post, Chat, Marketplace |
| `media.failed` | media | error, retryable | Post, Chat (show retry) |

### Chat
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `message.created` | message | conversation_id, sender, type | Realtime, Notification |
| `message.read` | receipt | conversation_id, reader, up_to | Realtime |
| `message.reacted` | reaction | message_id, reactor, type | Realtime, Notification |
| `conversation.typing` | conversation | actor (ephemeral, Realtime-only) | Realtime |
| `conversation.member.changed` | conversation | member, action | Realtime, Notification |
| `user.presence.changed` | account | status, last_seen? (privacy-filtered) | Realtime |

### Marketplace
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `listing.created` | listing | seller, category, price | Search, Moderation (queue) |
| `listing.updated` | listing | changed | Search |
| `listing.status.changed` | listing | from, to | Search, Notification |
| `listing.reported` | report | reporter, reason | Moderation |
| `marketplace.contact.requested` | listing | buyer, seller | Chat (create conversation) |

### Notification
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `notification.created` | notification | recipient, kind | Realtime (push to client) |

### Moderation
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `report.created` | report | target_type, target_id | Moderation (own queue) |
| `moderation.actioned` | case | target, action (remove/restrict/warn/shadow) | Post/Chat/Marketplace/Profile (enforce), Notification, Audit |
| `appeal.created` | appeal | case_id | Moderation |

### Advertisement
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `ad.impression.recorded` | ad | placement, viewer_bucket | Analytics, Billing ledger |
| `ad.click.recorded` | ad | placement, viewer_bucket | Analytics, Billing ledger |
| `ad.review.decided` | creative | decision | Ads (activate), Notification |

> Impression/click events are **deduplicated** (event_id) and **rate-limited**
> at ingest, and travel on the firehose topic, never the transactional path.

## 6. Schema governance

- Each event type has a **JSON Schema** stored in `libs/events/schemas/` and a
  generated typed model (Python + TypeScript) so producers and consumers share
  one definition. CI validates sample payloads against schemas.
- A **schema registry** (or the in-repo schemas in early phases) gates breaking
  changes; adding a new `event_version` requires a migration note for consumers.
- Consumer compatibility is **contract-tested** (doc on testing): a consumer's
  expectations are verified against the producer's published schema in CI.

## 7. What must NOT be an event-only flow

- **Money / billing ledger entries:** events feed analytics, but the
  authoritative ledger uses transactional writes + reconciliation, not
  fire-and-forget events.
- **Authorization decisions:** never trust an event to grant access; always
  re-check object-level permissions at the owning service.
