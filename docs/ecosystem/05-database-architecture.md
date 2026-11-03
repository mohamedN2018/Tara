# Tara database architecture (current + target)

| | |
|---|---|
| Status | Draft for review |
| Date | 2026-11-03 |
| Branch | `feat/web-social-platform` |
| Audience | Tara engineers and the product owner (Mohammed) |
| Scope | All Tara data stores: PostgreSQL (one database per service), Redis, MinIO. Covers today's schema and the target schema after the 10 ecosystem modules: Social, Marketplace, Video, Reels, Messenger, Ads Manager, Professional, User Profiles, Notifications, Administration & Moderation. |

---

## 0. How to read this document

### 0.1 Sources

- **Tara source code** on `feat/web-social-platform`. Read directly while writing this document:
  - `infra/postgres/init/01-create-databases.sh`
  - `docker-compose.dokploy.yml`: backing services, per-service env blocks, worker commands
  - `services/media/media_app/models.py`, `services.py`, `storage.py`, `tasks.py`, `services/media/config/settings.py`
  - `services/post/posts/models.py`, `services/chat/chat/models.py`, `services/ads/ads/models.py`, `services/feed/feed/models.py`, `services/notification/notifications/models.py`
  - every `services/*/config/settings.py` (the `DATABASES` options)
  - every `services/*/*/models.py` (table names) and every `services/*/*/migrations/` folder
  - `libs/tara_events/tara_events/envelope.py` (`uuid7`)
  - `docs/architecture/phase-0/05-data-model-plan.md`
- **Tara area audits:** identity/profile/graph/admin, post/feed/search/moderation, chat/realtime/notification, media/marketplace/ads, frontend/BFF/infra. Each audit read its services' models, services, handlers and tests in full.
- **The 10 module designs and their verifier reviews.** Where a verifier refuted or corrected a design claim, this document uses the corrected version and says so.
- **The QTech audit.** QTech is a read-only reference project. Only patterns are borrowed; no QTech code, schema or data moves into Tara (Appendix A).

### 0.2 Tags

| Tag | Meaning |
|---|---|
| **verified** | Seen in Tara's code, either read directly for this document or reported by the area audits. |
| **plan** | Target state from a module design, after verifier corrections. |
| **decision** | Two module designs disagree, or a verifier proposed two options. This document picks one, and the pick needs sign-off from the lead engineer and product owner (listed in §11). |
| **unverified** | Not confirmed in code. Treat as an assumption until checked. |

### 0.3 Relation to older documents

`docs/architecture/phase-0/05-data-model-plan.md` is the original data plan. Parts of it were never built: monthly partitions, `social_suggestion`, `post_audience_custom`, `comment_reaction`, partitioned `security_event`. This document describes what the code actually contains and what the 10 modules will add. Where the two documents disagree, this one is newer.

**Timing comes from the roadmap.** [04-roadmap.md](04-roadmap.md) fixes the build order. Every migration below is tagged with the roadmap milestone that ships it (for example `[1.5]`), and §7.2 maps milestones to schema changes. Where this document and 04 disagree about timing, 04 wins, and this document should be corrected.

---

## 1. Ground rules

The current code follows these rules (**verified**), and every target change below must keep them.

1. **One database per service.** Each service has its own Postgres database and its own login role, and never reads another service's tables.
2. **No cross-database foreign keys.** A reference to another service's row is a bare `UUIDField` (or `CharField` for polymorphic targets), for example `author_id`, `media_id`, `seller_id`, `recipient_id`, `target_id`. Real foreign keys are used only inside one database.
3. **UUIDv7 primary keys.** They come from `tara_events.envelope.uuid7()`: a 48-bit millisecond Unix timestamp followed by random bits (RFC 9562, verified in `envelope.py`). IDs therefore sort by creation time, which the partitioning plan in §8.2 relies on. A few small child tables in profile (`UserLink`, `UserEducation`, `UserWorkExperience`, `ProfileFieldPrivacy`) use `BigAutoField`.
4. **Cross-service writes go through the transactional outbox.** `record_event(...)` runs inside `transaction.atomic`. Every service sets `ATOMIC_REQUESTS=True` except identity, which uses explicit atomic blocks (verified in all `config/settings.py`). Cross-service reads use `/internal/v1/` endpoints with short-lived HS256 tokens.
5. **Consumers are idempotent.** Each consuming service records handled events in its `processed_event` table, keyed by `(event_id, "<service>:<handler name>")`. Renaming a handler resets its dedupe key. The realtime bridge has no database and is at-least-once.
6. **Migrations are committed per service.** `scripts/test-service.sh` checks them with `makemigrations --check`, and only the web container applies them (`RUN_MIGRATIONS=true`).
7. **Money is `Decimal(19,4)` plus a 3-letter currency.** §8.3 refines how ad spend accrues.
8. **Soft delete uses `deleted_at`.**

---

## 2. Physical layout today (verified)

### 2.1 PostgreSQL

- There is one `postgres:16-alpine` container with `mem_limit 1g`. It holds one logical database and one least-privilege role per service.
- `infra/postgres/init/01-create-databases.sh` creates them with `CREATE DATABASE … OWNER <role>`. Each role owns its database, so a service's own migration can create trusted extensions such as `pg_trgm`.
- The script runs **only once, on an empty data volume**. Adding a database to an existing deployment is a manual step. None of the 10 modules needs a new database (§3), so this limitation does not block the roadmap.
- Every role is created with `CREATEDB`. The script's comment says this is for dev test runs, but it also applies in production. A hardening item: drop `CREATEDB` in production.

| Service | Database | Role | Django app | Migrations today | Redis DB |
|---|---|---|---|---|---|
| identity | `identity_db` | `identity` | `identity` | `0001_initial`, `0002_account_role` | 0 |
| profile | `profile_db` | `profile` | `profiles` | `0001_initial` | 1 |
| graph | `graph_db` | `graph` | `graph` | `0001_initial` | 2 |
| media | `media_db` | `media` | `media_app` | `0001_initial` | 3 |
| post | `post_db` | `post` | `posts` | `0001_initial`, `0002_polls` | 4 |
| feed | `feed_db` | `feed` | `feed` | `0001_initial` | 5 |
| chat | `chat_db` | `chat` | `chat` | `0001_initial` | 6 |
| realtime | none | none | none | none | 7 |
| marketplace | `market_db` | `market` | `marketplace` | `0001_initial`, `0002_security_fixes` | 8 |
| notification | `notif_db` | `notif` | `notifications` | `0001_initial`, `0002_push_subscription` | 9 |
| search | `search_db` | `search` | `searchsvc` | `0001_initial`, `0002_security_fixes` | 10 |
| moderation | `moderation_db` | `moderation` | `moderation` | `0001_initial` | 11 |
| admin | `admin_db` | `adminsvc` | `adminsvc` | `0001_initial`, `0002_remove_role_registry` | 12 |
| ads | `ads_db` | `ads` | `ads` | `0001_initial`, `0002_creative_link` | 13 |
| bff | none | none | none | none | none |

Every service uses `CONN_MAX_AGE=60` and `CONN_HEALTH_CHECKS=True`.

### 2.2 Platform tables in each database

| Service | `outbox_event` | `processed_event` | `idempotency_record` |
|---|---|---|---|
| identity | yes | yes | yes |
| profile | yes | yes | yes |
| graph | yes | yes | yes |
| media | yes | yes | no |
| post | yes | yes | yes |
| feed | yes | yes | no |
| chat | yes | yes | no |
| marketplace | yes | yes | yes |
| notification | yes | yes | no |
| search | no (never publishes) | yes | no |
| moderation | yes | yes | no |
| admin | **no** | **no** | no |
| ads | yes | yes | yes |

- Admin cannot publish or consume events today (`TARA_EVENT_PUBLISHER="null"`, no Celery app). Modules 6 and 10 need both.
- Beat runs `tara_events.publish_outbox` every 2 s and `tara_events.purge_events` hourly (7-day retention, batches of 5000).

### 2.3 Redis

- One `redis:7-alpine` with `--appendonly yes`, a password and `mem_limit 256m`. **No `maxmemory` or eviction policy is set.**
- Each service uses its own DB index (table above); 14 and 15 are free.
- Redis holds caches, DRF throttle counters, ads serve-token spend keys, the realtime presence keys and the Channels layer.
- When the instance reaches its container memory limit it is OOM-killed rather than evicting keys. That drops every service's cache, throttles and WebSocket fan-out at once. Roadmap milestone 1.0h sets `maxmemory 200mb` with `noeviction` (§8.6).

### 2.4 Object storage (MinIO)

- One MinIO container (`cgr.dev/chainguard/minio`, pinned by digest, `mem_limit 512m`) holds one bucket, `tara-media` (the `S3_BUCKET` default).
- Only the media service talks to it, through `services/media/media_app/storage.py`. Media signs URLs with the MinIO root credentials (audit).
- Keys today (verified):
  - original upload: `{kind}/{owner_id}/{asset_id}` (`services.sign_upload`)
  - image thumbnail: `{original_key}/thumb.jpg` (`tasks.py`)
- Presigned PUT and GET URLs live `SIGNED_URL_TTL=900` s. `MAX_UPLOAD_BYTES` is 200 MB for **every** kind.
- `MediaAsset.visibility` defaults to `public`.
- nginx proxies `/tara-media/` to MinIO, so browsers see one origin.

### 2.5 What the data layer does not have yet (verified)

- **No partitioned tables.** `chat.Message` carries the comment "Partitioned by month at scale (doc 05 §4); single table for now".
- **No retention jobs** for `notification`, `notification_delivery_log`, `ad_impression_event`/`ad_click_event`, `service_health_snapshot` or `feed_item`.
- **No Postgres extensions** and **no sequences**.
- **No denormalized relationship counters.** Graph lists and counts are computed by loading full ID lists.
- `media_variant` has **no uniqueness constraint**, and `process_media` uses a get-or-create that is not race-safe.

---

## 3. Target layout at a glance

- **No new database, role or service.** All 10 modules extend the existing 13 databases, following `docs/architecture/project-review-and-plan.md` §5.2. New Django apps are added inside existing services:
  - post gets `stories`, `gatherings`, `videos` and `reels`
  - profile gets `groups` and `careers`
- **New Postgres objects:**
  - `pg_trgm` in `search_db`, `market_db`, `profile_db` and `chat_db`
  - optionally `btree_gin` in `chat_db` (**unverified**: check that it is a trusted extension on the deployed image before relying on it)
  - sequences `marketplace_order_number_seq` (`market_db`) and `ads_statement_seq` (`ads_db`)
  - PostGIS is **not** used; it is not in `postgres:16-alpine`. Geo search in marketplace uses a rounded lat/lng bounding box.
- **Redis:** a second instance, `redis-hot`, for high-churn data, created in roadmap milestone 1.7 (§8.6).
- **New processes that hold DB connections:** `admin-worker`, `admin-consumer`, `identity-consumer`, `ads-consumer`, `media-consumer`, `media-video-worker` (one shared ffmpeg worker for Video and Reels, **decision**; the roadmap calls this container `media-transcoder`) and `profile-activity-consumer`. The connection impact is in §8.7.
- **New containers without a database:** `media-scanner` (clamd, roadmap 3.10; the `media.scan` task that calls it runs in the media worker) and `livekit`.

| Module | Main databases | What it adds to the data layer |
|---|---|---|
| 1 Social | post, feed, graph, profile, search, media | comments v2, comment reactions, reaction counts, stories, gatherings (events), trending, groups (in profile), ranking tables (in feed), suggestions and close friends (in graph) |
| 2 Marketplace | market (+ search, moderation, chat, notification) | sellers (individual or business), cities, typed attributes, inquiries, daily stats, reviews, orders |
| 3 Video | post (`videos` app), media, feed, search | videos, categories, playlists, watch history, HLS variants |
| 4 Reels | post (`reels` app), media, feed | reels, sounds, telemetry, candidate pools, interest signals |
| 5 Messenger | chat (+ notification, media) | per-conversation sequence, inbox state, edits, hides, reports, settings, calls |
| 6 Ads Manager | ads | business ad accounts, prepaid funding ledger, daily spend, stats, reach, conversions, audit |
| 7 Professional | profile (`careers` app) | skills, certifications, CVs, company profiles, jobs, applications, interviews |
| 8 User Profiles | profile, graph, post | handle registry, activity log, connection privacy, counters, media tab denormalization |
| 9 Notifications | notif | aggregation, actor table, deferred push, digests |
| 10 Admin & Moderation | identity, moderation, admin (+ profile, post, market, search, media) | restrictions, capabilities, triage, evidence snapshots, blocklists, unified audit, daily metrics |

---

## 4. Per-service schema: current and target

Each subsection lists the **current** tables (verified), the **target** additions (plan, after verifier corrections), the references that point outside the service, and notes. Choices inside table cells are separated with `/`.

### 4.1 identity (`identity_db`)

**Current (verified)**

- **`account`** (custom `AbstractBaseUser`): UUIDv7, `email` (unique, the `USERNAME_FIELD`), `email_verified`, `status` active / pending / suspended / deactivated / deleted, `language`, `theme`, `is_staff`, `is_active`, `last_login_at`, `deleted_at`.
- **`account_role`**: `account`, `role` admin / moderator / ad_reviewer / analyst, `granted_by`; unique (account, role).
- **Sessions and tokens:**
  - `device`
  - `user_session`: coarse `ip_region` only, no raw IP; `user_agent`; `revoked_at`
  - `refresh_token`: sha256 `token_hash` (unique), `family_id`, `rotated_from`, `used_at`, `revoked_at`
  - `email_verification` and `password_reset`: hashed tokens with expiry
- **`security_event`** (append-only).
- **`two_factor_secret`**: a scaffold with no endpoints.
- Platform tables.

Nothing sets status DEACTIVATED or DELETED, and nothing sets `deleted_at`. Identity has no event consumer.

**Target**

| Model | Change | Key fields | Indexes / constraints | Module |
|---|---|---|---|---|
| `AccountRestriction` | new | account FK, `kind` suspension / feature, `features` JSON, `reason_code`, `note`, `case_id`, `source` admin / moderation / system, `actor_id`, `previous_status`, `starts_at`, `ends_at` (null means permanent), `lifted_at`, `lifted_by`, `lift_reason` | `(account, lifted_at, ends_at)`; partial `(ends_at) WHERE lifted_at IS NULL`; partial unique one active suspension per account | 10 |
| `RoleCapabilityOverride` | new | `role`, `capability` (checked against the `tara_common.capabilities` registry), `granted`, `updated_by` | unique (role, capability) | 10 |
| `AccountCapabilityOverride` | new | account FK, `capability`, `granted`, `granted_by`, `reason`, `expires_at` | unique (account, capability); index `expires_at` | 10 |
| `account` | indexes only | none | `Lower(email)` with `varchar_pattern_ops` (staff prefix search); `(-created_at, id)`; built CONCURRENTLY | 10 |
| `security_event` | index only | none | `(type, created_at)`, CONCURRENTLY | 10 |
| `account` age data | add (roadmap 2.12) | Optional `birth_date`, or an age attestation plus `age_band`, kept inside identity | none | needed by 4, 5, 6, 10 |
| `account_role` | choices only (roadmap 6.3) | role gains `finance` (top-up verification with separation of duties) | none (an `AlterField`; no table rewrite) | 6 |

