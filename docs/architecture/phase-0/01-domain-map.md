# 01 — Domain Map

This document defines the **bounded contexts**, their core concepts, and how
they relate. Contexts are the unit of ownership: each maps to one service and
one database (see docs 02 and 05).

## 1. Context map (text diagram)

```
                                  ┌─────────────────────┐
                          (edge)  │  API Gateway / BFF  │
                                  └──────────┬──────────┘
            ┌──────────────┬──────────────┬──┴───────────┬──────────────┐
            ▼              ▼              ▼               ▼              ▼
      ┌──────────┐  ┌────────────┐  ┌──────────┐   ┌──────────┐  ┌────────────┐
      │ Identity │  │  Profile   │  │  Social  │   │  Posts   │  │   Feed     │
      │          │  │ (+ Pages)  │  │  Graph   │   │          │  │            │
      └────┬─────┘  └─────┬──────┘  └────┬─────┘   └────┬─────┘  └─────┬──────┘
           │              │              │              │              │
           │   ┌──────────┴──────────────┴──────────────┴──────────────┴────────┐
           │   │                    EVENT BUS  (outbox → broker)                  │
           │   └──┬───────────┬───────────┬───────────┬───────────┬───────────┬──┘
           │      ▼           ▼           ▼           ▼           ▼           ▼
        ┌──┴───┐ ┌──────┐ ┌────────┐ ┌────────────┐ ┌────────┐ ┌──────────┐ ┌─────────┐
        │ Chat │ │Media │ │ Search │ │Notification│ │ Market │ │Moderation│ │Analytics│
        └──┬───┘ └──────┘ └────────┘ └────────────┘ │ place  │ └──────────┘ └─────────┘
           │                                         └────────┘
           ▼                                ┌──────────┐  ┌───────┐  ┌───────┐
    ┌──────────────┐                        │ Realtime │  │  Ads  │  │ Admin │
    │   Realtime   │◀── Redis pub/sub ──────│ Gateway  │  └───────┘  └───────┘
    │   Gateway    │     + event bus        └──────────┘
    └──────────────┘
```

- **Solid top edges** = synchronous REST calls via the gateway (read-time).
- **Event bus** = asynchronous, the default for cross-context writes.
- No context reaches into another's database. Ever.

## 2. Bounded contexts & ubiquitous language

### 2.1 Identity (Core)
The single source of truth for *who a user is* and *how they authenticate*.
- **Aggregates:** Account, Session, RefreshToken, Device, SecurityEvent,
  EmailVerification, PasswordReset.
- **Language:** *register, verify, login, rotate, revoke, suspend, recover*.
- **Owns:** credentials, account status, tokens, device sessions, security log.
- **Publishes:** `account.registered`, `account.verified`, `account.suspended`,
  `session.created`, `session.revoked`.
- **Never owns:** profile content, social relationships, posts.

### 2.2 Profile & Pages (Supporting)
The public presentation layer of an Account, plus managed Pages.
- **Aggregates:** UserProfile, ProfileFieldPrivacy, UserLink, UserEducation,
  UserWorkExperience, Page, PageMember, PageRole.
- **Language:** *handle, display name, bio, intro, cover, visibility,
  field privacy, page role (owner/admin/editor/moderator/advertiser/analyst)*.
- **Owns:** handle uniqueness, profile fields & their per-field privacy, Pages
  and Page membership/roles.
- **Consumes:** `account.registered` (to create an empty profile),
  `account.suspended` (to restrict visibility).
- **Publishes:** `profile.updated`, `page.created`, `page.member.changed`.

### 2.3 Social Graph (Core)
All relationships between Accounts (and Account→Page follows).
- **Aggregates:** Friendship, FollowRelation, BlockRelation, CloseFriendRelation,
  SocialSuggestion (cache).
- **Language:** *request, accept, reject, cancel, unfriend, follow, unfollow,
  block, restrict, mutual, suggestion*.
- **Invariants:** a Friendship is symmetric and unique per unordered pair;
  a Follow is unique per (follower, target); a Block forbids friend/follow/
  message/tag/visibility between the pair.
