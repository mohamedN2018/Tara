# 05 — Data Model Plan

PostgreSQL, **one logical database per bounded context**. No cross-database
foreign keys; cross-context references are stored as bare UUIDs and resolved via
API/events. This document lists entities, keys, indexing, partitioning, and the
conventions every table follows.

## 1. Global conventions

| Convention | Rule |
|-----------|------|
| **Public IDs** | UUIDv7 (time-sortable) primary keys for public-facing resources. Internal-only high-volume rows may use `bigint` surrogate PKs + a UUID external id. |
| **Timestamps** | `created_at`, `updated_at` (UTC, `timestamptz`) on every table. |
| **Soft delete** | `deleted_at timestamptz NULL` where content must be recoverable/auditable (posts, comments, messages, listings, accounts). Hard delete for ephemeral/cache rows. |
| **Audit attribution** | `created_by`, `updated_by` (account/page UUID) on operator- or multi-actor-editable tables (Pages, listings, moderation, ads, admin config). |
| **Uniqueness** | Enforced in DB via unique/partial indexes — not just app logic (esp. friend/follow/reaction dedupe). |
| **Money** | `numeric(19,4)` + ISO-4217 `currency` char(3). Never floats. |
| **Enums** | Postgres native enums or constrained `varchar` + check; documented status machines. |
| **Tenancy of events** | Each writable context's DB carries `outbox_event`, `processed_events` (idempotency), and a context-local `audit_log` partition. |

## 2. Cross-context reference rule (illustrated)

```
post_db.post.author_id   -- UUID of an Identity account; NOT a FK.
                         -- Display data comes from Profile's read API/cache,
                         -- refreshed by profile.updated events.
```

No `REFERENCES` across databases. Within a context, real FKs + `ON DELETE`
rules are used normally.

## 3. Entities per context

### 3.1 identity_db
- **account**(id, email[unique citext], email_verified, password_hash[argon2id],
  status[active/pending/suspended/deactivated/deleted], language, theme,
  created_at, last_login_at, deleted_at)
- **user_session**(id, account_id→account, device_id→device, ip_region,
  user_agent, created_at, last_seen_at, revoked_at)
- **refresh_token**(id, account_id, session_id, token_hash, family_id,
  rotated_from_id, expires_at, used_at, revoked_at) — *reuse detection on family*
- **email_verification**(id, account_id, token_hash, expires_at, consumed_at)
- **password_reset**(id, account_id, token_hash, expires_at, consumed_at)
- **device**(id, account_id, platform[web/ios/android], push_token_ref?, created_at)
- **security_event**(id, account_id, type, ip_region, metadata, created_at) — *partitioned by month*
- **two_factor_secret**(account_id, type[totp], secret_enc, confirmed_at) — *2FA-ready*

Indexes: `account(email)` unique; `refresh_token(family_id)`, `(account_id, expires_at)`;
`user_session(account_id, revoked_at)`.

### 3.2 profile_db
- **user_profile**(id, account_id[unique], handle[unique citext], display_name,
  bio, intro, city, country, avatar_media_id, cover_media_id, visibility
  [public/friends_only/private/custom], completion_pct)
- **profile_field_privacy**(id, profile_id, field_key, visibility) — per-field
- **user_link**(id, profile_id, label, url, position)
- **user_education**(id, profile_id, school, degree, field, start_year, end_year)
- **user_work_experience**(id, profile_id, company, title, start_date, end_date, current)
- **page**(id, owner_account_id, handle[unique citext], name, category,
  description, avatar_media_id, cover_media_id, contact, location, status)
- **page_member**(id, page_id, account_id, role[owner/admin/editor/moderator/
  advertiser/analyst], invited_by, created_at) — unique(page_id, account_id)
- **page_role** (lookup of role→permission set)

Indexes: unique `user_profile(handle)`, `page(handle)`;
`page_member(page_id, role)`; partial `user_profile(visibility) WHERE deleted_at IS NULL`.

### 3.3 graph_db
- **friendship**(id, account_low_id, account_high_id, status[pending/accepted],
  requested_by, created_at, accepted_at) — **unique(account_low_id,
  account_high_id)** with `low < high` enforced (symmetric dedupe)
- **follow_relation**(id, follower_id, target_id, target_type[user/page],
  created_at) — **unique(follower_id, target_id, target_type)**
- **block_relation**(id, blocker_id, blocked_id, created_at) — **unique(blocker_id, blocked_id)**
- **close_friend_relation**(id, account_id, friend_id, created_at) — unique pair
- **social_suggestion**(id, account_id, suggested_id, score, reason, computed_at) — cache