- **How age leaves identity (decision, aligned with roadmap 2.12):** only as access-token claims, `is_minor` and `age_band` (`unknown` for accounts created before 2.12). There is **no** age event. Every age decision in the plan happens inside a request: reels personalisation in feed, ad matching in ads (feed forwards the claims in its internal slot call), marketplace seller attestation and careers. A birthday that crosses 18 takes effect at the next token refresh. If a later feature needs age outside a request, it adds an internal identity read, not an event.
- **Events:**
  - Module 10 adds `account.suspended`, `account.reinstated`, `account.restricted`, `account.restriction.lifted`, `account.role_changed` and `account.capabilities_changed` through the outbox.
  - Several modules depend on `account.deleted`, `account.deactivated` and `account.updated` (language or email change). They are now planned in roadmap L.5 (account deletion and erasure), with an erasure consumer in every service.
- **Write path for suspensions (verifier correction, aligned with roadmap 8.4):** a suspension from a moderation case cannot happen "inside the case transaction". Moderation runs with `ATOMIC_REQUESTS=True`, and any remote call inside that transaction can split the outcome (identity suspends and moderation rolls back, or the reverse). The rule is the same in both documents. Moderation's view runs `non_atomic_requests`, pre-generates the action id, and calls identity's internal suspend endpoint **first**, with an idempotency key derived from the case id and that action id. Identity applies the suspension (with the hierarchy guard) once per key, and revokes sessions and refresh tokens in its own transaction. Moderation then commits the action, the case resolution and an outbox row together. A reconcile job compares identity's active suspensions with resolved cases and repairs either side. An async `moderation.actioned` consumer alone is not enough. `identity-consumer` remains for `system_config.changed`.
- **Django admin:** in `identity/admin.py`, `AccountAdmin` can edit `status`, `is_staff` and `is_superuser`. That bypasses `AccountRestriction`, session revocation and the audit trail. Make those fields read-only, or route saves through the services layer. In production Django admin is reachable only from a shell, because nginx does not route `/admin`.
- **Partition candidate:** `security_event` (§8.2).

### 4.2 profile (`profile_db`)

**Current (verified)**

- **`user_profile`**: `account_id` (unique), `handle` (unique, lowercase), `display_name` (80), `bio` (300), `intro` (TextField with no length cap), `city`, `country`, `avatar_media_id`, `cover_media_id`, `visibility` public / friends_only / private / custom, `completion_pct`, `deleted_at`.
- **`profile_field_privacy`**: 7 keys.
- **`user_link`, `user_education`, `user_work_experience`**: `BigAutoField` keys and no `created_at`.
- **`page`**: `owner_account_id`, `handle` (unique), `name`, `category`, `description`, avatar and cover media ids, `contact` (JSON, unvalidated), `location`, `status` draft / published / suspended, `deleted_at`.
- **`page_member`**: roles owner / admin / editor / moderator / advertiser / analyst, `invited_by`.
- **`blocked_pair`** read-model and the platform tables.

Defects that touch the schema (verified by the audit):

- The list `GET /profile/me/links|education|work/` raises `FieldError`. The default cursor paginator falls back to ordering by `-created_at`, a column these tables do not have.
- `display_name` is 80 characters in profile but 120 at identity registration. An 81 to 120 character name raises `DataError` in `ensure_profile`, the `account.registered` event dead-letters, and the account never gets a profile.

**Target: `profiles` app**