- **Publishes:** `friendship.requested/accepted/removed`, `user.followed/
  unfollowed`, `user.blocked/unblocked`.
- **Consumes:** `account.suspended` (cascade restrictions).

### 2.4 Posts (Core)
Authored content and its direct interactions.
- **Aggregates:** Post (root), PostMedia (ref), Comment, CommentReaction,
  PostReaction, Share, Mention, Hashtag, SavedItem, SavedCollection.
- **Language:** *draft, publish, audience (public/friends/followers/only-me/
  custom/page/group), react, comment, reply, mention, hashtag, share, save*.
- **Owns:** post lifecycle, comments/replies tree, reactions, saves, shares.
- **Consumes:** `user.blocked` (hide content), media-ready events.
- **Publishes:** `post.created/updated/deleted`, `post.reacted`,
  `post.commented`, `comment.replied`, `post.shared`, `post.reported`.

### 2.5 Feed (Core)
The reader's stream. Owns *no source-of-truth content* — it composes references.
- **Aggregates:** FeedItem, FeedCursor, FeedRankingSignal (all derived).
- **Language:** *home/following/friends/page feed, fan-out (on-write/on-read),
  rank, cursor, hot feed, new-post indicator*.
- **Consumes:** `post.created` (+ graph relationships, follows) to fan out.
- **Strategy:** fan-out-on-write for normal accounts; fan-out-on-read for
  high-follower ("celebrity") accounts. Eventual consistency is acceptable.
- **Publishes:** `feed.item.added` (for real-time new-post indicators).

### 2.6 Media (Supporting)
Binary asset lifecycle, decoupled from any content type.
- **Aggregates:** MediaAsset, MediaVariant (thumbnails/transcodes/waveform),
  UploadSession.
- **Language:** *signed upload/download URL, variant, transcode, thumbnail,
  waveform, virus-scan hook, lifecycle/expiry*.
- **Owns:** the only context that talks to object storage; produces variants
  asynchronously.
- **Publishes:** `media.uploaded`, `media.processed`, `media.failed`.
- **Resilience:** if processing fails, the original is preserved and a
  `media.failed` event lets owners show a retry state.

### 2.7 Chat (Core)
Messaging state-of-record (NOT the socket transport).
- **Aggregates:** Conversation, ConversationMember, Message, MessageAttachment,
  MessageReaction, MessageReadReceipt, MessageDeliveryReceipt, ConversationMute,
  PinnedMessage.
- **Language:** *DM, group, conversation, message, reply, react, voice note,
  read/delivery receipt, mute, pin, retention*.
- **Owns:** conversation membership & authorization, message persistence.
- **Consumes:** `user.blocked` (block handling), `media.processed` (voice/file).
- **Publishes:** `message.created`, `message.read`, `message.reacted`,
  `conversation.member.changed`.

### 2.8 Realtime Gateway (Infrastructure)
Stateless-ish WebSocket fan-out edge. Holds **no source of truth**.
- **Language:** *connect, authenticate channel, subscribe, presence, typing,
  backpressure, reconnect, fallback-to-poll*.
- **Owns:** socket connections, presence cache (Redis), typing cache.
- **Bridges:** event bus / Redis pub-sub → connected clients. Critical state
  always lives in Chat/Notification/Feed, never only in a socket node.

### 2.9 Notification (Supporting)
Multi-channel delivery of user-facing notifications.
- **Aggregates:** Notification, NotificationPreference, PushDeviceToken,
  NotificationDeliveryLog.
- **Language:** *in-app, web push, mobile push, email, preference, grouping,
  quiet hours, read/unread, retry, dead-letter*.
- **Consumes:** virtually every domain event (reactions, comments, follows,
  messages, moderation, listings…).
- **Resilience:** failures retry with backoff → DLQ; never block the source action.

### 2.10 Marketplace (Core)
Commerce listings and discovery.
- **Aggregates:** MarketplaceCategory, Listing, ListingMedia, ListingSave,
  ListingReport, SellerProfile, ListingConversationLink.
- **Language:** *listing, category, condition, price, currency, status
  (draft/pending_review/active/reserved/sold/rejected/archived), save,
  sponsored, fraud hook*.