Indexes: `follow_relation(target_id, target_type)` (followers lookups);
`friendship(account_high_id, status)`; everything dedupe-constrained in DB.

### 3.4 post_db
- **post**(id, author_id, author_type[user/page], type[text/image/video/poll/
  link/share], body, audience[public/friends/followers/only_me/custom/page/group],
  shared_post_id?, link_preview_json, moderation_status, created_at, deleted_at)
- **post_media**(id, post_id, media_id, position, role) — refs Media context
- **post_audience_custom**(id, post_id, account_id) — for custom audiences
- **post_reaction**(id, post_id, account_id, type) — **unique(post_id, account_id)** (one reaction/user, type updatable)
- **comment**(id, post_id, author_id, parent_comment_id?, body, created_at, deleted_at) — nested replies
- **comment_reaction**(id, comment_id, account_id, type) — unique(comment_id, account_id)
- **share**(id, post_id, account_id, target_post_id?, created_at)
- **mention**(id, post_id?, comment_id?, mentioned_account_id)
- **hashtag**(id, tag[unique citext]) + **post_hashtag**(post_id, hashtag_id)
- **saved_collection**(id, owner_id, name, is_default, created_at)
- **saved_item**(id, owner_id, collection_id, item_type[post/listing/page/video],
  item_id, created_at) — **unique(owner_id, item_type, item_id)**

Indexes: `post(author_id, created_at desc)`; `comment(post_id, created_at)`;
`post_hashtag(hashtag_id)`; partial `post(... ) WHERE deleted_at IS NULL`.
**Partition:** `comment` and `post_reaction` partition candidates at high scale.

### 3.5 feed_db (derived; Redis for hot feeds)
- **feed_item**(recipient_id, post_id, author_id, score, reason, created_at) —
  **partitioned by recipient hash**; PK(recipient_id, post_id)
- **feed_cursor**(recipient_id, last_seen_at) — read position
- **feed_ranking_signal**(post_id, signal_type, value, updated_at)

Hot feeds (first N pages per active user) cached in Redis sorted sets; `feed_db`
is the durable backing store. Rebuildable from Post + Graph events.

### 3.6 media_db
- **media_asset**(id, owner_id, owner_type, kind[image/video/audio/voice/file],
  storage_key, bytes, mime, status[uploading/processing/ready/failed],
  scan_status, created_at, deleted_at)
- **media_variant**(id, media_id, kind[thumb/transcode/waveform/preview],
  storage_key, width?, height?, duration_ms?, bitrate?)
- **upload_session**(id, owner_id, media_id, signed_url_meta, expires_at, completed_at)

Indexes: `media_asset(owner_id, kind)`, `media_asset(status)`.

### 3.7 chat_db
- **conversation**(id, type[dm/group/page/marketplace/support], title?,
  created_by, listing_id?, created_at)
- **conversation_member**(id, conversation_id, account_id, role, joined_at,
  muted_until?, last_read_message_id?) — unique(conversation_id, account_id)
- **message**(id, conversation_id, sender_id, type[text/image/video/file/audio/
  voice/system/share], body, reply_to_id?, created_at, edited_at, deleted_at) —
  **partitioned by month (range on created_at)**
- **message_attachment**(id, message_id, media_id, kind)
- **message_reaction**(id, message_id, account_id, type) — unique(message_id, account_id)
- **message_read_receipt**(message_id, account_id, read_at) — PK(message_id, account_id)
- **message_delivery_receipt**(message_id, account_id, delivered_at)
- **conversation_mute**, **pinned_message**(conversation_id, message_id)

Indexes: `message(conversation_id, created_at desc)`; receipts by composite PK.
Presence & typing live in **Redis**, not Postgres.

### 3.8 notif_db
- **notification**(id, recipient_id, kind, actor_id?, subject_ref, group_key,
  read_at, created_at) — **partitioned by month**
- **notification_preference**(account_id, channel, kind, enabled, quiet_hours)
- **push_device_token**(id, account_id, platform, token[unique], created_at, last_seen)
- **notification_delivery_log**(id, notification_id, channel, status, attempts,
  last_error, created_at) — **partitioned by month**

### 3.9 market_db
- **marketplace_category**(id, parent_id?, slug[unique], name_i18n, position)
- **listing**(id, seller_id, category_id, title, description, price, currency,
  condition[new/like_new/good/fair], location, status[draft/pending_review/
  active/reserved/sold/rejected/archived], created_at, deleted_at)
- **listing_media**(id, listing_id, media_id, position)
- **listing_save**(id, account_id, listing_id) — unique(account_id, listing_id)
- **listing_report**(id, listing_id, reporter_id, reason, created_at)
- **seller_profile**(account_id, rating_avg, rating_count, response_time_ms)
- **listing_conversation_link**(listing_id, conversation_id, buyer_id)

