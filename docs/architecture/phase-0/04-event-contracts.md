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
| `account.role.granted` | account | account_id, role; `actor_id` = the granting admin; `correlation_id` = admin's edge request id. Emitted only when a grant is new; behind `IDENTITY_EMIT_AUDIT_EVENTS` | Admin (audit log) |
| `account.role.revoked` | account | account_id, role (as above) | Admin (audit log) |
| `capability.matrix.changed` | role name | role, capability, state (`grant`/`revoke`/`default`), previous (same values). One event per changed cell; a no-op change emits nothing | Admin (audit log) |

### Profile & Pages
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `profile.updated` | account | changed_fields, public_snapshot | Search, Feed/Post/Chat (refresh author cache) |
| `page.created` | page | handle, category | Search |
| `page.member.changed` | page | member, role, action | (none yet) |

### Social Graph
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `friendship.requested` | request | from, to | Notification |
| `friendship.request.withdrawn` | request | from, to (emitted only when the requester cancels; a reject by the recipient emits nothing) | Notification |
| `friendship.accepted` | friendship | a, b | Notification, Feed (edge), Search (mutuals) |
| `friendship.removed` | friendship | a, b, reason (`unfriend` \| `block`) | Feed |
| `user.followed` | follow | follower, target(type) | Notification, Feed (edge) |
| `user.unfollowed` | follow | follower, target, target_type, reason (`unfollow` \| `block`) | Feed |
| `user.blocked` | block | blocker, blocked | Post, Chat, Feed (hide/sever) |
| `user.unblocked` | block | blocker, blocked | Post, Chat, Feed |

A block ends every edge between the two accounts in the same transaction: graph emits `user.blocked`, then `friendship.removed` (only if they were friends; a pending request is deleted silently) and one `user.unfollowed` per follow direction, all with `reason=block` and `actor_id` = the blocker. Consumers therefore react to a block exactly as to an unfriend or unfollow. `reason` is additive (v1); a re-block emits nothing.

### Posts
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `post.created` | post | author, audience, media_ids, hashtags, mentions | Feed (fan-out), Search, Notification (mentions) |
| `post.updated` | post | post_id, author_id, audience (may change on edit), comment_policy (additive, v1), excerpt, hashtags (the full list, additive, v1), new_mentions. Also emitted, with no new_mentions, when an overturned appeal restores a removed post | Feed, Search |
| `post.deleted` | post | post_id. Also emitted when moderation removes a post. Feed and search keep a tombstone, so a retried older `post.created`/`post.updated` cannot bring it back. Post consumes its own event to restrict the post's media through media's bind (retried while media is down), so only the owner can fetch them | Feed, Search, Post |
| `post.reacted` | post | reactor, reaction_type | Notification |
| `post.unreacted` | post | post_id, reactor, reaction_type, author_id. Once per removed reaction | — (for later notification clean-up) |
| `post.commented` | comment | post_id, author | Notification, Feed (signal) |
| `comment.replied` | comment | parent_id (the thread root: replies are flattened onto it since 1.3), reply_to_id, parent_author_id (the author of the comment answered, who gets the notification), root_author_id, post_author_id, author | Notification |
| `comment.edited` | comment | post_id, comment_id, author, new_mentions | Post (mention notifications) |
| `comment.deleted` | comment | post_id, comment_id, author_id, post_author_id, parent_id, removed_ids (a root takes its thread), by (`author`, `post_author` or `moderation`) | — |
| `comment.restored` | comment | post_id, comment_id, restored_ids (a moderation removal overturned) | — |
| `comment.reacted` | comment | post_id, comment_id, reactor, reaction_type, author_id. Only a new reaction | — |
| `comment.reported` | comment | comment_id, post_id, reporter, reason, owner_id (the comment author). Emitted once per reporter per comment, and only when the reporter can see the comment | Moderation (needs `comment.reported` in its intake map) |
| `post.shared` | post | sharer, post_id, share_post_id, author_id | Notification |
| `user.mentioned` | post | recipient, actor, post_id, comment_id (only readers who can open the post) | Notification |
| `post.reported` | post | post_id, reporter, reason, owner_id (the post author; additive, v1). Emitted once per reporter per post, and only when the reporter can see the post | Moderation |

### Events (post service `gatherings` app, roadmap 1.13)
Schemas: `libs/tara_events/tara_events/schemas/gathering.*.v1.json`. Ids, enums and times only: never the title, description, place or link. Recipient lists are chunked (at most 500 ids per event, with `chunk` and `chunks`); a consumer that only needs the event's state reads chunk 0. Every row is written in the same transaction as the state change. Partition key `gathering:<id>`.

| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `gathering.created` | gathering | gathering_id, host_id, host_type, audience (`public`/`friends`/`invite_only`), status, location_type (`place`/`online`), starts_at, ends_at, capacity, cover_media_id | (search in 1.15) |
| `gathering.updated` | gathering | as `gathering.created`, plus changed[] (edited fields), notify[] (the time or place fields among them) and recipients[] (going and interested, only when notify[] is not empty). Also emitted with changed=[`moderation_status`] when an overturned removal restores the event | Notification (`gathering.update` when notify[] is set) |
| `gathering.cancelled` | gathering | as `gathering.created`, plus recipients[] (going and interested) | Notification (`gathering.cancel`) |
| `gathering.deleted` | gathering | gathering_id, host_id, by (`moderation` when a moderator removed it; absent for the host's delete) | Notification (purges `gathering:<id>`) |
| `gathering.rsvp` | gathering | gathering_id, host_id, account_id, status (`going`/`interested`/`not_going`, null when taken back), previous_status, going_count, interested_count. Only a real change | Notification (`gathering.rsvp` to the host, aggregated per event, for a new going or interested) |
| `gathering.invited` | gathering | gathering_id, host_id, invitee_ids[] (newly invited friends only, at most 50) | Notification (`gathering.invite`) |
| `gathering.reminder` | gathering | gathering_id, host_id, window (`24h`: host, going and interested; `1h`: host and going), starts_at, recipients[]. Once per event and window (`gathering_reminder_log`); a new start time re-arms both | Notification (`gathering.reminder`) |
| `gathering.reported` | gathering | gathering_id, reporter, reason (an enum: spam, scam, hate, violence, nudity, harassment, false_information, other), owner_id (the host). Once per reporter per event, and only when the reporter can see it | Moderation (`gathering` target) |

Post consumes `moderation.actioned` with `target_type=gathering` (`remove` hides the event everywhere and emits `gathering.deleted`; `approve` restores it) and `user.blocked` (the blocked side loses its RSVP and invite on the other's events), and `friendship.removed` (on friends-only events hosted by either side, the other side loses its RSVP and invite, freeing the seat; invite-only and public events are untouched; graph is re-checked first so a stale event after a re-friend drops nothing; no notification). An event's cover is bound in media to the event id, restricted, and media asks post's `/internal/v1/posts/<id>/visibility/` for it like for post media.

### Feed
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `feed.item.added` | post | recipients[], post_id, author_id (one summary event per fan-out) | Realtime (new-post indicator) |

### Media
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `media.uploaded` | media | owner, kind, bytes (the stored object's real size, not the declared one) | File Processing |
| `media.processed` | media | variants, waveform?, duration? | Post, Chat, Marketplace |
| `media.failed` | media | error, retryable | Post, Chat (show retry) |

### Chat
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `message.created` | message | conversation_id, message_id, sender, type, seq, recipients[] (active members), muted[], preview (first 140 characters of the body, for the notification text) | Realtime, Notification |
| `message.read` | receipt | conversation_id, reader, up_to_message_id, up_to_seq, recipients[] (a DM: both members; a group: the reader and the senders the pointer passed). Only when the pointer moves forward | Realtime, Notification (clears the conversation's notifications) |
| `message.delivered` | receipt | conversation_id, account, up_to_seq, recipients[] (as for `message.read`) | Realtime |
| `message.edited` | message | conversation_id, message_id, editor, recipients[]. No body: clients refetch | Realtime |
| `message.deleted` | message | conversation_id, message_id, scope (`everyone`: a tombstone stays; `moderation`: hidden until restored), recipients[]. Emitted once per removal | Realtime |
| `message.reacted` | reaction | conversation_id, message_id, reactor, type (null when the reaction was removed), recipients[] | Realtime |
| `conversation.typing` | conversation | actor (ephemeral, Realtime-only; never echoed to the typist's own sockets) | Realtime |
| `conversation.member.changed` | conversation | conversation_id, action (`created`, `added`, `removed`, `renamed`, `role_changed`, `pinned`, `unpinned`, `blocked`), recipients[], revoked[] (additive, v1: accounts that just lost access; Realtime drops their live subscriptions). `blocked` is emitted by Chat when it applies `user.blocked`, once per shared DM or marketplace thread, with no recipients so the blocked side is not told | Realtime |
| `user.presence.changed` | account | status, last_seen? (privacy-filtered). Not a bus event: Realtime pushes `presence.changed` frames only to DM peers and friends, and a block seen on the bus keeps the pair hidden even while Chat's copy of the block lags | Realtime |

### Calls (chat `calls` app, roadmap 3.7 / 3.8)
Schemas: `libs/tara_events/tara_events/schemas/call.*.v1.json`. Ids and enums only. Every payload has `call_id`, `conversation_id` and `kind` (`audio`/`video`). Emitted only while calls are on (LiveKit key and secret set), in the same transaction as the state change.

| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `call.started` | call | conversation_type, initiator, recipients[] (the callees to ring: active members except the caller; in a group never someone blocked either way with the caller), ring_expires_at | Realtime (`call.ringing` to every callee device, `call.updated` to the caller's other devices), Notification (push-only ring, tag `call:<id>`, no in-app row) |
| `call.answered` | call | account (who accepted; a callee's first accept makes the call active), recipients[] (members and participants) | Realtime (`call.answered`), Notification (clears the ring on the answerer's other devices) |
| `call.declined` | call | account, recipients[]. In a DM, `call.ended` (reason `declined`) follows in the same transaction | Realtime, Notification (clears the decliner's ring) |
| `call.ended` | call | reason (`hangup`, `declined`, `left`, `lost`; `revoked` when only a removed member's seat ended, with just that account in recipients[]), duration_s, ringing[] (accounts whose ring must clear), recipients[] | Realtime (`call.ended`), Notification (clears the ring for ringing[]) |
| `call.missed` | call | initiator, missed[] (accounts that never answered), final (true: nobody answered or the caller gave up; false: group members who missed a call that went on), reason (`timeout`, `cancelled`, `ended`), recipients[] | Realtime (`call.missed`), Notification (in-app `call.missed` row per missed account, and a push that replaces the ring) |

The call-log line in the conversation is an ordinary `message.created` with `type=system` and a code as the body (`call:missed:<kind>`, `call:declined:<kind>`, `call:ended:<kind>:<seconds>`). Notification skips `system` messages, because a missed call already has its own kind.

### Marketplace
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `listing.created` | listing | seller, category, price | Search, Moderation (queue) |
| `listing.updated` | listing | changed | Search |
| `listing.status.changed` | listing | from, to | Search, Notification |
| `listing.reported` | report | listing_id, reporter, owner_id (the seller; only the owner may appeal; absent before 1.2), reason; once per reporter per listing | Moderation |
| `marketplace.contact.requested` | listing | buyer, seller | Chat (create conversation) |
| `listing.availability.changed` | listing | listing_id, seller_id, from, to (available/reserved/sold or null) | Search, Notification |
| `marketplace.inquiry.created` | listing | inquiry_id, listing_id, seller_id, buyer_id (first inquiry per buyer per listing) | (none yet; 4.7 metrics) |
| `marketplace.review.created` | review | review_id, listing_id, seller_id, buyer_id, rating | (none yet) |
| `marketplace.review.reported` | review | review_id, listing_id, seller_id, reporter, owner_id (the review's author), reason; once per reporter per review | Moderation (`listing_review` target) |
| `marketplace.review.status.changed` | review | review_id, seller_id, from, to (published/removed) | (none yet) |

### Notification
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `notification.created` | notification | recipient, kind | Realtime (push to client) |

### Moderation
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `report.created` | report | target_type, target_id | Moderation (own queue) |
| `moderation.actioned` | case | target, action (remove/restrict/warn/shadow/dismiss/approve). An overturned appeal emits it again only with the inverse of the decision: `approve` for removed content (post/comment/message/listing), and only when no other case's removal of that target still stands. Overturning a warning, or a user or page decision, emits nothing (audit log only). `appeal.resolved` records which appeal caused it | Post/Chat/Marketplace/Profile (enforce), Notification, Admin (audit log) |
| `appeal.created` | appeal | case_id | Moderation |
| `appeal.resolved` | appeal | appeal_id, case_id, target_type, status (`upheld`/`overturned`), reversal (`approve` or null). Never the appeal text. Behind `MODERATION_EMIT_AUDIT_EVENTS` | Admin (audit log) |

### Advertisement
| Event | Subject | Key payload | Consumers |
|-------|---------|-------------|-----------|
| `ad.impression.recorded` | ad | placement, viewer_bucket | Analytics, Billing ledger |
| `ad.click.recorded` | ad | placement, viewer_bucket | Analytics, Billing ledger |
| `ad.review.decided` | creative | decision; `actor_id` = the reviewer | Ads (activate), Notification, Admin (audit log) |

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