| Model | Change | Key fields | Indexes / constraints | Module |
|---|---|---|---|---|
| `UserProfile` | add | `headline` (220), `website` (URL 300), `profile_type` personal / creator, `creator_category`, `open_to_work`, `searchable` (default true; covers in-app search, suggestions and explore), `allow_link_previews` (default false), `mentions_from` everyone / friends / nobody, `country_code` (ISO-2; the free-text `country` stays for display), `handle_changed_at`, `suspended_at`, `deactivated_at`, `moderation_hidden_fields` JSON, `moderated_at` | none new; set `default_manager_name` and `base_manager_name` to `all_objects` with an active-only `objects` manager | 1, 7, 8, 10 (**decision**: union of fields, see §5) |
| `UserLink` | add | `platform`, `created_at`, `position` | max 10 per profile (service rule) | 8 |
| `UserWorkExperience` | add | `page` FK (SET_NULL), `employment_type`, `location`, `description` (≤ 2000), `position`, `verification_status` none / pending / verified / rejected, `verified_by`, `verified_at`, `created_at`, `updated_at` | `(page, is_current)`, `(page, verification_status)` | 7, 8 |
| `UserEducation` | add | `school_page` FK (SET_NULL), `grade`, `description`, `position`, `created_at`, `updated_at` | none | 7, 8 |
| `Skill` | new (catalog) | `name` (display), `normalized_name` | unique `normalized_name`; `varchar_pattern_ops` index for prefix autocomplete | 7 |
| `ProfileSkill` | new | profile FK, skill FK (PROTECT), `position`, `endorsement_count` | unique (profile, skill); max 50 per profile | 7 |
| `SkillEndorsement` | new | profile_skill FK, `endorser_account_id` | unique (profile_skill, endorser); index endorser | 7 |
| `Certification` | new | `name`, `issuer_name`, `issuer_page` FK, `issued_on`, `expires_on`, `credential_id`, `credential_url` (https only), `media_id`, `position` | check `expires_on ≥ issued_on`; max 30 | 7, 8 (merged) |
| `Resume` | new | profile FK, `media_id` (unique), `filename`, `bytes`, `is_default`, `deleted_at` | partial unique: one default per profile; max 3 active | 7 |
| `ProfessionalPreference` | new | one-to-one profile; desired titles, workplace types, employment types, locations (JSON, capped) | PK only | 7 |
| `HandleRegistry` | new | `handle` (PK, lowercase), `owner_type` user / page, `owner_id`, `reserved_until` | check `handle = lower(handle)`; index `(owner_type, owner_id)` | 8 |
| `HandleHistory` | new | `owner_type`, `owner_id`, `old_handle`, `new_handle`, `changed_at`, `redirect_until` | `(old_handle, -changed_at)` | 8 |
| `ActivityEntry` | new | uuid7, `account_id`, `category`, `verb`, `subject_type`, `subject_id`, `post_id`, `context` JSON (ids and enums only), `source_event_id`, `occurred_at`, `hidden_at` | unique (source_event_id, account_id); `(account_id, -occurred_at)`; `(account_id, category, -occurred_at)`; `(subject_type, subject_id)`; `(post_id)`; BRIN on `occurred_at` for the purge | 8 |
| `Page` | add | `status_reason`, `status_changed_at`, `status_changed_by` | `(owner_account_id, status)`, `(status, -created_at)`, CONCURRENTLY | 10 (8's `suspended_*` fields folded in) |
| `PageMember` | add | role `recruiter`; invitation `state` pending / active (a role takes effect only after the invitee accepts) | index `(account_id)` | 7, 8 |
| `CompanyProfile` | new | one-to-one Page; `industry`, `company_size`, `founded_year`, `website`, `hq_country`, `hq_city`, `specialties`, `verified_at`, `verified_by` | `verified_at` | 7 |

Verifier corrections applied in this table:

- **Employment verification** can only be decided by owners or admins of a page whose `CompanyProfile.verified_at` is set, and the decider cannot be the requester. Without this, anyone can create a page and self-verify their own job.
- **Skill normalization** keeps `+ # . / -`, so `C`, `C#` and `C++` stay distinct. It is not the QTech chatbot normalizer as-is.
- **Every handle claim** goes through one helper that inserts the `HandleRegistry` row inside the caller's transaction, whether the claim comes from `ensure_profile`, `create_page` or the change endpoint. New default handles stop being derived from the email local-part.
- **`ActivityEntry`** gets its own consumer queue (`profile.activity`), so reaction bursts cannot delay `user.blocked` or `account.registered`.
- **Not added to profile:** list visibility and `friend_request_policy` move to graph (§4.3). `Page.follower_count` and a `PageFollower` read-model are dropped in favor of graph counters (**decision**, §5).

**Target: `groups` app (Module 1, `profile_db`)**

| Model | Key fields | Indexes / constraints |
|---|---|---|
| `Group` | uuid7, `handle` (unique, lowercase, own namespace, shared reserved-word list), `name`, `description`, avatar and cover media ids, `privacy` public / private / secret, `join_policy` open / approval / invite_only, `post_approval`, `rules` JSON (≤ 10), `member_count`, `status` active / suspended / deleted, `created_by`, `deleted_at` | `(privacy, status)` |
| `GroupMember` | uuid7, group FK, `account_id`, `role` owner / admin / moderator / member, `status` active / pending / invited / banned, `invited_by`, `joined_at` | unique (group, account); `(account_id, status)`; `(group, status, role)` |

**Target: `careers` app (Module 7, `profile_db`; first migration creates `pg_trgm`)**

| Model | Key fields | Indexes / constraints |
|---|---|---|
| `JobPosting` | page FK (PROTECT), `posted_by`, `title`, `description` (plain text ≤ 10 000), employment / workplace / seniority types, `country`, `city`, salary range + currency + period, `show_salary`, `status` draft / open / paused / closed / removed, `close_reason`, `published_at`, `expires_at` (≤ 60 days), `application_count`, `search_text` | `(status, -published_at)`, `(page, status)`, `(country, city)`, GIN trigram on `search_text`; check salary_min ≤ salary_max |
| `JobSkill`, `JobQuestion` | job FK, skill FK; prompt, kind, required, position | unique (job, skill); ≤ 10 skills, ≤ 5 questions |
| `JobApplication` | job FK (PROTECT), `applicant_account_id`, `resume` FK, `resume_media_id` (frozen at apply time), `cover_letter`, contact fields, `answers` JSON, `profile_share_consent`, `consented_at`, `consent_version`, `shared_field_keys`, `stage` (8 values), `viewed_at`, `stage_changed_at`, `anonymized_at` | unique (job, applicant); `(job, stage, -created_at)`; `(applicant, -created_at)` |
| `ApplicationEvent`, `ApplicationNote` | stage history and CV-access log; recruiter-only notes | `(application, -created_at)` |
| `Interview`, `InterviewPanelist`, `InterviewFeedback` | UTC `scheduled_at` plus an IANA `timezone`; https-only meeting URL; feedback rating 1 to 5 | partial `(status, scheduled_at)`; unique (interview, panelist); check rating 1 to 5 |
| `SavedJob`, `JobAlert` | per-account saves; up to 5 alerts | unique (account, job); `(frequency, last_sent_at)` |

Careers retention (verifier correction):

- Withdrawing an application immediately clears `resume_media_id` and the contact fields. Previously they stayed until anonymization.
- Applications are anonymized 365 days after their job closes, and withdrawn ones after 30 days.

**References out of profile**

| Field | Points to | How it is checked |
|---|---|---|
| avatar / cover / certificate / resume / logo media ids | media `MediaAsset` | media `/internal/v1/media/<id>/`: owner, kind, status, visibility |
| `account_id`, `owner_account_id`, `applicant_account_id`, `endorser_account_id` | identity `account` | `account.registered`; no deletion signal exists yet |

**New events:** `page.updated`, `page.status.changed`, `profile.deleted`, `profile.photo.changed`, `group.*`, `job.*`, `skill.endorsed`, `employment.verification.*`. The `profile.updated` payload carries non-public fields only inside `public_fields`, and only when that field's privacy is public.

### 4.3 graph (`graph_db`)

**Current (verified)**

- **`account_ref`**: `account_id`, `handle`. It is populated from events but never read.
- **`friendship`**: `account_low_id` < `account_high_id` enforced by a check constraint, unique pair, `status` pending / accepted, `requested_by`, `accepted_at`.
- **`follow_relation`**: `follower_id`, `target_id`, `target_type` user / page; unique.
- **`block_relation`**: unique pair.
- **`close_friend_relation`**: model only, no API.
- Platform tables.

All list endpoints are unpaginated. Follows to pages are never validated. `block()` deletes edges without emitting `friendship.removed`.

**Target**

| Model | Change | Key fields | Indexes / constraints | Module |
|---|---|---|---|---|
| `ConnectionPrivacy` | new (**decision**) | `account_id` PK, `friends_list_visibility`, `followers_list_visibility`, `following_list_visibility` (public / friends_only / private), `friend_request_policy` (everyone / friends_of_friends / nobody), `updated_at` | PK | 1, 8 (verifiers moved this from profile into graph) |
| `AccountRef` | add | `searchable`, `is_active`, `last_event_at` | PK | 1, 8 |
| `AccountCounter` | new | uuid7, `subject_id`, `subject_type` user / page, `friends_count`, `followers_count`, `following_count`, `updated_at` | unique (subject_id, subject_type) | 8 (also serves Module 7 page follower counts) |
| `PageRef` | new read-model | `page_id` PK, `owner_account_id`, `status`, `last_event_at` | PK | 7, 8 (verifiers) |
| `SuggestionDismissal` | new | `account_id`, `candidate_id` | unique pair | 1 |
| `friendship` | indexes | none | partial `(account_low_id, accepted_at)` and `(account_high_id, accepted_at)` WHERE status = 'accepted', CONCURRENTLY | 8 (the proposed `(account_low_id, status)` index is redundant with the pair-unique index) |
| `follow_relation` | indexes | none | `(follower_id, target_type, -created_at)`, `(target_id, target_type, -created_at)`, CONCURRENTLY | 8 |

- Counters are updated with `F()` in the same transaction as each edge change: accept, unfriend, follow, unfollow and **block**. A `rebuild_counters` command repairs drift.
- `ConnectionPrivacy` lives in graph so enforcement is immediate. When it was a copy of profile data delivered by event, a delayed or reordered `profile.updated` could leave a stricter setting unenforced.
- Graph needs new internal endpoints:
  - batch relationships, `POST /internal/v1/relationships/batch` with ≤ 100 ids
  - a paginated fan-out
  - a paginated follower list for page targets
  
  Each is required to keep post, feed and profile list visibility affordable.

### 4.4 media (`media_db`)

**Current (verified directly in `media_app/models.py`)**

- **`media_asset`**:
  - `id`, `owner_id`, `kind` image / video / audio / voice / file, `storage_key` (300), `bytes`, `mime`
  - `status` uploading / processing / ready / failed
  - `scan_status` (default "pending"; set to "clean" without any scan)
  - `visibility` public / private (default **public**)
  - `error`, `created_at`, `updated_at`, `deleted_at`
  - index `(owner_id, kind)`
- **`media_variant`**: `kind` thumb / transcode / waveform / preview, `storage_key`, `width`, `height`, `duration_ms`, `bitrate`. No unique constraint. Only `thumb` rows are written, and they are always saved as 320×320.
- **`upload_session`**: `expires_at` (ignored by `complete_upload`), `completed_at`.
- Outbox and processed tables.

`bytes` holds the size the client **declared** at sign time. `complete_upload` checks the real object only against the 200 MB cap and never stores the real size (verifier).

**Target (merged from Modules 3, 4, 5, 7, 8 and 10, with verifier corrections)**

| Model | Change | Key fields | Indexes / constraints |
|---|---|---|---|
| `MediaAsset` | add | `purpose` (post / story / group_post / avatar / cover / chat / voice / reel / reel_render / video / sound / caption / listing / cv / receipt / certificate / thumbnail) [1.5], `staging_key` [1.5], `etag` (binds processing to the object that passed verification) [1.5], `probe` JSON (sanitized: container, codecs, duration, size, rotation, fps, has_audio), `duration_ms`, `width`, `height`, `progress`, `error_code`, `processing_started_at`, `processing_finished_at`, `original_name` (sanitized) [5.2], `moderation_hold_at` [5.3], `legal_hold_until` [8.2]; `scan_status` gains real states pending / clean / infected / error [3.10]; kind gains `caption`. `bytes` is overwritten with the real stored size at complete [1.5]. | partial `(status, created_at) WHERE status = 'uploading'` for the abandoned-upload reaper; `(purpose, status, created_at)` |
| `MediaVariant` | add | `label` (for example `720p`, `1-640`, `master`), `mime`, `position`; kinds gain `poster`, `audio`, `hls` | unique (media, kind, label), added after a dedupe of duplicate (media, kind) rows |
| `VideoJob` | new | media FK, `job_type` probe / transcode / render / caption, `params` JSON, `params_hash`, `status`, `attempts` (FAILED after 3), `error`, timestamps | unique (media, job_type, params_hash); `(status, created_at)` |
| `UploadSession` | add | `s3_upload_id`, `part_count` (multipart uploads, later milestone) | none |

- **Behavior changes that are not schema:**
  - per-kind size caps (`file` 5 MB for CVs; images about 15 MB; reels 150 MB)
  - real-size accounting [1.5]
  - EXIF/GPS stripping of **every** image before READY [1.5]
  - container signature checks for video and audio (`ftyp`, EBML, `OggS`), and uploads to a staging key that `complete` copies to the final key, so a reused presigned PUT cannot change a verified object [1.5]
  - PDF active-content rejection (`/JavaScript`, `/Launch`, `/EmbeddedFile` and similar)
  - clamd scanning with quarantine for `file` kind, receipts, creatives and CVs [3.10]
  - one-off `privatize_post_media` [1.5] and `privatize_chat_media` [3.2]
  - **private by default for all media attached to content** (post images, story media, group posts, chat, voice, listings, CVs, receipts, custom thumbnails and video/reel originals). The owning service mints URLs after its own visibility check [1.5, 3.2, 4.2, 5.2]. Only account and page avatars and covers, public-group images and sounds stay public. Before roadmap 1.5 every SPA upload is public and `_can_view` lets any signed-in user fetch it, so this list closes a live leak; it is not just a target.
- **Events:**
  - `media.processed` and `media.failed` gain `purpose`, `probe`, the variant list and, for failures, `error_code`.
  - New: `media.deleted`, so dependents can mark creatives or attachments unavailable.
  - Media gains a consumer (`media-consumer`) for `video.deleted` and `post.deleted`, and for moderation holds and releases.
- **Revocation (verifier blocker for Video and Reels):** when content is removed, media must block delivery, so HLS playlists and presigned URLs stop working within minutes instead of after a 6-hour token. `moderation_hold_at` plus a short presign window implements this.

### 4.5 post (`post_db`)

**Current (verified)**

- **`post`**:
  - `author_id`, `author_type` user / page
  - `type` text / image / video / link / share / poll
  - `body`, `audience` **`CharField(max_length=12)`** public / friends / followers / only_me
  - `shared_post_id`, `link_preview` JSON
  - `moderation_status` ok / pending / removed (pending is never set)
  - reaction, comment and share counters, `deleted_at`
  - index `(author_id, created_at)`
- **Polls:** `poll`, `poll_option`, `poll_vote`.
- **Engagement:** `post_media`, `post_reaction` (unique post + account), `comment` (`parent` self-FK; `deleted_at` is never written), `share`.
- **Tagging:** `hashtag`, `post_hashtag`, `mention` (stores `mentioned_handle` as text).
- **Saves and reports:** `saved_collection`, `saved_item`, `post_report`.
- `blocked_pair` and the platform tables.

**Target: `posts` app**

| Model | Change | Key fields | Indexes / constraints | Module |
|---|---|---|---|---|
| `Post` | alter and add | `audience` widened to `max_length=16` (`close_friends` is 13 characters; widening a varchar is metadata-only), values + `close_friends`, `group`; `type` + `reel`, `gathering`; `group_id`, `gathering_id`, `comment_policy` everyone / friends / off; `publish_state` draft / processing / published / failed (`db_default` 'published') and `published_at`; `origin` '' / profile_avatar / profile_cover; `source_event_id` (unique when set) | partial `(group_id, -created_at)`, `(gathering_id, -created_at)`, `(author_id, -created_at) WHERE type = 'reel'`; trending scan partial `(created_at) WHERE audience = 'public' AND deleted_at IS NULL AND moderation_status = 'ok'`; all CONCURRENTLY | 1, 3, 4, 8 |
| `PostMedia` | add (denormalized) | `kind`, `author_id`, `post_created_at`, `audience` | `(author_id, kind, -post_created_at)` | 8 |
| `PostReaction` | index | none | `(account_id, -created_at)`, CONCURRENTLY (for liked-videos lists and the activity log) | 3 |
| `PostReactionCount` | new | post FK, `type`, `count` | unique (post, type) | 1 |
| `Comment` | add | `reply_to_id` (parent stays the thread root), `edited_at`, `reaction_count`, `moderation_status` ok / pending / removed | `(post, moderation_status, created_at)`; `(parent, created_at)` | 1, 10 |
| `CommentReaction` | new | comment FK, `account_id`, `type` | unique (comment, account) | 1 |
| `Share` | index | none | `(post_id, created_at)` | 3 |
| `Hashtag` | add | `norm` (Arabic-normalized; queried and counted by norm) | index `norm` | 1 |
| `HashtagBlock`, `TrendingSnapshot` | new | moderator blocklist; trending rows per language every 10 min (keep the last 48) | `(lang, -computed_at)` | 1 |
| `GroupRef`, `GroupMembership` | new read-models | group privacy, post-approval flag and status; member role and status, plus short-TTL negative rows | unique (group, account); `(account, status)` | 1 |
| `AuthorState` | new read-model (**decision**: merges Module 8's `AuthorPrivacy` and Module 10's `HiddenAuthor`) | `account_id` PK, `profile_visibility`, `suspended`, `searchable`, `last_event_at` | PK | 8, 10 |
| `PageMemberRef` | new read-model | `page_id`, `account_id`, `role`, `last_event_at` (tombstone rows on removal) | unique pair | 7 (verifier: check post-as-page locally instead of calling profile synchronously) |

- **Group posts (verifier blocker):** when `group_id` or `gathering_id` is set, the server forces `audience` to `group`. Search, trending, explore and link previews must treat these posts as non-public unless the group itself is public.
- **Save normalization:** saving a video from a feed card and from the watch page must create one `SavedItem` row, not one per item type. A data migration merges existing duplicates.

**Target: new apps in `post_db`**

| App | Model | Key fields | Indexes / constraints |
|---|---|---|---|
| `stories` | `Story` | author, kind image / video / text, media_id, styled text, audience, `expires_at`, counts, `moderation_status`, `deleted_at` | `(author_id, -created_at)`, `(expires_at)` |
| | `StoryView` | story FK, `viewer_id`, `viewed_at` (kept 30 days) | unique (story, viewer); `(viewer_id, viewed_at)`; partition candidate |
| | `StoryReaction` | story FK, account, type | unique (story, account) |
| `gatherings` (renamed from Module 1's `events` app, which clashed with every service's `events.py` emit module and the event-bus vocabulary) | `Gathering` | host type user / page / group, host_id, title, description, cover media, `starts_at`, `ends_at`, IANA `timezone`, online / location fields, `visibility`, `group_id`, `capacity`, going / interested counts, `status`, `moderation_status` | `(starts_at)`, `(host_id, starts_at)`, partial `(group_id, starts_at)` |
| | `GatheringRSVP`, `GatheringInvite`, `GatheringReminderLog` | RSVP status; invites (friends only); reminder sent per kind | unique (gathering, account); unique (gathering, invitee); unique (gathering, kind) |
| `videos` | `VideoCategory` | slug, ar / en names, position | unique slug |
| | `Video` | uuid7 (equal to the Post id at publish), `author_id`, `media_id`, title, description, category FK, tags + `tags_norm` (array, GIN), `language`, `comments_enabled`, `status`, `publish_when_ready`, `publish_at`, duration and size, thumbnail choice, `view_count`, `watch_time_ms`, `trending_score`. Audience, deletion and moderation state are read from the linked `Post`, which is the single authority (verifier). | **unconditional** unique `media_id`, so a purge can never delete files another row uses (verifier); `(author_id, status, -published_at)`; partial trending and recent indexes on public published rows |
| | `Playlist`, `PlaylistItem` | owner, kind normal / watch_later, visibility public / private, `item_count`; items with gapped positions (≤ 5000 per playlist) | partial unique one watch_later per owner; unique (playlist, video); `(playlist, position, id)` |
| | `VideoWatch`, `WatchHistorySetting` | last position, watched ms, completed flag; history pause flag | unique (account, video); `(account, -last_watched_at, -id)` |
| `reels` | `Reel` | `post` one-to-one PK, `author_id` and `audience` (denormalized; verifier), `media_id`, `playback_media_id`, duration and size, cover fields, sound FK + offsets and volumes, caption track, `allow_comments`, `allow_sound_reuse` (**decision**: default false for v1, per verifier), `view_count`, `published_at` | unique `media_id`; `(author_id, -published_at) WHERE published_at IS NOT NULL`; `(sound, -published_at)` |
| | `Sound` | kind original / library, title, artist, owner, `origin_post_id`, `audio_media_id` (its **own** purpose=sound asset, copied out of the origin reel so a reel purge cannot break it; verifier), `status`, `license` JSON, `use_count` | `(status, -use_count)`; partial unique `origin_post_id` WHERE kind = 'original' |
| | `ReelShare` | post FK, account, channel link / native / dm, `shared_on` | unique (post, account, channel, shared_on) |

- **Video and reel publishing (decision):** both use `Post.publish_state` and `Post.published_at` as the single visibility gate. `post.created` for a video or reel carries `published_at`, not `created_at`, so a slow transcode does not backdate the item in followers' feeds (verifier).
- **Extension:** none needed in `post_db`. Hashtag norms use a plain index.

### 4.6 feed (`feed_db`)

**Current (verified)**

- **`feed_item`**: uuid7, `recipient_id`, `post_id`, `author_id`, `score` (always 0.0), `reason` self / follow, `snapshot` JSON, `post_created_at`; unique `(recipient_id, post_id)`; index `(recipient_id, -post_created_at)`.
- Outbox and processed tables.
- No retention.

**Target**

| Model | Change | Key fields | Indexes / constraints | Module |
|---|---|---|---|---|
| `FeedItem` | add | `reason` self / friend / follow / page / group; `source_type`, `source_id` | expression index `(recipient_id, (snapshot->>'type'), -post_created_at)` instead of a new `post_type` column and a full-table backfill (**decision**, verifier option) | 1, 3 |
| `PostStat` | new | per-post engagement counters, `velocity`, `is_candidate`, snapshot | `(is_candidate, -velocity)`, `(created_at)` | 1 |
| `Affinity` | new | viewer → author score (decayed on read) | unique pair; `(viewer, -score)` | 1 |
| `FeedHide`, `AuthorSnooze`, `BlockedPair` | new | user feedback and block read-model | unique pairs | 1 |
| `StoryTrayEntry` | new | recipient, author, latest story, `expires_at` | unique (recipient, author); `(recipient, -latest_story_at)`; `(expires_at)` | 1 |
| `FollowEdge` | new read-model | follower, target, `created_at`, `removed_at` (tombstone), `last_event_at` | unique pair; `(follower)`, `(target)` | 4 |
| `ReelCandidate`, `ReelCandidateTag` | new | candidate pool with counters, score, state (tombstoned, never hard-deleted), `last_event_at` | `(state, -score)`, `(state, -published_at)`, `(sound_id, -published_at)`; unique (post, tag) and `(tag, -published_at)` | 4 |
| `ViewerInterest`, `ReelNegative` | new | interest weights; "not interested" | unique (viewer, key); unique (viewer, kind, target) | 4 |
| `ReelViewDay` | new (verifier) | `viewer_id`, `post_id`, `day`. View qualification is checked in SQL with `INSERT … ON CONFLICT DO NOTHING` instead of a Redis `SET NX`. | unique (viewer, post, day); partition candidate | 4 |
| `ReelEngagement` | new (verifier) | viewer, post, kind like / save / repost / share. Only the first per viewer counts toward ranking; an undo decrements. | unique triple | 4 |
| `AuthorEligibility` | new (verifier) | author visibility and restrict/shadow state, fed by `profile.updated` and `moderation.actioned` | PK author | 4, 10 |
| `ReelStatsDaily`, `CreatorStatsDaily` | new | daily counters as **one integer column per source and per retention bucket**, not JSON (F() cannot increment JSON keys; verifier) | unique (post, day) / (author, day) | 4 |
| `IngestCursor` | new (verifier) | consumer name, last applied stream id, updated inside the same transaction as the counter upserts | PK | 4 |
| `VideoStatDaily`, `VideoCreatorStatDaily` | new (**decision**: video stats live here next to reel stats, not in post) | views, unique viewers, watch time, retention buckets, sources, device class (k ≥ 10 suppression in the API) | unique (video, day) | 3 |

- **Privacy (verifier):** for non-public and explore items, `GET /feed/` returns ids only, and clients hydrate through `POST /posts/batch/`. Otherwise a stale snapshot would still show a revoked viewer the excerpt.
- **Retention:** at most 1000 items or 30 days per recipient; `PostStat` rows older than 14 days are dropped; `Affinity` below 0.05 is pruned after 60 days.

### 4.7 chat (`chat_db`)

**Current (verified directly in `chat/models.py` and by the audit)**

- **`conversation`**: type dm / group / page / marketplace / support, `title`, `created_by`, `listing_id`, `dm_key` (unique), `last_message_at`.
- **`conversation_member`**: role, `muted_until`, `last_read_message_id`, `left_at`, `joined_at`; unique (conversation, account); index `account_id`.
- **`message`**:
  - uuid7, conversation FK, `sender_id`
  - `type` text / image / video / file / audio / voice / system / share
  - `body`, `reply_to` self-FK, `created_at`, `edited_at`, `deleted_at`
  - index `(conversation, -created_at)`
- **`message_attachment`**: `media_id`, `kind` (free text), `duration_ms`.
- **`message_reaction`**: unique (message, account).
- **`pinned_message`**, **`blocked_pair`** and the platform tables.

**Target (Module 5, with verifier corrections)**

| Model | Change | Key fields | Indexes / constraints |
|---|---|---|---|
| `Conversation` | add | `last_seq` (bigint), `seq_ready` (per-conversation backfill marker, §7.3), `last_message_id`, `last_message_sender_id`, `last_message_type`, `last_message_preview` (140; wiped on delete-for-everyone) | none new |
| `ConversationMember` | add | `archived_at`, `pinned_at` (≤ 5 per account), `cleared_at`, `visible_from` (history start for members added later), `request_state` accepted / pending / declined, `last_read_seq`, `last_delivered_seq`, `last_read_at` | `(account_id, archived_at, request_state)`; partial `(account_id) WHERE pinned_at IS NOT NULL` |
| `Message` | add | `seq` (per conversation), `deleted_by`, `moderation_removed_at` (kept separate from the user's own delete, so moderation can reverse it), `forwarded_from_message_id` (never serialized), `meta` JSON (server-only system payloads), `body_norm` | unique (conversation, seq); GIN trigram on `body_norm`, or `btree_gin` composite `(conversation_id, body_norm)` (**decision**, §11) |
| `MessageAttachment` | add | `mime`, `bytes`, `file_name`, `width`, `height`, `position` (≤ 10 per message) | `(media_id)` |
| `MessageEdit` | new | previous body, editor, time. Purged after 90 days; deleted on delete-for-everyone unless the message is reported. | `(message, -edited_at)` |
| `MessageHidden` | new | delete-for-me | unique (message, account) |
| `MessageReport` | new | reason, note, snapshot of the message and up to 5 earlier messages the reporter could see; retention 180 days after the case closes | unique (message, reporter) |
| `MessengerSettings` | new | `show_presence`, `send_read_receipts`, `message_requests` | PK account |
| `ParticipantProfile` | new read-model | handle, display name, `name_norm`, avatar | trigram on `name_norm` |
| `FriendPair` | new read-model (verifier) | fed by `friendship.accepted` and `friendship.removed`; decides message requests locally instead of calling graph synchronously | unique pair |
| `Call`, `CallParticipant`, `CallWebhookEvent` | new | server-generated room name, kind, state, end status, durations; per-participant state; LiveKit webhook event ids (purged after 7 days) | partial unique one live call per conversation; `(account_id, -invited_at)` |

- **Unread counts (verifier correction):** replace the per-member `unread_count` that is incremented on every send (up to 255 UPDATEs per group message) with sequences. The unread count is `conversation.last_seq − member.last_read_seq`. Pointers move monotonically with `UPDATE … WHERE last_read_seq < :new`, so a pointer can never go backwards.
- **Read receipts:** `member_states` must become viewer-aware, so `send_read_receipts=false` cannot be bypassed through REST.
- **Partition candidate:** `message` (§8.2).

### 4.8 realtime (no database)

Realtime uses Redis DB 7 only (**verified**). Target presence keys (Module 5) replace the single `presence.<id>` key, which today is deleted when any one tab closes and is never refreshed by pings:

| Key | Type | TTL | Purpose |
|---|---|---|---|
| `presence:sock:<account_id>` | ZSET (member channel_name, score heartbeat epoch) | 120 s | online while `ZCOUNT(now − TTL, +inf) > 0`; dead sockets expire on their own |
| `presence:last_seen:<account_id>` | string (ISO time) | none or long | written on the last disconnect |
| `presence:vis:<viewer>:<target>` | string | 60 s | cached visibility verdict |
| `ratelimit:typing:<channel>:<conv>` | `SET NX EX 2` | 2 s | typing throttle |

### 4.9 marketplace (`market_db`)

**Current (verified)**

- **`marketplace_category`**: `parent`, `slug`, `name`, `position`.
- **`seller_profile`**: created on first listing, never updated.
- **`listing`**:
  - `seller_id`, `category` FK (PROTECT), `title`, `description`
  - `price` `Decimal(19,4)` NOT NULL default 0, `currency` `CharField(3)` default USD
  - `condition`, `location` (free text)
  - `status` (8 states), `save_count`, `deleted_at`
  - indexes `(status, category, -created_at)` and seller
- **`listing_media`**, **`listing_save`** (unique), **`listing_report`**, **`blocked_pair`** and the platform tables.

**Target (Module 2, with verifier corrections)**

| Model | Change | Key fields | Indexes / constraints |
|---|---|---|---|
| `MarketplaceCategory` | add | `name_ar`, `icon`, `is_active`, `condition_applicable`, `attribute_schema` JSON, `restricted`, `requires_business` | `(parent, position)` |
| `MarketplaceCity` | new | `country_code`, `slug`, ar / en names, centroid lat / lng | unique (country, slug) |
| `Seller` | new (replaces `SellerProfile`, which stays read-only for one release) | `kind` individual / business, `account_id`, `page_id`, display snapshot, rating aggregates, response metrics, counts, `phone_verified`, `status`, `terms_version`, `terms_accepted_at`, age attestation, business disclosure (`commercial_registration`, `tax_id`) | check kind ↔ ids; partial unique one individual seller per account; partial unique page |
| `Listing` | add | `seller_ref` FK, `page_id`, `price` nullable (null means on request, 0 means free), `sale_price`, `price_negotiable`, currency allow-list, `effective_price`, `sort_key` plus id for keyset paging (verifier: equal keys break DRF cursors after 1000 ties), `country_code`, `city` FK, `area`, `geo_lat` and `geo_lng` (rounded to 2 decimals on the server), `quantity`, `attributes` JSON, `search_text`, `title_norm`, `view_count`, `inquiry_count`, `published_at` (set by both auto-publish and moderator approval), `expires_at`, `expiry_warned_at`, `revision` (monotonic counter carried in every `listing.*` event) | `(status, -published_at)`, `(status, currency, sort_key, id)`, `(status, country_code, city)`, `(status, geo_lat, geo_lng)`, `(seller_ref, status)`, partial `(page_id)`, `(status, expires_at)`, `(seller_ref, title_norm, created_at)`, GIN trigram `search_text`; checks on price, sale price and quantity added `NOT VALID` then validated |
| `ListingMedia` | add | `kind` image / video | unique (listing, media_id) after a dedupe |
| `ListingSave` | add | `price_at_save`, `currency_at_save` | `(account_id, -created_at)` |
| `ListingReport` | add | `reason_code` | unique (listing, reporter) after duplicates are marked, not deleted |
| `ListingInquiry` | new | listing, seller, buyer, `conversation_id`, status, first message and first response times | unique (listing, buyer); `(seller, status, -last_activity_at)`; `(conversation_id)` |
| `ListingDailyStat` | new | views, saves, inquiries per listing per day (purged after 400 days) | unique (listing, day) |
| `ReviewEligibility`, `SellerReview` | new | eligibility from a completed order or an answered inquiry; review 1 to 5, body, seller reply, status | unique (listing, buyer); check rating 1 to 5 |
| `Order`, `OrderEvent` | new | number from `marketplace_order_number_seq`, quantity, prices, totals, status machine, cash / meetup only, listing snapshot, delivery address (purged 90 days after a terminal state); event timeline | partial unique **one open requested order per buyer per listing**; `(buyer, -created_at)`, `(seller, status, -created_at)`, `(status, requested_at)`; checks on quantity and total |
| `HiddenSeller` | new read-model | suspended sellers, fed by `account.suspended` and `account.reinstated` | PK account |
| `MediaRef`, `PageMemberRef` | new read-models (verifier) | media owner, kind and status from `media.processed`; page roles from `page.member.changed` | PK / unique |

- **Search (verifier):** `search_text` is already normalized and lowercased, so query it with `__contains`. Django compiles `icontains` to `UPPER(col) LIKE`, which cannot use a plain `gin_trgm_ops` index.
- **Stock (verifier):** quantity is decremented at seller **accept**, under `select_for_update`, not at request time. Otherwise one buyer can lock a seller's stock for 48 hours.
- **Extension:** `pg_trgm`.

### 4.10 notification (`notif_db`)

**Current (verified)**

- **`notification`**: `recipient_id`, `kind`, `actor_id`, `subject_ref`, `group_key`, `body` (300), `read_at`, `created_at`; index `notif_recipient_idx (recipient_id, -created_at)`.
- **`notification_preference`**: PK account, `prefs` JSON, `quiet_hours`.
- **`push_device_token`**: platform, unique token, subscription JSON; index `push_account_idx`.
- **`notification_delivery_log`**, plus the platform tables.
- No retention.

**Target (Module 9, with verifier corrections; Module 5's `aggregate_count` is folded in)**

| Model | Change | Key fields | Indexes / constraints |
|---|---|---|---|
| `Notification` | add | `category`, `target_ref`, `data` JSON (≤ 1 KB, whitelisted keys; **never** copied onto the event bus), `aggregate_key`, `actor_count`, `recent_actor_ids` (≤ 3), `last_event_at` (`db_default` `Now()`), `visible_in_app` (hidden rows get `read_at` at creation, so they never hold an aggregate open), `resolution` | `(recipient_id, -last_event_at, -id)`; partial unread `(recipient_id, category) WHERE read_at IS NULL AND visible_in_app`; `(subject_ref)` and `(target_ref)` alone (cleanup works across recipients); partial unique `(recipient_id, aggregate_key) WHERE read_at IS NULL AND aggregate_key <> ''` |
| `NotificationActor` | new (verifier) | notification FK, `actor_id`, `last_at` | unique (notification, actor); index actor. `actor_count` grows only for a new actor, and block cleanup removes one actor without deleting other people's aggregates. |
| `NotificationPreference` | add | `message_previews`, `email_digest` off / daily / weekly | PK |
| `PushDeviceToken` | add | `label`, `last_success_at`, `failure_count` | existing |
| `BlockedPair`, `PendingPush`, `EmailDigestRun` | new | block read-model (backfilled from graph); deferred quiet-hours pushes; one digest per account per period | unique pair; unique notification; unique (account, period_start) |
| `NotificationDeliveryLog` | index | none | `(created_at)` for the purge |

- **Aggregation window (verifier blocker):** an unread aggregate older than the window must be closed explicitly, by clearing or suffixing its `aggregate_key` inside the same `select_for_update`, before the next row is inserted. Otherwise the partial unique index rejects every later event for that key and the consumer dead-letters.
- **Not adopted:** a `RecipientContact` copy of emails (verifier). The digest job asks identity's internal API for email, language and status at send time, so `notif_db` holds no email addresses.
- **Retention:** read rows after 90 days; any row after 180 days; delivery logs after 30 days.

### 4.11 search (`search_db`)

**Current (verified)**

- **`search_document`**:
  - `doc_type`: a free `CharField(16)`. The allowed values are a Python list in the views, so a new type needs no migration.
  - `doc_id`, `title`, `body`, `owner_id`, `extra` JSON
  - unique (doc_type, doc_id); index `doc_type`
- **`blocked_pair`** and **`processed_event`**; search publishes nothing.
- Migrations `0001_initial` and `0002_security_fixes`.

**Target**

| Model | Change | Key fields | Indexes / constraints | Module |
|---|---|---|---|---|
| `SearchDocument` | add | `title_norm`, `body_norm` (Arabic-normalized) | GIN `gin_trgm_ops` on both; `(doc_type, -updated_at)`; migration **0003** (0002 is taken; verifier) | 1 |
| doc types | code only | `group`, `gathering`, `video`, `reel`, `job` | none | 1, 3, 4, 7 |
| `HiddenOwner` | new read-model (verifier) | suspended accounts and pages, filtered like `BlockedPair` instead of deleting their documents, so reinstatement is instant and lossless | PK owner | 10 |

- **Ordering:** listing and page documents store the source `revision` (or `occurred_at`) in `extra`. An older event never overwrites a newer state; without this, a retried `listing.updated` could re-index a removed listing.
- **Owner preserved:** `page.updated` and `job.*` payloads carry the owner, so a re-index never clears `owner_id`. Clearing it would show the document to users who blocked the owner.
- **Hashtags:** hashtag documents are created only from public posts. They are removed when the tag's last post is deleted or when the tag is blocked.

### 4.12 moderation (`moderation_db`)

**Current (verified)**

- **`report`**: free-text reason.
- **`moderation_case`**: `state` open / in_review / resolved, `severity` (always "normal"), `report_count`, `assigned_to`; partial unique `one_open_case_per_target`.
- **`moderation_action`**: remove / restrict / warn / shadow / dismiss / approve.
- **`appeal`**.
- **`content_policy`**: unused.
- **`moderation_audit_log`**: write-only.
- Outbox and processed tables.

`target_type` is a free `CharField(20)` on report and case, so new target types need no migration.

**Target (Module 10, with the Module 2 and Module 10 verifier corrections)**

| Model | Change | Key fields | Indexes / constraints |
|---|---|---|---|
| `ModerationCase` | add | `source` report / auto / review / staff (`review` covers Module 2's pre-publication listing review), severity choices + `severity_rank`, `triage_key` bigint (severity, capped report count and age packed together), `reason_code`, `owner_id`, `snapshot` JSON + `snapshot_captured_at`, `decision`, `policy_key`, `resolved_by`, `resolved_at`, `appealable_until` | `(state, -triage_key, -id)`: a keyset-friendly triage order (verifier; a `severity_rank` lead column has ~4 values and degrades to offset scans); `(owner_id, -created_at)`; `(assigned_to, state)` |
| `Report` | add | `reason_code`, `case` FK | unique (case, reporter) WHERE case IS NOT NULL, after a dedupe |
| `ModerationAction` | add | actions + reject / hold / suspend / reinstate / restore; `reverses_action_id`; `reason_code`, `policy_key`, `duration_hours`, `features`, `metadata`; `moderator_id` nullable + `actor_type` staff / system | `(case, -created_at)`, `(moderator_id, -created_at)` |
| `Appeal` | add | `resolved_by`, `resolved_at`, `resolution_note` | unique (case, account) after duplicates are marked; `(status, created_at)` |
| `ContentPolicy` | add | bilingual title and body, `is_published`, `updated_by` | unique (key, version) |
| `BlockedTerm`, `BlockedDomain`, `AccountStrike` | new | normalized terms (token or phrase, at most 2000 active), domains, strikes with expiry | unique (term, match); unique domain; `(account_id, expires_at)` |
| `ModerationAuditLog` | add | `actor_id` nullable + `actor_type` | `(case, -created_at)`, `(actor_id, -created_at)` |

- **Reversals (verifier):** an overturned appeal emits the **inverse** of the original action (remove → restore, reject → approve, suspend → reinstate, and so on), linked by `reverses_action_id`. Today it always emits `approve`, which only posts understand.
- **Snapshot retention:** snapshots of resolved cases are blanked after 365 days unless an appeal is open (legal review pending, §11).

### 4.13 admin (`admin_db`)

**Current (verified)**

- **`feature_flag`**: key PK, `enabled`, `rollout_pct`, `targeting`, `description`, `updated_by`.
- **`system_config`**: unused.
- **`audit_log`**: `actor_id`, `action`, `target`, `metadata`; write-only.
- **`service_health_snapshot`**: one row per poll, never purged.
- No outbox and no Celery.

**Target (Module 10, with verifier corrections)**

| Model | Change | Key fields | Indexes / constraints |
|---|---|---|---|
| `OutboxEvent`, `ProcessedEvent` | new | platform tables | inherited |
| `AuditLog` | add | `category`, `target_type`, `target_id` (backfilled from `target`), `source_service`, `event_id` (unique, for idempotent consumption), `request_id`, `ip_region`, `actor_id` nullable + `actor_type` | `(category, -created_at)`, `(actor_id, -created_at)`, `(target_type, target_id, -created_at)`, `(action, -created_at)`; retention 730 days; partition candidate |
| `MetricDaily` | new | `day`, `metric`, `dimension`, `value` | unique (day, metric, dimension); `(metric, day)` |
| `DailyActiveAccount` | new (verifier, replaces the HyperLogLog) | `day`, `account_id` | unique pair; dropped after 90 days |
| `SystemConfig` | add | `version`, `description`; keys restricted to a code registry with schemas | PK |
| `ServiceHealthSnapshot` | behavior | written by a beat task every 60 s; purged after 7 days | existing |

- **Metrics (verifier):** `MetricDaily` is incremented with `F('value') + 1` in the **same transaction** as the `ProcessedEvent` row. There is no Redis counter with a later flush.
- **Header trust:** `ip_region` and `request_id` are stored only when the edge sets them. nginx must overwrite `X-Geo-Region` and `X-Request-Id`; today clients control both.

### 4.14 ads (`ads_db`)

**Current (verified directly in `ads/models.py` and by the audit)**

- **`advertiser_account`**: `owner_account_id` (unique), `name`, `billing_status` (never read).
- **`campaign`**: objective is free text; `budget`, `spent` `Decimal(19,4)`, `currency`, `status`, schedule.
- **`ad_set`**: `targeting` JSON (not evaluated), `placement`, `cpc`, `cpm`, `frequency_cap`.
- **`ad_creative`**: headline, body, `media_id`, CTA, `link_url`, `review_status`.
- **`ad_review`**.
- **`ad_impression_event` / `ad_click_event`**: creative FK, `viewer_bucket` (2 hex characters), `placement`, `occurred_at`; index `(creative, occurred_at)`.
- **`ad_budget_ledger`**: `Decimal(19,4)`, `balance_after`.
- Platform tables.

Money bugs that touch the schema (verified):

- Each impression adds `cpm/1000` into a 4-decimal column, which rounds on every save. A CPM below 0.05 is never charged, and a CPM of 1.25 is overcharged by about 4%.
- Both `cpm` and `cpc` are charged when both are set.
- The last event can overspend the budget.

**Target (Module 6, with verifier corrections)**

| Model | Change | Key fields | Indexes / constraints |
|---|---|---|---|
| `AdvertiserAccount` | add | `kind` personal / business, `page_id`, `currency` (allow-list, fixed after the first funding), `timezone`, `status`, `balance`, `reserved`, `billing_verified_at`; `billing_status` becomes unverified / verified / suspended | partial unique one personal account per owner; unique page; check `balance ≥ reserved ≥ 0` |
| `PageRoleRef` | new read-model | keyed on the event `subject_id` (the page); `last_event_at`; removed members kept as tombstone rows | unique (page, account) |
| `BlockedPair`, `AdPreference` | new | block read-model; ad topics, personalization toggle, hidden advertisers. Age is **not** stored in ads: it arrives as `is_minor` / `age_band` claims in the feed slot call (§4.1), so the earlier `ViewerAdContext` read-model is dropped. | PK / unique pairs |
| `Campaign` | add | objective choices, `daily_budget`, `reserved`, `pause_reason` (including `payment_required`), `special_category`, lifecycle timestamps; explicit state machine | `(advertiser, -created_at)`, `(status, schedule_end)`; check `spent ≥ 0` and schedule end > start |
| `CampaignDaySpend` | new | campaign, `day` (advertiser time zone), integer `impressions` and `clicks` counters, `spend` computed at the charge boundary (or integer micros), `settled` | unique (campaign, day) |
| `AdSet` | add | `billing_event` impression / click (only this event is charged), `status` | `(campaign, status)` |
| `AdCreative` | add | `format`, `post_id`, `listing_id`, `replaces` FK, `lineage_id` (keeps frequency caps and stats stable across revisions; verifier), `delivery_status`, `reject_reason_code`, `review_step`, `landing_domain`, `utm_tagging`; a discarded revision gets status `discarded` and is never deleted (keeps `AdReview` history) | `(ad_set, review_status)`, partial post / listing indexes, format checks |
| impression / click events | add | `country`, `is_valid`, `invalid_reason`, `visible_ms` (impressions), `click_id` (unique) | `(occurred_at)` for the 90-day purge, CONCURRENTLY; partition candidate |
| `AdStatsDaily`, `CampaignReachDaily` | new | per creative × day × placement × country counters; reach from HLL registers, stored as `bytea` once a day closes | unique keys per design |
| `AdFundingTransaction` | new (append-only) | credit / reserve / release / spend / refund / adjustment | settle **closed days only**, or make the reference `campaign:day:<seq>` (verifier blocker: the unique `campaign:day` reference otherwise rejects the second hourly settlement); check `amount > 0` |
| `TopUpRequest` | new | private receipt media (must be scanned clean), method, decider ≠ requester | `(status, created_at)`; check decider ≠ requester |
| `AdStatement`, `AdStatementLine` | new | monthly statements numbered from `ads_statement_seq` | unique (advertiser, month) |
| `ConversionEvent`, `ConversionApiKey` | new | conversions; HMAC-hashed API keys | unique **(advertiser, source, external_id)** (verifier: a global unique silently drops another advertiser's order id 1001) |
| `AdAuditLog` | new | append-only staff actions | `(target_type, target_id)`, `(actor_id, -created_at)` |

`ad_budget_ledger` is kept as read-only history.

### 4.15 bff (no database)

The BFF is a stub with no data and is not deployed on Dokploy (**verified** by the infra audit).

---

## 5. Conflicts between module designs, and how this document resolves them

Each row is a **decision** that needs sign-off.

| # | Conflict | Modules | Resolution here | Why |
|---|---|---|---|---|
| 1 | Skills and certifications modelled twice (`UserSkill` / `UserCertification` vs `Skill` + `ProfileSkill` + `SkillEndorsement` + `Certification`) | 7, 8 | Use Module 7's catalog models. Drop `UserSkill` and `UserCertification`. | Superset: endorsements, issuer pages, media evidence. |
| 2 | Who owns list visibility and friend-request policy (copies in profile vs graph) | 1, 8 + verifiers | Graph `ConnectionPrivacy`. Profile keeps per-field privacy only. | Enforced at once by the service that owns the edges; no event lag. |
| 3 | Page follower count in profile (`PageFollower` + `Page.follower_count`) vs graph `AccountCounter` | 7, 8 | Graph `AccountCounter` with `subject_type=page`. | Graph owns follows; avoids an order-sensitive copy. |
| 4 | Page suspension fields: `suspended_reason` / `suspended_at` vs `status_reason` / `status_changed_at` / `status_changed_by` | 8, 10 | Module 10 names. | They also cover non-suspension status changes. |
| 5 | Author read-models in post: `AuthorPrivacy` vs `HiddenAuthor` | 8, 10 | One `AuthorState` table. | Same key and the same visibility checks. |
| 6 | Where video stats live: post (`VideoStatDaily`) vs feed (reel stats) | 3, 4 | Feed holds both. Post keeps only a display `view_count`, updated from roll-up events. | One telemetry pipeline, one Redis stream, one set of fraud checks. |
| 7 | Notification aggregation: `aggregate_count` vs `actor_count` + `recent_actor_ids` | 5, 9 | Module 9 plus `NotificationActor`. | Exact counts and precise block cleanup. |
| 8 | `events` app name in post | 1 | Rename to `gatherings`; events become `gathering.*`. | Avoids clashing with `events.py` and the event-bus vocabulary. |
| 9 | `discoverable` vs `searchable` profile flags | 1, 8 | One `searchable` flag on profile's `UserProfile` (built in roadmap 1.6), copied from `profile.updated` into graph `AccountRef` (suggestions), post `AuthorState` and feed (recommendations); plus a separate `allow_link_previews`. Graph's `ConnectionPrivacy` does not hold it. | "Findable inside Tara" and "previewed on the open web" are different consents. |
| 10 | Pre-review cases: a new `kind` column vs `source` | 2, 10 | `source='review'`. | One column. |
| 11 | Video creates the Post late vs Reels creates it early with `publish_state` | 3, 4 | `Post.publish_state` + `published_at` for both. | One visibility gate; no backdating. |
| 12 | Emails copied into `notif_db` (`RecipientContact`) | 9 | Not adopted; identity internal lookup at send time. | No PII copy, and no stale language or status. |
| 13 | Admin metrics via Redis then flush vs in the consumer transaction | 10 | In the transaction. | No double-count window; one less job. |
| 14 | Ad spend accrual: Decimal per event vs counters | 6 | Integer counters per day; spend computed at the boundary. | No rounding drift. |
| 15 | `FeedItem.post_type` column + backfill vs expression index | 3 | Expression index on `snapshot->>'type'`. | No rewrite of the largest derived table. |
| 16 | ffmpeg worker per module (Video "transcoder", Reels "video worker") | 3, 4 | One `media-video-worker` image and queue for both, with a minimal env (§9.6). | One hardened ffmpeg surface. |
| 17 | Migration numbers claimed more than once (profile `0002` by Modules 1, 7, 8 and 10; post `0003`, `0004` by 1, 3, 4 and 8) | all | Numbers are assigned when a PR merges; §7.3 gives the order. | Django needs a linear chain per app. |
| 18 | Media key layout: per-asset prefix (today's thumbnails) vs top-level `hls/<id>` and `poster/<id>` | 3, 4 | Per-asset prefix for every derived file (§9.2). | Matches existing rows; deleting one asset is a single prefix. |

---

## 6. Cross-service references and read-models

### 6.1 Reference map (who points at whose rows)

| Stored in | Field(s) | Points to (owner) | Kept consistent by |
|---|---|---|---|
| post, chat, marketplace, profile, ads, careers | `media_id`, `*_media_id` | media `MediaAsset` | validation at write time via the media internal endpoint (owner, kind, status, visibility); `media.processed` / `media.failed`; planned `media.deleted` |
| almost every service | `account_id`, `author_id`, `owner_id`, `recipient_id`, `seller_id`, `viewer_id` | identity `account` | `account.registered`; planned `account.suspended` / `account.reinstated` (Module 10); **missing** `account.deleted` / `account.deactivated` |
| post (`author_type=page`), ads, marketplace, careers (real FK, same DB), graph | `page_id` | profile `Page` | `page.created`, planned `page.updated`, `page.status.changed`, `page.member.changed` |
| feed, notification, search, ads, admin | `post_id`, `subject_ref` (`post:<id>`) | post `Post` | `post.created`, `post.updated`, `post.deleted` |
| ads, chat (`listing_id`), search, notification | `listing_id` | marketplace `Listing` | `listing.status.changed`, `listing.updated` (with `revision`) |
| moderation, admin | `target_type` + `target_id` | any service | snapshot via each owner's `/internal/v1/moderation/targets/...`; decisions sent back by `moderation.actioned` |
| notification | `subject_ref`, `target_ref` | post / chat / graph / marketplace / ads | cleanup consumers (`post.deleted`, `user.blocked`, `friendship.request.withdrawn`) |
| post (`group_id`) | group | profile `Group` | `group.*` + `GroupMembership` read-model |
| chat (`conversation_id` in `ListingInquiry`) | conversation | chat `Conversation` | new `marketplace.thread.opened` and `marketplace.thread.message` (carrying buyer id and inquiry id) |

### 6.2 Read-model catalogue

| Read-model | Lives in | Fed by | Used for | Backfill path |
|---|---|---|---|---|
| `BlockedPair` | post, profile, chat, marketplace, search (today); feed, notification, ads (planned) | `user.blocked`, `user.unblocked` | hiding content and actors | graph export through an internal paginated endpoint, or a snapshot event (**not** replaying `user.blocked`) |
| `AccountRef` | graph | `account.registered`, `profile.updated`, `profile.deleted` | target validation, suggestions | `publish_profiles` (safe: idempotent upsert) |
| `AuthorState` | post | `profile.updated`, `account.suspended`/`reinstated`, `profile.deleted` | profile lock, suspension hiding | `publish_profiles` |
| `GroupRef`, `GroupMembership` | post | `group.*`, `group.member.changed` | group visibility | `rebuild_group_readmodel` (pages through profile's internal fan-out) |
| `PageMemberRef` | post, marketplace | `page.created`, `page.member.changed` | post or sell as a page | internal page-member list |
| `PageRoleRef` | ads | same | business ad accounts | same |
| `PageRef` | graph | `page.created`, `page.updated`, `page.status.changed` | validate page follows, owner blocks | internal page list |
| `FollowEdge` | feed | `user.followed`, `user.unfollowed`, `user.blocked` | Following reels | paginated graph endpoint (**not** `publish_follows`, which would re-send "started following you" notifications; verifier blocker) |
| `FriendPair` | chat | `friendship.accepted`, `friendship.removed` | message requests | graph export |
| `ParticipantProfile` | chat | `profile.updated` | DM name search, call display names | `publish_profiles` |
| `MediaRef` | marketplace (optionally post) | `media.processed` | attach validation without sync calls | media internal batch lookup |
| `HiddenOwner` | search | `account.suspended`/`reinstated`, `page.status.changed` | hide without deleting | identity and profile internal lists |
| `HiddenSeller` | marketplace | same | browse filter | same |
| `AuthorEligibility` | feed | `profile.updated`, `moderation.actioned` (user targets) | For You eligibility | `publish_profiles` |

There is no age read-model. Ads, reels and marketplace read `is_minor` and `age_band` from the access-token claims at request time (§4.1).

### 6.3 Rules every read-model follows

1. **Upserts are idempotent and ordered.** Each read-model row stores `last_event_at` from `envelope.occurred_at`. An event older than the stored value is ignored. tara_events retries through delay queues (5 s to 1800 s), so delivery order is not guaranteed.
2. **Revocations are kept as tombstones**, not deleted rows. Then an older "added" event cannot bring back a removed grant. This applies to `PageRoleRef`, `PageMemberRef`, `FollowEdge`, `ReelCandidate` and group membership.
3. **Missing means fail closed.** A missing row on a privacy or authorization path triggers a synchronous internal check with a circuit breaker. If that check fails, access is denied. Negative results are cached briefly, so non-members do not trigger a sync call on every request.
4. **Never backfill by replaying action events.** Use a snapshot event type that only the read-model consumes, or a paginated internal endpoint. `profile.updated` is an exception because its consumers are pure upserts.
5. **Revocation-critical paths read the source synchronously:** posting into a group, recruiter CV access, billing actions, suspension. A read-model alone is not enough there.

---

## 7. Migration plan

### 7.1 Safety rules

These rules come from the module designs and the verifier corrections. All of them are mandatory.

| Situation | Technique |
|---|---|
| Add a column with a default | `db_default=` (Django 5.2), so containers still running the old code during a Dokploy recreate keep inserting rows. A plain `default=` is dropped from the database after `AddField`. |
| Make an existing column NOT NULL | Add `CHECK (col IS NOT NULL) NOT VALID`, then `VALIDATE CONSTRAINT`, then `SET NOT NULL` (PG12+ skips the scan), wrapped in `SeparateDatabaseAndState`. |
| Add a check constraint on existing data | `NOT VALID` in one migration, `VALIDATE` in the next. |
| Add or remove an index on an existing table | `AddIndexConcurrently` / `RemoveIndexConcurrently`, alone in an `atomic = False` migration. |
| Add a unique constraint on existing data | Dedupe first (mark duplicates when they are evidence, such as reports or appeals; never delete them), then `CREATE UNIQUE INDEX CONCURRENTLY` with `state_operations=[AddConstraint(...)]`. |
| Backfill data | A management command, batched by primary key, one commit per batch, safe to re-run. When a `RunPython` is unavoidable, use `atomic = False` and a frozen copy of any helper (for example the Arabic normalizer) inside the migration file. |
| Change choices only, or widen a varchar | `AlterField`; no table rewrite. |
| Extension | `TrigramExtension()` in the first migration that needs it. Works because each role owns its database. Fallback when a managed Postgres refuses: `icontains` without the index. |
| Sequence | `RunSQL` with a `reverse_sql`. |
| Rename or drop | Expand and contract over two releases: add, dual-write, switch reads, then drop in a later release. Never rename or drop in the release whose code stops using the column. |
| Long backfills | Never in the web entrypoint, which has a 60 s healthcheck `start_period`. Run them as one-off jobs. |

Every PR still passes `makemigrations --check` in `scripts/test-service.sh`. Rehearse each step's migrations on a restored backup (`scripts/backup.sh`) before production. Rows are not written to a new column until the backfill for that column has finished; feature flags hide the dependent reads until then. The one exception is a value that must be assigned under a lock while live writes continue, such as the chat message `seq`. Its backfill runs per parent row under that same lock (§7.3, chat).

**Existing rows that a new rule would reject** get an explicit data migration or command in the milestone that adds the rule: `relabel_feed_reasons` [1.1], `visibility=custom` → `private` [2.1], `classify_zero_price_listings` and `normalise_currencies` before the listing checks are added `NOT VALID` [4.3].

### 7.2 Schema changes by roadmap milestone

This table replaces the earlier "waves". The waves did not match the roadmap's build order: they put the admin outbox (8.1), the identity, ads and media consumers (steps 5, 6 and 8), `HandleRegistry` (2.2) and `AuthorState` (2.3) first, bundled careers and marketplace sellers with groups and stories, and put orders after video, while 04 builds orders in 4.10. Each migration now ships with the milestone that first needs it. The tags in §7.3 use the same ids.

| Step | Milestone → schema change |
|---|---|
| 1 | **1.1** `relabel_feed_reasons` (command); hashtag documents only from public posts (code + cleanup). **1.2** moderation state guards (code only). **1.3** comments v2 (`reply_to_id`, `edited_at`, `CommentReaction`). **1.4** `PostReactionCount` (+ `backfill_reaction_counts`). **1.5** media real `bytes`, `etag`, `staging_key`, `purpose`; `MediaVariant` dedupe and unique index; `privatize_post_media`. **1.6** graph `ConnectionPrivacy`, `AccountCounter` (+ `rebuild_counters`), `SuggestionDismissal`, `AccountRef.searchable`, edge indexes; profile `UserProfile.searchable`. **1.7** feed `PostStat`, `Affinity`, `FeedHide`, `AuthorSnooze`, `BlockedPair`, new `FeedItem.reason` values; `redis-hot`. **1.8** `Hashtag.norm`, `HashtagBlock`, `TrendingSnapshot`. **1.9** `Post.audience` widened to 16; `stories` app; feed `StoryTrayEntry`. **1.11** profile `groups` app; post `group_id`, `GroupRef`, `GroupMembership`. **1.13** `gatherings` app; post `gathering_id`. **1.15** search `0003` trigram and normalised columns. |
| 2 | **2.1** profile child-table `created_at` and `position` (fixes the list 500s); `custom` → `private`. **2.2** `HandleRegistry`, `HandleHistory` (+ backfill, audit). **2.3** post `AuthorState`; profile `mentions_from`. **2.4** work and education fields. **2.5** `PostMedia` denormalisation (+ `backfill_media_kind`). **2.6** profile type and page fields. **2.7** post `PageMemberRef`; graph `PageRef`. **2.8** `ActivityEntry`. **2.9** profile lifecycle and moderation fields. **2.12** identity age attestation. **2.14–2.19** notification v2 (fields, backfill, `NOT NULL`, indexes, `NotificationActor`, `BlockedPair`, `PendingPush`, `EmailDigestRun`). |
| 3 | **3.1** chat `visible_from`. **3.2** `MessageAttachment` fields; `privatize_chat_media`. **3.3** `MessageEdit`, `MessageHidden`, `MessageReport`, `moderation_removed_at`. **3.4** `Message.seq`, `Conversation.last_seq`, inbox state. **3.5** `ParticipantProfile`, `body_norm`, trigram index. **3.6** `MessengerSettings`, `FriendPair`, `request_state`. **3.7–3.8** `Call`, `CallParticipant`, `CallWebhookEvent`. **3.10** media `scan_status` states and quarantine. |
| 4 | **4.1** moderation `source='review'`; listing report dedupe. **4.2** `ListingMedia` unique. **4.3** category schemas; price and currency fields with their data commands; checks `NOT VALID` → `VALIDATE`. **4.4** `pg_trgm`, search fields, listing indexes, `revision`. **4.5** `MarketplaceCity`. **4.6** `Seller` (+ `backfill_sellers`), marketplace `PageMemberRef`. **4.7** `ListingInquiry`, `ListingDailyStat`, expiry fields. **4.8** reviews. **4.9** `ListingSave` price fields. **4.10** `Order`, `OrderEvent`, `marketplace_order_number_seq`. **4.12** seller terms, attestation and business disclosure. |
| 5 | **5.2** media processing fields, `VideoJob`, variant labels and kinds. **5.3** `moderation_hold_at`. **5.4** `videos` app; post `publish_state`, `published_at`. **5.5** `reels` app. **5.6** feed `ReelViewDay`, `IngestCursor`, stats tables. **5.7** feed expression index on `snapshot->>'type'`. **5.9** playlists, watch history, saved-item normalisation. **5.11** feed `FollowEdge`, `ReelCandidate`, `ViewerInterest`, `AuthorEligibility`. **5.12** creator and video stats. **5.13** `Sound`. **5.15** multipart `UploadSession` fields. |
| 6 | **6.1** ad set billing event, event quality fields. **6.2** ad accounts, `PageRoleRef`. **6.3** campaign lifecycle (pauses active campaigns), funding ledger, `TopUpRequest`; identity `finance` role. **6.4** creative formats and lineage. **6.6** targeting refs, `AdPreference`, ads `BlockedPair`. **6.7** stats, reach, statements, `ads_statement_seq`. **6.9** conversions. **6.12** video and reel creative formats. |
| 7 | **7.1** skills and certifications. **7.2** `Resume`. **7.3** `CompanyProfile`. **7.4–7.9** `careers` app. **7.10** page status meta, `PageMember` invitation state and the recruiter role. |
| 8 | **8.1** admin outbox and processed tables, audit fields, nullable `actor_id` + `actor_type` in moderation and admin. **8.2** moderation triage and evidence; media `legal_hold_until`. **8.4** identity `AccountRestriction`. **8.5** search `HiddenOwner`, marketplace `HiddenSeller`. **8.9** `BlockedTerm`, `BlockedDomain`, `AccountStrike`; `Post.is_visible` hides PENDING (code). **8.11** `MetricDaily`, `DailyActiveAccount`. **8.12** capability overrides. **8.13** `SystemConfig`. |
| L | **L.4** identity recovery codes for TOTP. **L.5** erasure bookkeeping per service. |

### 7.3 Proposed migration order per service

Names are indicative. Numbers are assigned when each PR merges, so the chains below give names and order without numbers. The `[x.y]` tag is the roadmap milestone that ships each migration (§7.2). A migration tagged `CONC` contains only concurrent index or constraint operations, with `atomic = False`. Concurrent indexes ship as their own `CONC` migration next to the milestone that first queries them.

| Service / app | Order |
|---|---|
| identity | `age_attestation` [2.12] → `account_role_finance` (choices only) [6.3] → `restrictions` [8.4] → `capability_overrides` [8.12] → `admin_indexes` (CONC) [8.6] → `two_factor_recovery` [L.4] |
| profiles | `profile_searchable` (db_default) [1.6] → `child_created_at` (db_default; UserLink / Education / Work `created_at`, `position`) + `map_custom_visibility` (command: `custom` → `private`) [2.1] → `handle_registry` (+ `backfill_handle_registry`, `audit_handles`) [2.2] → `mentions_from` [2.3] → `professional_fields` [2.4] → `profile_type_page_fields` [2.6] → `page_member_indexes` (CONC) [2.7] → `activity_entry` → `activity_indexes` (CONC) [2.8] → `lifecycle_moderation_fields` [2.9] → `allow_link_previews` [2.11] → `skills_certifications_resumes_prefs` [7.1, 7.2] → `company_profile` [7.3] → `page_status_meta`, `page_member_invitation_state` [7.10]. Each `UserProfile` addition ships with the milestone that first uses it. |
| groups (new app) | `0001_initial` [1.11] |
| careers (new app) | `0001_initial` (TrigramExtension + jobs and applications) [7.4, 7.5] → `interviews_alerts` [7.7, 7.9] |
| graph | `connection_privacy_counters_dismissal` + `AccountRef.searchable` [1.6] → `edge_indexes` (CONC) [1.6] → `rebuild_counters` (command) [1.6] → `page_ref` [2.7] |
| media_app | `real_bytes_etag_staging_purpose` [1.5] → `variant_dedupe` (atomic=False RunPython: delete duplicate (media, kind) rows, keep the oldest) [1.5] → `variant_unique` (CONC) [1.5] → `privatize_post_media` (command, run only after the SPA uses minted URLs) [1.5] → `privatize_chat_media` (command) [3.2] → `scan_states` [3.10] → `processing_fields` → `videojob` [5.2] → `moderation_hold` [5.3] → `multipart` [5.15] → `legal_hold` [8.2] |
| posts | `comments_v2` [1.3] → `reaction_counts` (+ `backfill_reaction_counts`) [1.4] → `hashtag_norm_trending_block` (+ `renormalize_hashtags`; trending partial index CONC) [1.8] → `audience_widen` [1.9] → `group_readmodels` (`group_id`, GroupRef, GroupMembership) [1.11] → `gathering_id` [1.13] → `author_state` [2.3] → `postmedia_denorm` (+ `backfill_media_kind`, throttled, using the media batch endpoint) [2.5] → `page_member_ref` [2.7] → `origin` [2.10] → `publish_state` (db_default `published`) [5.4] → `saved_item_normalize` [5.9] |
| stories, gatherings, videos, reels (new apps) | `0001_initial` each [1.9, 1.13, 5.4, 5.5] |
| feed | `relabel_feed_reasons` (command) [1.1] → `ranking_and_readmodels` [1.7] → `story_tray` [1.9] → `telemetry_tables` (+ `IngestCursor`) [5.6] → `feed_expression_index` (CONC) [5.7] → `reels_tables` [5.11] → `video_stats` [5.12] |
| chat | `visible_from` [3.1] → `attachment_fields` [3.2] → `message_lifecycle` [3.3] → `messenger_state` (db_default) [3.4] → `seq` (+ the per-conversation backfill below) [3.4] → `search_indexes` (TrigramExtension + CONC) [3.5] → `settings_friendpair` [3.6] → `calls` [3.7, 3.8] |
| marketplace | `report_reason_mark_dupes` [4.1] → `media_kind_unique` [4.2] → `category_schema` [4.3] → `listing_price_currency` (db_default; price nullable) + `classify_zero_price_listings` and `normalise_currencies` (commands, run before the checks) [4.3] → `listing_checks_not_valid` → `validate_checks` [4.3] → `trigram_extension` → `listing_search_fields` (+ `backfill_listings`) → `listing_indexes` (CONC) [4.4] → `city` (+ `seed_cities`) [4.5] → `seller` (+ `backfill_sellers`), `page_member_ref` [4.6] → `inquiry_stats_expiry` [4.7] → `reviews` [4.8] → `save_price` [4.9] → `orders_sequence` [4.10] → `seller_terms` [4.12] → `hidden_seller` [8.5] |
| notifications | `v2_fields` (db_default `last_event_at`) [2.14] → `backfill_notification_v2` (command) → `last_event_at_not_null` (NOT VALID → VALIDATE → SET NOT NULL) → `indexes` (CONC, including the partial unique aggregate index) [2.16] → `actor_blockedpair_pending_digest` [2.16, 2.17, 2.19] → later `drop_notif_recipient_idx` (CONC) |
| searchsvc | `0003_trgm_norm` (+ `renormalize_documents`) [1.15] → `hidden_owner` [8.5] |
| moderation | `review_source` [4.1] → `actor_type` [8.1] → `triage_evidence` → `mark_duplicates` (atomic=False) [8.2] → `constraints_blocklists` (CONC for the uniques) [8.2, 8.9] |
| adminsvc | `events_audit` → `audit_backfill` [8.1] → `audit_indexes` (CONC) [8.1] → `metrics` [8.11] |
| ads | `adset_billing` (cpc>0 and cpm=0 → click, else impression) [6.1] → `event_quality` (+ CONC `occurred_at` indexes) [6.1] → `accounts` [6.2] → `campaign_lifecycle` (RunPython: currently ACTIVE campaigns become paused with `payment_required`) + `funding_sequence` [6.3] → `creative_formats_lineage` [6.4] → `targeting_refs_audit` [6.6] → `stats` (+ `ads_backfill_stats`) [6.7] → `conversions` [6.9] → `video_reel_formats` [6.12]. The earlier `viewer_context` migration is dropped (§4.14). |

**Chat `seq` backfill under live sends (critic correction).** `unique (conversation, seq)` and a monotonic per-conversation `seq` cannot be backfilled in batches while sends continue. A send during the backfill would either get no `seq` or one that collides with a backfilled value (`IntegrityError` on send). The procedure:

1. `messenger_state` adds `Conversation.last_seq` (db_default 0) and `Conversation.seq_ready` (db_default false). `seq` is nullable, and Postgres treats NULLs as distinct under the unique constraint.
2. New code sends under `select_for_update` on the conversation row. If `seq_ready` is true, it assigns `last_seq + 1` and updates `last_seq` in the same transaction. If not, it leaves `seq` null, and unread counts for that conversation keep the old method.
3. `backfill_messenger_state` takes one conversation at a time. Under the same row lock, it numbers all its messages (including any sent with a null `seq`) by `(created_at, id)`, sets `last_seq`, the members' `last_read_seq`, and `seq_ready=true`, then commits.
4. Conversations above a size threshold (for example 50,000 messages) are backfilled in a short maintenance window, so the lock does not hold sends for long.
5. A concurrency test runs sends in parallel with the backfill of the same conversation: no `IntegrityError`, and `seq` is gap-free and strictly increasing afterwards.

### 7.4 Deploy order rules

1. **New event types ship in two releases.** A RabbitMQ queue binds only the event types registered when its consumer starts. The publisher uses `confirm_publish` without `mandatory` or an alternate exchange (`libs/tara_events/tara_events/publisher.py`), so an event with no bound queue is confirmed, dropped, and marked published in the outbox. A Dokploy compose deploy restarts every changed container together, so "deploy the consumer first" cannot be enforced inside one deploy. Release N therefore adds the consumers with emission off. Release N+1, or a flag flip once release N is fully up, turns emission on. The alternate exchange on `tara.events` (roadmap 1.0g) sends anything unroutable to `tara.events.unrouted` for alerting and replay.
2. **Workers and consumers wait for migrations.** Only web containers set `RUN_MIGRATIONS=true`. Worker and consumer entrypoints wait until `manage.py migrate --check` passes before they start (roadmap 1.0g), so new code never runs against the old schema. `db_default` (§7.1) still covers old code running against the new schema.
3. **Read-model backfills run after their consumer is live**, so no live event can land between the snapshot and the switch.
4. After the graph, post, search and chat consumers for `profile.updated` are live, run `manage.py publish_profiles` once. It cannot create profiles that were never provisioned (seeded or superuser accounts). Those need `ensure_profile` driven from identity.
5. **Money migrations ship behind flags.** The ads `campaign_lifecycle` migration pauses every active campaign, so the release notes must say so. Keep `ADS_SERVING_ENABLED=false` until `funding_sequence` is live (both in roadmap 6.3).
6. **Dead-letter routing is a broker migration** (roadmap 1.0c), not a code change. Main queues are declared with `x-dead-letter-exchange` only (`worker.py`, lines 68–74), and RabbitMQ refuses to redeclare a durable queue with different arguments (`PRECONDITION_FAILED`). The per-queue routing key is therefore set by a RabbitMQ policy, the old `#` DLQ bindings are removed by a one-off script, and the change is rehearsed on a restored broker with a rollback step. It must be finished before steps 1–8 add many new event types.

---

## 8. Data volume and scaling

### 8.1 What grows, and how fast

Real traffic today is small, so this section gives **growth drivers**, not row estimates. Measure with `pg_stat_user_tables` before acting on any trigger.

| Table | Grows with | Main control |
|---|---|---|
| `feed.feed_item` | posts × recipients (fan-out capped at 5000 recipients per post) | retention (1000 items / 30 days per recipient); fan-out-on-read for large accounts (deferred) |
| `notification.notification` | events × recipients (a group message reaches up to 255 people) | aggregation, actor table, 90 / 180-day retention |
| `chat.message` | messages sent | monthly partitions (trigger in §8.2) |
| `post.post_reaction`, `post.comment` | engagement | indexes; partition only at very large scale (phase-0 note) |
| `post.story_view`, `feed.reel_view_day` | viewer × item × day | 30-day / 90-day retention; daily or monthly partitions |
| ads impression / click events | served ads | 90-day retention; daily partitions; aggregates kept forever |
| `profile.activity_entry` | every action by every user | 365-day retention; monthly partitions |
| `*.outbox_event`, `*.processed_event` | every state change and every consumed event | hourly purge (7 days); watch the backlog after outages |
| audit logs (admin, moderation, ads) | staff actions plus consumed facts | 730-day retention; monthly partitions |
| `media.media_variant` | about 3 to 12 rows per video asset | none needed |
| reels raw telemetry | every playback event | **Redis stream only** (never stored per event in Postgres); rolled up every 60 s |

### 8.2 Partitioning

**Technique: partition by `id` (UUIDv7) range.** UUIDv7 starts with a millisecond timestamp, and Postgres compares UUIDs byte-wise, so monthly ranges can be written as UUID boundaries. A boundary is the month-start timestamp followed by `7000-8000-000000000000`. Every ID generated after the month starts sorts at or above it.

- The primary key stays `id`, so existing same-database foreign keys keep working. Examples: `message_attachment` → `message`, `message.reply_to`, `pinned_message`. Postgres 12+ allows FKs that reference a partitioned table on its partition key.
- The alternative, range on `created_at`, would force a composite primary key `(id, created_at)` and break those foreign keys.
- **Requirement:** every row id must come from `tara_events.envelope.uuid7()` at insert time, including backfills. A test should assert that the first 48 bits of new ids match the clock.

**Pure time-series tables** with no inbound foreign keys (ad events, `reel_view_day`, `activity_entry`, audit logs) can use the same `id` range, or range on `occurred_at` with a composite key through Django 5.2 `CompositePrimaryKey`. Use the `id` range everywhere for one consistent approach (**decision**).

**Converting a live table.** There is no in-place conversion. Instead:

1. Create the partitioned parent.
2. Add `CHECK (id < <cutover uuid>) NOT VALID` to the old table and validate it.
3. Attach the old table as a "legacy" partition `FROM (MINVALUE) TO (<cutover>)`.
4. Repoint child FKs to the parent.
5. Create future partitions.

This is all `RunSQL`, rehearsed on a restored backup.

**Maintenance.** `pg_partman` is not in `postgres:16-alpine`, so each owning service runs a Celery beat task that:

- creates partitions 3 periods ahead
- keeps a DEFAULT partition for stragglers
- detaches and drops partitions older than the retention period. Dropping a partition is instant and avoids `DELETE` bloat.

The service role owns its database, so it may run this DDL.

| Table | Partition by | Trigger to partition | Retention |
|---|---|---|---|
| `chat.message` | month (id) | > 20 M rows or > 10 GB | product decision (messages are long-lived) |
| `notification.notification` | month (id) | > 20 M rows | 180 days (drop partitions) |
| ads impression / click events | day or month (id) | from the start of Module 6 M7 | 90 days |
| `feed.reel_view_day`, `post.story_view` | month | > 50 M rows | 90 / 30 days |
| `profile.activity_entry` | month | > 20 M rows | 365 days |
| admin / moderation / ads audit logs | month | > 10 M rows | 730 days |
| `identity.security_event` | month | > 10 M rows | 365 days (planned in phase-0) |
| `feed.feed_item` | hash on recipient (phase-0 plan) | only if retention is not enough | 30 days |

The thresholds are this document's suggestion (**unverified**: re-measure on the production host).

### 8.3 Counters: Redis first, then flush to Postgres

Use Redis for counters that are hot, approximate and per viewer. Use Postgres for anything that is money or proof.

| Counter | Hot store | Flushed to | Rules |
|---|---|---|---|
| reel playback telemetry | Redis stream `reels:events` (redis-hot, §8.6) | `ReelStatsDaily`, `ReelCandidate`, `ViewerInterest`, `ReelViewDay` | Store the last applied stream id in `IngestCursor` **in the same transaction** as the upserts, so a crash between commit and XACK cannot double-count. Decide views with `ReelViewDay` `ON CONFLICT`, not `SET NX` before commit. |
| video watch events | Redis hashes per (video, day) plus per-session position | `VideoStatDaily`, `Video.view_count`, `VideoWatch` | `VideoWatch` rows are written by the flush job, never per request |
| listing views | `SET NX EX 1800` dedupe + `HINCRBY mkt:views:<day>` | `ListingDailyStat`, `Listing.view_count` | `RENAME` to a **unique** processing key tracked in a set; drain every pending day, not only today; delete only after the DB commit |
| reach (ads) | HyperLogLog per campaign per day | `CampaignReachDaily` (register stored as `bytea` once the day closes) | Keep only about 35 days in Redis |
| ad spend | **Postgres only**, `CampaignDaySpend` integer counters under a row lock | `AdFundingTransaction` on settlement | Money is never stored only in Redis |
| admin metrics | **Postgres only**, `F()` in the consumer transaction | `MetricDaily` | no Redis step |
| relationship counts | **Postgres**, `AccountCounter` with `F()` in the edge transaction | not applicable | `rebuild_counters` repairs drift |
| denormalized row counters (`reaction_count`, `comment_count`, `save_count`, `member_count`, `application_count`) | Postgres `F()` | not applicable | Each needs a reconcile command. Hot rows (viral posts) serialize writers, so batch increments in Redis only if lock waits show up. |

Counters fed by toggles (like / unlike, follow / unfollow) need an undo event: `post.unreacted`, `user.unfollowed` consumed, `message.reacted` with `type=null`. Without them, counters only grow.

### 8.4 Retention schedule (target)

| Data | Keep | Job owner |
|---|---|---|
| outbox / processed events | 7 days after publish or processing | `tara_events.purge_events` (exists) |
| read notifications / all notifications / delivery logs | 90 / 180 / 30 days | notification beat |
| feed items | 30 days, at most 1000 per recipient | feed beat |
| story views | 30 days | post beat |
| ads raw events | 90 days | ads beat |
| `ListingDailyStat` | 400 days | marketplace beat |
| order delivery addresses | 90 days after a terminal state | marketplace beat |
| `MessageEdit` | 90 days | chat beat |
| `CallWebhookEvent` | 7 days | chat beat |
| `ActivityEntry` | 365 days | profile beat |
| service health snapshots | 7 days | admin beat |
| admin audit | 730 days | admin beat |
| moderation snapshots | 365 days after resolution, unless an appeal is open | moderation beat |
| job applications | anonymized 365 days after close; 30 days after withdrawal | profile (careers) beat |
| soft-deleted media | 7 days (user delete); 90 days (moderation removal) | media beat |

Erasure on account deletion is **not covered**: no `account.deleted` event exists yet (§11).

### 8.5 Search and text indexes

- **Arabic normalization** comes from one tested function in `libs/tara_common` (the QTech `_norm` port), hardened with: NFKC, removal of zero-width and bidi control characters, folding of Persian `ی`/`ک` and Arabic-Indic digits. Its output is written to `*_norm` columns.
- **Query with `__contains`** on the normalized column so the `gin_trgm_ops` index is used. `icontains` becomes `UPPER(col) LIKE` and skips the index.
- **Trigram limits:** queries shorter than 3 characters cannot use the trigram index. Require at least 2 characters and use prefix matching for 2-character queries.
- **Arabic trigrams:** check `SELECT show_trgm('مدرسة')` on the production image before launch. Trigram extraction depends on the database ctype (the audit saw `en_US.utf8` on `chat_db`; **unverified** for the other databases).
- **Keyset pagination:** relevance-ordered pages need a dedicated keyset paginator over `(round(similarity, 6), id)`, or a cap of 50 results. The shared `CursorPagination` repeats rows on ties.

### 8.6 Redis memory budget

| Instance | Holds | Policy |
|---|---|---|
| `redis` (existing, `mem_limit 256m`) | caches, throttles, Channels layer, presence, serve-token spend keys | `maxmemory 200mb` with **`noeviction`** (roadmap 1.0h). A policy without `maxmemory` does nothing, and the container is OOM-killed at its memory limit. With the limit set, a full Redis refuses writes, which callers must handle, instead of dying. Never `allkeys-*`, because evicting a throttle bucket or a spend key reopens abuse. Alert at 80% (L.1). Raise the container to 512m (and `maxmemory` with it) before public launch (L.3). |
| `redis-hot` (new, created in roadmap 1.7) | ranking session lists (1.7), then reels telemetry stream, served-recommendation sets, suggestion caches, HLL keys, listing view counters | own `maxmemory` below its `mem_limit`, AOF on, `noeviction` for the stream DB; size it after the reels load test (roadmap §21, decision 13) |

Concrete caps from the verifiers:

- reels stream `MAXLEN ~100000`
- seen sets capped at 500 entries with a 7-day TTL
- per-day HLL keys flushed into Postgres when the day closes and kept for 7 to 35 days

### 8.7 Connections and Postgres sizing

- Every web, worker and consumer process keeps persistent connections (`CONN_MAX_AGE=60`).
- **Estimate today (unverified arithmetic):**

  | Process group | Connections |
  |---|---|
  | about 13 DB-backed web services × 2 gunicorn workers | about 26 |
  | 11 Celery workers × (2 workers + embedded beat) | about 33 |
  | about 10 consumers | about 10 |
  | **Total** | **about 69** |

- Postgres defaults to `max_connections=100`. The 7 new processes in §3 bring the estimate to about 80.
- Recommendation (roadmap L.3, before step 3):
  - Set `max_connections` explicitly (150) and raise `mem_limit` from 1g to match.
  - Plan PgBouncer in transaction mode once headroom drops below 20%. That requires `DISABLE_SERVER_SIDE_CURSORS=True` and a check of advisory-lock usage.
- Celery beat runs inside each worker (`-B -s /tmp/celerybeat-schedule`), so the schedule is lost on every restart, and workers cannot scale past one replica without duplicating periodic jobs. Roadmap L.2 moves beat into its own container with a persistent schedule before 1.8 adds the first new periodic jobs. Heavy periodic jobs (trending scan, purges, statement generation) run on a separate `*.periodic` queue, so they do not delay outbox draining.

---

## 9. Media storage layout (MinIO)

### 9.1 Today (verified)

- One bucket, `tara-media`.
- Originals at `{kind}/{owner_id}/{asset_id}`; image thumbnails at `{original_key}/thumb.jpg`.
- Every `MediaVariant` row records its own `storage_key`, so a layout change for new rows does not break old rows.
- Presign TTL is 900 s. Signing uses the root credentials.

### 9.2 Target key layout (**decision**: per-asset prefix)

Every derived file lives under its asset's prefix. Deleting an asset means deleting one prefix, and existing thumbnails already follow this pattern.

| Object | Key | Produced by | Visibility |
|---|---|---|---|
| staging upload (new, roadmap 1.5) | `staging/{asset_id}` | browser presigned PUT | private; `complete` verifies it, copies it to the original key and deletes it, so the presigned PUT (valid 900 s, not revocable) can never change a verified object; leftovers are deleted by the stale-upload reaper |
| original upload | `{kind}/{owner_id}/{asset_id}` (unchanged) | media `complete` (copy from staging) | asset visibility; originals of all content media (posts, stories, group posts, chat, listings, video, reels, CVs and receipts) are **private** |
| image thumbnail (320) | `…/thumb.jpg` (exists) | media worker | as asset |
| image preview (1280) | `…/preview_1280.webp` | media worker | as asset |
| re-encoded display image (EXIF/GPS removed) | `…/display.jpg` (or the original rewritten in place) | media worker | as asset |
| posters | `…/poster/{idx}-{width}.webp`, widths 320 / 640 / 1280 (one ladder for Video and Reels; **decision**) | video worker | as asset (custom thumbnails uploaded **private**) |
| HLS (long-form video) | `…/hls/master.m3u8`, `…/hls/{label}/index.m3u8` + segments | video worker | private; served only through the token playlist endpoint |
| reel MP4 renditions | `…/mp4/720p.mp4`, `…/mp4/480p.mp4` (`+faststart`) | video worker | private; presigned per viewer |
| audio-only track | `…/audio.m4a` | video worker | private |
| waveform | `…/waveform.json` (64 normalized peaks) | video or voice worker | as asset |
| caption | separate asset `caption/{owner_id}/{asset_id}` + `…/caption.vtt` (normalized) | caption task | as linked reel / video |
| reel rendered with sound | separate asset, `purpose=reel_render` | render task | private |
| sound | separate asset, `purpose=sound`, **copied** out of the origin reel | sound task | public audio |
| CV / certificate / ad receipt PDF | `file/{owner_id}/{asset_id}` | browser | private; served with `Content-Disposition: attachment` |

**Note:** presigned URLs include the key, and therefore the uploader's `owner_id`. That is acceptable for public content. Private keys should never appear in a URL served to someone who is not allowed to see the owner. Later: prefix-hash the owner, **unverified** whether this is needed.

### 9.3 Renditions

| Content | Ladder | Codec / container | Notes |
|---|---|---|---|
| Long-form video (Module 3) | 240p 400k, 360p 800k, 480p 1.4M, 720p 2.8M; 1080p 5M only when `VIDEO_MAX_RENDITION=1080` (default 720) | H.264 veryfast CRF + maxrate / bufsize, closed 2 s GOP, `-sc_threshold 0`, AAC 128k, HLS VOD 6 s segments | Never upscale. Strip all metadata (`-map_metadata -1`). Prefer single-file byte-range or fMP4 renditions, so a rendition needs one presigned URL instead of hundreds (verifier). |
| Reels (Module 4) | 720p (maxrate 2.2M), 480p (1M) | H.264 High yuv420p, CRF 23, GOP 48, AAC 96 to 128k, MP4 `+faststart` | Progressive MP4 in v1, no HLS. Tone-map HDR iPhone HEVC (HLG / PQ) before conversion to SDR. |
| Images | thumb 320, preview 1280, optional 400 / 800 / 1200 / 1600 WebP ladder | JPEG / WebP q82 | Apply `exif_transpose` first. Pixel cap about 24 MP; use `draft()` decoding to fit the 256m worker. Write the variant row only after the S3 write succeeds. |
| Voice / audio | original plus optional waveform | as uploaded (mp4 / webm / ogg; signature-checked) | no transcoding in v1 |

### 9.4 Access model

- **Who signs:** only media creates presigned URLs. Other services store `media_id` and ask media for URLs through the internal batch endpoint (roadmap 1.5), **after** their own visibility check: post for posts, stories and group posts (audience, close friends, blocks, group membership, story expiry) [1.5, 1.9, 1.11]; chat for conversation membership and that the attachment belongs to the conversation [3.2]; marketplace for `listing_visible_to` [4.2]; careers for recruiter CV access [7.2]. `GET /media/<id>/` serves only public assets (avatars, covers, public-group images, sounds) and the owner's own files.
- **TTL:** 900 s by default. HLS playlist tokens live at most 6 h, but segment URLs are presigned with a **fixed time bucket** (for example the end of the current 30-minute window), so a cached playlist never hands out URLs that outlive a revocation.
- **Revocation and holds:** `moderation_hold_at` blocks delivery to everyone except the owner and moderators, and prevents deletion. `legal_hold_until` keeps evidence through appeals and legal requests. Moderation and post-deletion events set these through the media consumer.
- **Upload checks (roadmap 1.5 unless noted):**
  - MIME allow-list per kind
  - magic bytes: `ftyp` brand allow-list for MP4 / MOV, EBML for WebM, `OggS`, `%PDF-` (today `validation.matches_signature` returns true for every video and audio type)
  - real size recorded and compared with per-kind caps
  - upload to a staging key, then copy to the original key at `complete`; the ETag of the copied object is stored, and processing fails if it changes
  - `scan_status` must be `clean` for CVs, receipts, creatives and chat files. This needs a real scanner: today `tasks.py` sets `clean` without scanning. Roadmap 3.10 adds a clamd `media-scanner`, a `media.scan` task and a quarantine state (`infected` assets are private and never delivered). If the product owner chooses manual review instead (roadmap §21, decision 12), this rule becomes "reviewed by staff, always served with `Content-Disposition: attachment`", and this line must be changed to say so.
- **Edge headers:** the nginx `/tara-media/` location must carry a sandbox CSP and `nosniff`. Re-declare **all** server-level security headers there, because adding any `add_header` in a location drops the inherited ones.

### 9.5 Lifecycle and backup

| Rule | Job |
|---|---|
| uploads still `uploading` after 24 h: delete object and row | `media.reap_stale_uploads` (hourly) |
| user-deleted assets: delete objects after 7 days | `media.purge_deleted` (daily) |
| moderation-removed assets: keep 90 days (or longer under legal hold), then delete | same |
| reel originals: delete 7 days after a successful transcode (renditions kept); keep for long-form video is an open decision | same |
| HLS / MP4 renditions: regenerable, so **exclude from backup**; back up originals and posters | `scripts/backup.sh` (needs a prefix filter) |

Purges delete keys explicitly. A MinIO prefix lifecycle rule cannot tell an original from its derived files, because they share a prefix.

### 9.6 Credentials (verifier blocker)

| Principal | Access |
|---|---|
| media web + media worker | read / write the bucket (scoped user, not root) |
| media-video-worker (ffmpeg) | read originals, write derived prefixes, nothing else; **no** `INTERNAL_JWT_SECRET`, no RabbitMQ admin, no `media_db` write. It reports results by enqueueing a finalize task that the trusted media worker runs. |
| root credentials | bucket administration only |

---

## 10. Current schema defects to fix before building on them

All are **verified** by the area audits or the verifiers. Each maps to the roadmap milestone that fixes it (§7.2).

| Defect | Where | Effect | Milestone |
|---|---|---|---|
| Child tables lack `created_at` but the default paginator orders by it | `services/profile/profiles/models.py`, `views.py` | GET links / education / work returns 500 | 2.1 |
| `display_name` 80 in profile vs 120 at registration | `profiles/models.py`, identity `serializers.py` | profile creation dead-letters; the account has no profile | 2.1 |
| `Post.audience` max_length 12 | `services/post/posts/models.py` | `close_friends` cannot be stored | 1.9 |
| `MediaAsset.bytes` is the declared size | `media_app/services.py` | quotas and CV caps can be bypassed | 1.5 |
| Content media public by default, readable by any signed-in user; originals keep GPS EXIF | `media_app/services.py` (`_can_view`), `frontend/web/src/services/media.ts` | friends-only, close-friends and private-group media leak | 1.5 |
| No signature check for video and audio; presigned PUT reusable after `complete` | `media_app/validation.py`, `services.py` | arbitrary files hosted as "video" | 1.5 |
| `scan_status` set to `clean` without a scan | `media_app/tasks.py` | the scan-clean rule is meaningless | 3.10 |
| Thumbnail variant saved as 320×320 whatever its shape | `media_app/tasks.py` | wrong layout data | 5.2 |
| No unique key on `media_variant` | `media_app/models.py` | duplicate variants under task redelivery | 1.5 |
| `edit_post` ignores moderation removal | `posts/services.py` | removed posts get re-indexed | 1.1 |
| Hashtags indexed from private posts | `searchsvc/handlers.py` | privacy leak | 1.1 |
| `Post.ModerationStatus.PENDING` not hidden by `is_visible` | `posts/models.py` | holds would not hide content | 8.9 |
| ads per-impression rounding; cpm and cpc both charged; overspend | `ads/services.py` | wrong money | 6.1 (serving off from 1.0b until 6.3) |
| moderation `assign()` reopens resolved cases; `take_action()` re-actions them | `moderation/services.py` | broken audit trail, duplicate events | 1.2 |
| non-null `actor_id` everywhere | admin `AuditLog`, `ModerationAction`, `ModerationAuditLog` | system-originated actions cannot be audited | 8.1 |
| `listing.price` NOT NULL default 0 | `marketplace/models.py` | "free" and "on request" cannot be told apart | 4.3 (with `classify_zero_price_listings`) |
| No retention anywhere | notification, ads, admin, feed | unbounded tables | with each owning milestone (2.17, 6.7, 8.11, 1.7) |

---

## 11. Open decisions and unverified items

**Decisions to sign off** (all rows of §5, plus):

1. **Age data in identity.** Scheduled in roadmap 2.12: a birth date or an age attestation, under its own consent text. Age leaves identity only as `is_minor` and `age_band` token claims, with no event (§4.1). Still to sign off: the minimum age per market and the wording (roadmap §21, decision 5).
2. **Account lifecycle events.** `account.deleted`, `account.deactivated` and `account.updated` need a contract, plus an erasure consumer in every service. They are now scheduled as roadmap L.5, before public launch. Without them, no module can meet erasure or data-export obligations (Egypt PDPL 151/2020; GDPR if EU users are served).
3. **Retention periods** for messages, moderation snapshots and audit logs need legal review (Egypt, KSA, UAE).
4. **chat search index type:** plain GIN trigram vs `btree_gin` composite. `btree_gin` must be confirmed as trusted on the deployed image.
5. **`redis-hot`:** created in roadmap 1.7 for ranking sessions; its memory size is set after the reels load test (roadmap §21, decision 13).
6. **Keep or delete long-form video originals after transcoding** (re-encode ability vs storage cost).
7. **Telemetry ownership:** video stats in feed next to reels (§5 row 6).
8. **Partition thresholds** in §8.2.
9. **File scanning:** a clamd sidecar (roadmap 3.10) or manual review plus forced download (roadmap §21, decision 12). §9.4 follows the choice.

**Unverified items:**

- Arabic trigram extraction on each database's ctype (`show_trgm`).
- That `btree_gin` is trusted.
- The connection count estimate in §8.7.
- The partition-threshold numbers.
- The storage cost per reel (about 25 MB of renditions, from the Reels design) and the long-form ladder cost (about 2 to 2.5× the source, from the Video design). Both are design estimates, not measurements.
- Whether `scripts/backup.sh` can filter MinIO prefixes.
- Every number of the form "about N" above.

---

## Appendix A: QTech patterns reused at the data layer (reference only)

QTech is read-only. Only these ideas are carried over, each re-implemented in Tara with the corrections noted:

| Pattern | QTech source | Tara use |
|---|---|---|
| Two managers: `objects` hides soft-deleted rows, `all_objects` sees all, with `default_manager_name` and `base_manager_name` set to `all_objects` | `backend/accounts/managers.py`, `accounts/models.py` | `UserProfile` (§4.2) |
| Exactly-one-target `CheckConstraint` for polymorphic rows | `backend/cms/models.py` (`ProjectNote`) | ads creative format checks; seller kind checks |
| A unique business number must not come from a post-save UPDATE on a blank unique column | `backend/billing/models.py` (`Invoice`) | Postgres sequences for orders and statements |
| Presence ZSET heartbeat with per-socket reference counting | `backend/core/realtime.py` | realtime `presence:sock:<id>` ZSET per account (§4.8), which fixes QTech's counter drift after a crash |
| Arabic letter folding (`_norm`) | `backend/core/chatbot.py` | `libs/tara_common` normalizer, hardened (§8.5) |
| Image rendition guards: no upscale, `exif_transpose`, pixel cap, fixed width ladder | `backend/core/images.py` | media worker (§9.3) |
| Versioned-namespace cache invalidation | `backend/core/cache.py` | ranking and suggestion caches; the version starts from `time_ns`, because QTech resets it to 1 when the key is evicted |
| UTF-8 BOM CSV export | `backend/core/export.py` | audit and ads exports, with formula-injection escaping added |