Indexes: `listing(status, category_id, created_at desc)`;
`listing(seller_id)`; GIN on `to_tsvector(title||description)` as DB fallback
when Search is unavailable.

### 3.10 ads_db
- **advertiser_account**(id, owner_account_id, billing_status, created_at)
- **campaign**(id, advertiser_id, name, objective, budget, currency, schedule_start, schedule_end, status)
- **ad_set**(id, campaign_id, targeting_json, placement, frequency_cap)
- **ad_creative**(id, ad_set_id, media_id?, headline, body, cta, review_status)
- **ad_placement**(id, creative_id, surface[feed/marketplace/search/page], weight)
- **ad_review**(id, creative_id, reviewer_id, decision, notes, created_at)
- **ad_impression_event**(id, creative_id, placement, viewer_bucket, occurred_at) — **partitioned by day** (or Kafka→OLAP)
- **ad_click_event**(id, creative_id, placement, viewer_bucket, occurred_at) — **partitioned by day**
- **ad_budget_ledger**(id, advertiser_id, campaign_id, entry_type, amount, currency, balance_after, created_at) — append-only

### 3.11 moderation_db
- **report**(id, reporter_id, target_type, target_id, reason, status, created_at)
- **moderation_case**(id, target_type, target_id, severity, state[open/in_review/
  resolved], assigned_to?, created_at)
- **moderation_action**(id, case_id, moderator_id, action[remove/restrict/warn/
  shadow/dismiss], reason, created_at)
- **appeal**(id, case_id, account_id, text, status, created_at)
- **content_policy**(id, key, version, body, effective_from)
- **moderation_audit_log**(id, case_id, actor_id, action, before, after, created_at) — **partitioned by month**

### 3.12 admin_db
- **feature_flag**(key[unique], enabled, rollout_pct, targeting_json, updated_by, updated_at)
- **system_config**(key, value_json, updated_by, updated_at)
- **service_health_snapshot**(id, service, status, latency_ms, checked_at) — **partitioned by day**
- (User/role/permission management reads other contexts; RBAC roles stored here)

### 3.13 analytics_db
- Write-optimized/append tables and rollups (`metric_daily`, `funnel_event`…),
  fed by the firehose. Leans OLAP; may use partitioning + columnar extensions or
  a separate warehouse later. **Never on a synchronous user path.**

### 3.14 Shared per-DB platform tables (in every writable context)
- **outbox_event**(id[uuidv7], event_type, event_version, payload_json,
  partition_key, correlation_id, created_at, published_at NULL, attempts) —
  index `(published_at) WHERE published_at IS NULL`
- **processed_events**(event_id PK, consumer, processed_at) — consumer idempotency
- **idempotency_record**(key, request_fingerprint, response_snapshot, status,
  created_at, expires_at) — for `Idempotency-Key` HTTP writes
- **audit_log**(id, actor_id, action, target_type, target_id, metadata, created_at) — **partitioned by month**

## 4. Partitioning strategy (high-volume tables)

| Table | Strategy | Retention |
|-------|----------|-----------|
| `message` | range by month | long (configurable retention policy) |
| `notification`, `notification_delivery_log` | range by month | 6–12 months |
| `ad_impression_event`, `ad_click_event` | range by day (or Kafka→OLAP) | raw 30–90d, then rollups |
| `security_event`, `audit_log`, `moderation_audit_log` | range by month | compliance-driven (years) |
| `feed_item` | hash by recipient | rebuildable; short retention |
| `analytics.*` | range by day | rollups long, raw short |

Partitions are auto-managed (pg_partman or a Celery-beat maintenance task):
create-ahead + detach/archive old partitions.

## 5. Integrity & dedupe (DB-enforced, not just app)

- Friendship: `CHECK (account_low_id < account_high_id)` + unique pair → one row
  per relationship regardless of direction; idempotent requests.
- Follow / block / reaction / save: unique composite indexes → duplicate
  actions are no-ops (idempotent), matching the brief's idempotency requirement.
- Listing status transitions enforced in app as an explicit state machine
  (draft→pending_review→active→reserved/sold/rejected/archived) + check on
  illegal jumps.

## 6. Backups, retention, deletion

- Per-database automated backups + PITR (WAL archiving) in prod.
- **Account deletion workflow:** soft-delete → grace period → hard purge job per
  context (driven by `account.deleted` event), with audit trail of the purge.
- **Data export:** per-account export job assembles data across contexts via
  their APIs (GDPR-style portability), produced asynchronously.
- No sensitive data (passwords, tokens, raw message bodies) in logs or broad
  events.