- **Consumes:** `media.processed`, `moderation.actioned`.
- **Publishes:** `listing.created/updated`, `listing.status.changed`,
  `listing.reported`. Buyer/seller chat is created **in Chat** via an event.

### 2.11 Advertisement (Supporting)
Monetization foundation.
- **Aggregates:** AdvertiserAccount, Campaign, AdSet, AdCreative, AdPlacement,
  AdImpressionEvent, AdClickEvent, AdReview, AdBudgetLedger.
- **Language:** *advertiser, campaign, ad set, creative, budget, targeting,
  placement, impression, click, review, frequency cap, sponsored*.
- **Consumes:** review decisions; emits sponsored items the Feed/Marketplace
  *optionally* blend in. **Ads failing must never block organic content.**
- **Publishes:** `ad.impression.recorded`, `ad.click.recorded`,
  `ad.review.decided`. High-volume events go to the analytics firehose.

### 2.12 Search (Supporting)
Read-optimized discovery index. **Derived data only.**
- **Language:** *index, document, query, autocomplete, filter, rank, reindex*.
- **Consumes:** create/update/delete events from Profile, Pages, Posts,
  Marketplace to keep indices in sync.
- **Resilience:** if down, core browsing + category navigation still work
  (gateway falls back to DB queries / cached lists).

### 2.13 Moderation (Supporting)
Trust & safety workflows.
- **Aggregates:** Report, ModerationCase, ModerationAction, Appeal,
  ContentPolicy, ModerationAuditLog.
- **Language:** *report, case, queue, action, warning, removal, shadow-restrict,
  appeal, audit, policy*.
- **Consumes:** `*.reported` events from every content context.
- **Publishes:** `moderation.actioned` (others react: hide content, restrict user).

### 2.14 Admin (Supporting)
Operator console & platform configuration.
- **Aggregates:** (mostly read models) + FeatureFlag, configuration.
- **Language:** *user mgmt, role/permission, dashboards, feature flag, service
  health, config*.
- **Reads** across contexts via their APIs/read models; **writes** flags & config.

### 2.15 Analytics (Supporting)
Asynchronous metrics & insights. **Never on a user-facing critical path.**
- **Language:** *event ingest, aggregation, insight, dashboard metric*.
- **Consumes:** the firehose of domain + ad events; produces aggregates.

### 2.16 System / Platform (cross-cutting, shared library + per-DB tables)
Not a deployable service — a **shared kernel**: AuditLog, OutboxEvent,
IdempotencyRecord, FeatureFlag, ServiceHealthSnapshot, the event envelope,
error format, pagination, auth middleware, and the `EventPublisher` abstraction.
Lives in `libs/` and is imported by every service. Kept deliberately thin.

## 3. Context relationship patterns (DDD)

| Upstream → Downstream | Pattern | Why |
|-----------------------|---------|-----|
| Identity → all | **Upstream/Shared Kernel (auth)** | Everyone trusts signed tokens issued by Identity. |
| Profile → Posts/Feed/Chat/Market | **Customer/Supplier** | They need display data; Profile publishes a public read model. |
| Social Graph → Feed | **Customer/Supplier** | Feed depends on follow/friend edges; consumed via events + read API. |
| Posts → Feed/Search/Notification | **Published Language (events)** | Fan-out, indexing, notifications all event-driven. |
| Media → everything | **Open Host Service** | Stable signed-URL API + events; one storage owner. |
| Marketplace ↔ Chat | **Published Language (events)** | Listing event triggers a conversation; no direct coupling. |
| Ads → Feed/Marketplace | **Anti-Corruption Layer** | Feed blends sponsored items behind a tolerant adapter; ad outage = skip. |
| Moderation → content contexts | **Published Language (events)** | `moderation.actioned` drives hide/restrict in each owner. |

## 4. Consistency expectations

- **Strong consistency** within a context (single DB, ACID): auth, post
  creation, conversation membership, listing status transitions.
- **Eventual consistency** across contexts: feed fan-out, search indices,
  notifications, analytics, suggestion caches. The UI is designed to tolerate
  this (optimistic updates + new-content indicators).
