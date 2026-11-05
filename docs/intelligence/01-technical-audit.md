# Tara Intelligence 01: consolidated technical audit

Phase 1 of [00-master-spec.md](00-master-spec.md). Written on 2026-11-05. Four area audits were merged here: feed, content, graph and platform.

**How it was done.**
- The code was read at `HEAD` 4f105f9 on branch `feat/web-social-platform`, and every line reference was re-checked against `HEAD` 0483ae3 plus the working tree after a critic review. Other agents were editing the working tree at the same time, so line numbers in `services/post/posts/services.py`, `views.py`, `serializers.py`, `saved.py` and `services/post/reels/services.py` can drift by about 60 lines.
- Every row count was measured read-only in the local dev databases (container `tara-postgres-1`). **The dev data keeps growing** (the seed and the integration suites add rows), so every count in this document carries its measurement time, and no acceptance criterion in [04](04-implementation-plan.md) hard-codes a dev count: they compare against counts queried at run time.
- Those databases hold a **synthetic seed**: about 120 seeded users (760 accounts in total including integration-test accounts at the first pass, 795 at 15:51 UTC) and 2,275 posts at the first pass (2,354 at 15:51 UTC). Every post timestamp falls between 2026-11-03 00:17 and the measurement time.
- Tests were counted, not run. The feed container has no `pytest`. A baseline run is the entry gate of phase 2 (see [04](04-implementation-plan.md), WP 2.0).

**Status legend.**
- **exists**: it works end to end today.
- **partial**: some of it exists, or it exists for only one surface.
- **missing**: nothing usable exists.

---

## 1. Executive summary

1. **Only one ranker exists, and it serves only the Home "For you" mode.** It is a linear heuristic with hard-coded constants (`services/feed/feed/ranking.py:48-56`) over freshness, the reason for the feed row, favorites, `Affinity` and `PostStats` engagement. It ranks only the viewer's own fan-out rows: there is no candidate source outside friends and follows (`ranking.py:21-24`).
   - Reels (`services/post/reels/services.py:385`, the end of `feed_queryset` at 369-385), long video (`posts/services.py:826-840`) and marketplace (`marketplace/views.py:42-47`) are all chronological or sorted by a column.
   - People, page and group suggestions are three separate recommenders with hard-coded ordering. Two are in graph (`graph/suggestions.py:63-191`) and one is in profile (`profile/groups/services.py:933-984`).
2. **There is no behavioural telemetry**:
   - no impressions, opens or watch time;
   - no skips or profile visits;
   - no surface, session or position field anywhere.

   The only per-viewer view rows are `reel_view` (one per day, no duration) and `story_view`. The only impression table on the platform is in ads (`ad_impression_event`, 344 rows, with a coarse `viewer_bucket`).
3. **Several signals are carried and then dropped, or never emitted:**
   - `hashtags` are in `post.created`, but feed drops them (`feed/services.py:59-69`).
   - Saves emit no event (`posts/saved.py:9`).
   - A reaction-type change emits nothing (`posts/services.py:942-960`).
   - Reel hides, story views and poll votes are local rows only.
4. **Eligibility is mostly correct but incomplete:**
   - Block, mute, hide, snooze and deactivation are enforced (`ranking.py:66-75`, `handlers.py:50-56`).
   - Visibility is re-checked at hydration (`/posts/batch/`).
   - **Group posts never reach Home**, because `audience="group"` falls through to author-only (`feed/services.py:96-99`; measured at 15:51 UTC: 91 group posts in `post_db`, and the 72 group-audience `feed_item` rows are all `reason=self`).
   - Authors capped by `FANOUT_MAX_RECIPIENTS=5000` silently lose their extra recipients. The cut keeps the author, then friends sorted by UUID, then followers sorted by UUID (`feed/services.py:176-182`), and it is only logged: nothing records which followers were dropped.
   - A new follow does not backfill posts.
   - Graph ignores account deactivation and suspension, so people suggestions can return inactive accounts.
   - **Account-level moderation is not enforced anywhere downstream.** Moderation can `restrict` or `shadow` a user (`moderation/services.py:36`), and `moderation.actioned` carries `target_type=user` and `target_id`, but no service except notification reads it (`grep shadow` over `services/` finds only moderation and notification). An overturned `restrict` or `shadow` emits nothing (`moderation/services.py:44-62`, `REVERSALS` covers content removals only).
   - **Group posts waiting for approval and posts of non-published pages** are hidden by post (`posts/services.py:185`, `approval_state=pending` is visible only to the author and the group's staff; `:103-104`, `_page_visible`), but feed has no copy of either state. At 15:51 UTC dev has 28 draft pages that authored 28 posts.
   - **Reels taken off the reels surfaces by the reconcile job** (`media_missing`, `media_failed`, `media_elsewhere`) change `publish_state` with no event (`reels/reconcile.py:102-112`).
5. **No topic, language or interest model exists:**
   - Hashtags cover 25.5% of posts (581 of 2,275).
   - `Group.category` is the only controlled vocabulary (18 values), and 94 of 100 dev groups are `general`.
   - `Page.category` is free text (Bookshop 69, مطاعم 46, blank 41, ...).
   - `Account.language` is the UI locale, has no reader, and is never re-emitted after registration.
6. **The platform pieces that can be reused:**
   - the transactional outbox and RabbitMQ (`libs/tara_events`);
   - a feature-flag table with `rollout_pct` and an unused `targeting` field (`services/admin/adminsvc/models.py:11-21`);
   - an FNV-1a client bucketer (`frontend/web/src/stores/flags.ts:26-35`: it hashes `${accountId}:${key}` and folds `% 100`);
   - a cross-service audit log (`AuditEntry`, `adminsvc/models.py:61-104`);
   - capability-based RBAC with an `analyst` role that today holds **no** capability (`libs/tara_common/tara_common/capabilities.py:58-64`);
   - `django-prometheus` in every service;
   - a separate `redis-hot` for ranking sessions.

   No ML library, LLM client or analytics store exists anywhere. A grep for `openai|anthropic|ollama|sklearn|torch` across `services/` and `libs/` returns nothing.

---

## 2. Requirement status matrix

### 2.1 Stage 1: inventory (candidate sources)

| Requirement | Status | Evidence | Gap |
|---|---|---|---|
| Friends' posts | exists | Fan-out on write writes `FeedItem(reason=friend)` (`feed/services.py:154-224`, graph `fanout/`). 21,077 rows | Cap of 5,000 recipients with no fan-out-on-read (`settings.py:114`) |
| Followed users | exists | `reason=follow`, 16,127 rows; `FollowEdge` | No backfill on `user.followed` (`handlers.py:37-47`). `FollowEdge` drift: 1,439 vs 1,469 in graph at the first pass (2,291 feed `follow_edge` rows vs 2,315 graph `follow_relation` rows at 15:51 UTC, users and pages together) |
| Followed pages | exists | Page fan-out (`_recipients`, `services.py:92-112`). 824 page follow edges in sync | n/a |
| Joined groups | **missing** | `post` forces `audience="group"` (`posts/models.py:20`), and feed treats it as unknown | Feed does not consume `group.member.changed`. No membership read model |
| Public communities | missing | Group suggestions only (`profile/groups/services.py:933-984`) | No group-content candidate pool |
| Recommended users, pages and groups | partial | PYMK (`graph/suggestions.py:63-153`), pages by follower count (`:156-191`), group suggestions | Hard-coded ordering. No interest, quality or config. Inactive accounts not excluded |
| Public posts (non-connections) | missing in feed | Search indexes public posts (`SearchDocument`, 1,812 rows), but they are not used as candidates | No public pool inside feed |
| Videos | partial | `GET /posts/?type=video`, newest first (`posts/services.py:826-840`) | No ranking. No `(type, created_at)` index |
| Reels | partial | `GET /reels/?tab=for_you` returns public, friends' and followed reels, newest first (`reels/services.py:369-385`) | No scoring. Watched reels are not demoted. Reels hidden by the reconcile job leave no event (`reels/reconcile.py:102-112`) |
| Trending | partial | `search/history.py:139-151` counts distinct authors per tag over a day or week, live GROUP BY, uncached | No velocity. Not used as a candidate source |
| Multiple content types | exists (fan-out) | text 1,374, image 323, share 316, video 120, reel 101, poll 41 | Type plays no part in ranking |
| Eligibility before ranking | partial | `visible_items` covers hide, snooze, mute and deactivated (`ranking.py:66-75`). Blocks delete rows (`handlers.py:50-56`). Audience is checked at fan-out | Current audience is re-checked only **after** ranking, at hydration, so a ranked slot can hydrate to nothing (`frontend/web/src/services/feed.ts:42,90-95`, `MAX_EMPTY_PAGES=10`). Nothing handles report-pending content. No age gating. Feed has no copy of group `approval_state`, page `status`, reel `publish_state` or account `restrict`/`shadow` |

### 2.2 Stage 2: signals

| Signal | Status | Evidence | Gap |
|---|---|---|---|
| Follows and friendships | exists | graph `FollowRelation` (2,293) and `Friendship` (1,643 accepted). Feed has `FollowEdge` | Feed has no friend-edge table: friendship reaches feed only as a fan-out label |
| Likes | exists | `PostReaction` (9,099), `post.reacted` / `post.unreacted`, feed `PostStats` and `Affinity` | A type change sends no event. History is lost on unreact |
| Comments | exists | `Comment` (3,741, of which 420 are replies), `post.commented` / `comment.replied` | No quality measure for a "meaningful" discussion |
| Shares | exists | `Share` (316), `post.shared` | Only reshare is recorded: link copies and sends in chat are not. No `share.account_id` index |
| Saves | partial | `SavedItem` (643) | No event (`saved.py:9`). Unsave deletes the row |
| Post clicks / opens | missing | `PostDetailView` (`posts/views.py:176`) logs nothing | No telemetry |
| Profile visits | missing | n/a | n/a |
| Search interests | partial | `RecentSearch` (6 rows), at most 20 kept per account | No consent or retention policy. Not used |
| Watch duration, completion, rewatch, skip | missing | `ReelPlayer.vue:148-152` computes progress only for the UI. HLS segments are presigned, so the server never sees playback (`media_app/playback.py:11-17`) | Must be reported by the client and validated on the server |
| Hides | partial | Feed `post_hide` (139, with reasons), `author_snooze` (0), reels `ReelHide` (26) | No events. Reel hides never generalize. `not_interested` carries no topic signal (`test_hide_rank.py:240`) |
| Reports | exists for moderation | `PostReport` (9), `post.reported` goes to moderation. 40 open cases (post 9, message 29) | Feed does not consume reports, so there is no pending demotion |
| Interested / not interested | partial | Reels: `ReelHide` ("not interested" only) | No positive feedback anywhere |
| Explicit topic preferences | missing | No field. `UserProfile` has no interests (`profile/profiles/models.py:28-56`) | n/a |
| Content: publish date | exists | `Post.created_at` is set at publish time, `FeedItem.post_created_at` | n/a |
| Content: type | exists in the payload | `post.created.type` | Not used in ranking |
| Content: author quality | missing | n/a | No quality score. `SellerProfile.rating_*` exists for marketplace only |
| Content: originality | partial (raw) | `shared_post_id` in `post.created` | No duplicate detection |
| Content: topic and hashtags | partial | `Hashtag` / `PostHashtag` (128 tags, 890 links), with Unicode `\w` (`services.py:49`) | 25.5% coverage. No Arabic normalization of tags. Feed drops them |
| Content: engagement quality | partial | `engagement_score = ln(1+r+2c+3s) − 0.5·ln(1+flags)` (`feed/readmodels.py:33-42`) | Raw counts. No rate per impression and no smoothing |
| Content: meaningful discussion | missing | `reply_count` and the `reply_to` graph exist | Not computed |
| Content: media quality | partial (raw) | `MediaAsset.video_meta.probe`, `MediaVariant` HLS rungs (about 3.05 per video), `media.processed` | Not consumed by feed |
| Content: spam indicators | partial | Hides with reason `spam` / `sexual` bump `PostStats.flags` (0 in dev) | No intake into moderation |
| Content: visibility | exists | `audience`, `moderation_status`, `PostState` | n/a |
| Content: language | missing | No field. Heuristic on the dev data: Arabic in 1,191 posts, Latin-only in 995, empty in 89 | n/a |
| Relationship: past interactions | exists | `Affinity` (3,475 pairs, max 100) | A plain counter: no decay, no per-type weight, no negative interactions |
| Relationship: shared groups | missing in feed | `GroupMember` in `profile_db` (455 active at the first pass, 468 at 15:51 UTC) | No read model |
| Relationship: mutual interests | missing | n/a | No interest model |
| Relationship: meaningful conversations | missing | `comment.replied` carries `parent_author_id` / `root_author_id`. Chat was not audited | Not aggregated |

### 2.3 Stages 3 and 4: predictions and final ranking

| Requirement | Status | Evidence |
|---|---|---|
| P(meaningful engagement), P(like), P(comment), P(share), P(save) | missing | `engagement_score` is a global popularity aggregate, not a probability for the viewer |
| P(video completion), expected watch time | missing | No watch data |
| P(negative feedback) | partial | A per-viewer author penalty: `0.75·min(dislike hides, 3)` (`ranking.py:134`) |
| Interest relevance | missing | n/a |
| Rules designed so ML can replace them | missing | The score is a closure inside `rank_items` (`ranking.py:126-136`) with no prediction interface |
| Final combination of the ten factors | partial | Freshness, relationship, negative feedback and engagement exist. Interests, relevance, quality, diversity, originality and preferences do not |
| Tara's own configurable model | partial | Tara's own, but every weight is a module constant |
| All parameters in one central config | **missing** | Constants are split across `ranking.py:48-56`, `readmodels.py:33-41`, `feedback.py:23` (`SNOOZE_DAYS`), `settings.py:81-82`, `graph/suggestions.py` (`MAX_BRIDGES`) and `groups/services.py` (`MAX_SUGGESTIONS`). None comes from an environment variable or a database |

### 2.4 Separate configuration per surface

| Surface | Status | Evidence |
|---|---|---|
| Home | partial | One heuristic for `for_you` only |
| Reels | missing | Ordered `-created_at, -post_id` (`reels/services.py:385`) |
| Long video | missing | Newest first, filtered after paging |
| Groups | missing | No group candidates in Home. Group suggestions are hard-coded |
| Marketplace | missing | Sorts `newest`, `price_asc` and `price_desc` only. Trigram search exists. `ListingSave` (88) and `ListingInquiry` (70) are unused for ranking |
| Discovery | partial | Three separate suggestion rankers. No content discovery |

### 2.5 Feed modes

| Mode | Status | Evidence |
|---|---|---|
| For You | exists | `mode=for_you`, ranked, with a session (`ranking.py:158-271`) |
| Following | exists | `reason=follow` or `FollowEdge`, minus the viewer's own posts (`services.py:422-442`) |
| Friends | **missing** | It only needs `reason='friend'` |
| Favorites | exists | Active `RelationshipFlag(kind=favorite)` (0 rows in dev) |
| Most Recent | exists | `mode=recent` (the default), `-post_created_at` |
| Switching modes | exists | `HomeView.vue:425` |
| Mode remembered | partial | Only in `localStorage["tara.feedMode"]` (`HomeView.vue:50-78`), per browser. Not stored on the server |

### 2.6 Discovery

| Requirement | Status | Evidence |
|---|---|---|
| Recommends from accounts the user does not follow | missing for content | Exists only for people, pages and groups as entities |
| Factors: interest, quality, author quality, freshness, diversity, exploration, feedback | missing | PYMK uses mutual count only. Pages use popularity only |
| Labelled recommendations | partial | PYMK has `reason` (`mutual` / `follows_you`). Content has none |
| Configurable, A/B-testable ratio (60/30) | missing | No mix, no experiment framework. Flags are bucketed on the client only (`flags.ts`), and the server never evaluates `FeatureFlag.targeting` |

### 2.7 My Algorithm and natural-language preferences

| Requirement | Status | Evidence |
|---|---|---|
| Topics liked, disliked, more of, less of | missing | No topic model |
| Favourite creators and pages | partial | `FavoriteRelation` (`MAX_FAVORITES=30`, `graph/preferences.py:36`). 0 rows |
| Preferred formats, recommendation frequency, discovery preferences, content languages | missing | n/a |
| Settings page | partial | `/feeds/manage` (`FeedPreferencesView.vue`) manages snoozes only |
| Natural language with an optional LLM, validated, with undo | missing | No LLM client anywhere |

### 2.8 Post-menu feedback

| Action | Status | Evidence |
|---|---|---|
| Hide | exists | `POST /api/v1/feed/hide/` with 6 reasons (`feed/models.py:87-93`) |
| Mute author, Unfollow, Block, Report | exists | `PostCard.vue:648-780`. These go to graph, and to post or moderation for reports |
| Snooze (extra) | exists | `POST /feed/snooze/`, 30 days |
| Interested, Show more like this | missing | n/a |
| Not interested, Show less like this | partial | `not_interested` is a hide reason that affects one post only. Reels have `ReelHide` |
| Why am I seeing this? | partial | `WhyThisPost.vue:10-26` shows the reason label and the sort, with no ranking factors |
| Every action stored as an event | **missing** | Hides and snoozes are rows only, with no outbox event |
| Positive feedback boosts ranking, negative reduces it | partial | Negative only (`dislike_creator` / `annoying` down-weight the author) |
| An impression is not interest; a skip is not strong negative feedback | missing (no data) | n/a |

### 2.9 Event tracking

| Requirement | Status | Evidence |
|---|---|---|
| `feed_impression`, `post_open`, `video_start`, `video_progress`, `video_complete`, `video_rewatch`, `video_skip`, `profile_visit`, `interested` | missing | `posts/studio.py:8-9`: "no impressions or reach until a telemetry pipeline exists" |
| `post_like`, `post_comment`, `post_share`, `post_report`, `follow`, `unfollow` | exists as domain events | `post.reacted`, `post.commented`, `post.shared`, `post.reported`, `user.followed`, `user.unfollowed` |
| `post_save`, `post_hide`, `reel_view`, `not_interested` | partial | Stored as rows only, with no event |
| Fields: session, surface, watch duration, feed position | missing | None of them exists anywhere |
| Minimal personal data | partial | The ads impression table uses `viewer_bucket` (`ads/models.py:111-120`) |
| Deduplication | partial | `ProcessedEvent` dedupes the bus. `reel_view` is unique per day |
| No fake watch time | n/a | No watch data exists yet. A zero-second play counts as a reel view today (`reels/services.py:412-425`, `record_view`) |
| Privacy-aware retention | missing | The outbox is purged after 7 days (`libs/tara_events/tara_events/tasks.py:42-47`), which rules it out as an analytics log. `RecentSearch` has no time limit |

### 2.10 Interest profile and cold start

| Requirement | Status | Evidence |
|---|---|---|
| Topics, formats, creators, categories, recent and long-term interests | missing | Only `Affinity` (creator counts, no decay) |
| Explicit preferences kept separate from inferred ones | missing | n/a |
| The user can inspect and edit the profile | missing | n/a |
| Optional onboarding interest picker | missing | n/a |
| Language as a cold-start source | partial | `Account.language` (ar 593, en 167) is sent only in `account.registered`. `PATCH /me/` emits nothing for a language change (`identity/views.py:308-322`) |
| Trending and quality content as cold-start sources | partial | `search` trending (public posts only). No quality score |
| Communities as a cold-start source | partial | Groups ordered by `member_count` |

### 2.11 Quality, integrity, diversity and user control

| Requirement | Status | Evidence |
|---|---|---|
| Demote spam | partial | `PostStats.flags` from hide reasons (`feed/feedback.py:93`) |
| Demote duplicates, misleading content, engagement bait, repeated low quality, manipulated interactions | missing | n/a |
| Demote reported content pending review | missing | Feed ignores `post.reported` and `moderation.actioned` |
| Account-level moderation (`restrict`, `shadow`) | missing downstream | Decided in moderation (`moderation/services.py:36`, hidden from its subject in `account_status.py:23-26`), but no ranking or suggestion code reads it |
| Promote original, useful, quality content | missing | n/a |
| Fair reach for new and small creators; quality separate from popularity | missing | Engagement is a raw count |
| Reports go to moderation and are not proof | exists | `post.reported` opens a moderation case. Removal comes only from `moderation.actioned` followed by `post.deleted` |
| Author, topic and format diversity, exploration, repetition limits | **missing** | No re-ranker. No test covers diversity |
| Users can reduce recommendation intensity | missing | n/a |
| Chronological access always available | exists | `mode=recent` |
| Measure satisfaction and negative feedback | missing | No metrics pipeline |

### 2.12 Ads

| Requirement | Status | Evidence |
|---|---|---|
| Kept separate from organic ranking | exists | One `sponsored` object beside `data`, on the first page only (`feed/views.py:72-76`). No ads term in the score |
| Eligibility, budget, approval | **partial** | Approved creative, active campaign, in schedule, `spent < budget`, matching placement (`ads/services.py:234-252`, `eligible_creatives`). **The brief's payment check is missing:** `eligible_creatives` never reads `AdvertiserAccount.billing_status` (`ads/models.py:20`), and campaigns go active with no funding check. The only guard is a production deploy check that refuses to boot with `ADS_SERVING_ENABLED=true` while `PAYMENT_VERIFICATION_AVAILABLE=False` (`ads/checks.py:16-47`, `ads.E001`). Fixed in [04](04-implementation-plan.md) WP 4.11 |
| Frequency caps | exists | Per-viewer cap |
| Targeting, bid/auction, relevance, ad quality | missing | The newest eligible creative wins |
| Clear Sponsored label | exists | `SponsoredCard.vue:70` («مُموَّل»). Feed returns **one** sponsored object on the first page (`feed/views.py:72-76`). The web renders it at index 4 (`HomeView.vue:526`, `i % 5 === 4`), or in the right rail when the rail is visible |
| No payment influence on organic ranking | exists | Structural: there is no code path between the two |
| Ads impressions and clicks | exists | 344 impressions and 41 clicks across 74 creatives in dev |

### 2.13 Stack, modules, dashboard and tests

| Requirement | Status | Evidence |
|---|---|---|
| DRF, PostgreSQL, Redis, Celery | exists | Every service. Feed has `redis-hot` (128 MB, `noeviction`) |
| scikit-learn | missing | Not in any `requirements.txt` |
| 10 named modules | missing as modules | Pieces exist: `ranking.py` for ranking, `feedback.py` for feedback, `readmodels.py` for signals |
| Proper APIs, caching, pagination, no N+1 | exists for Home | `rank_items` uses 5 queries on the first page and 1 on later pages. The heaviest viewer's candidate query takes about 8.5 ms. Signed opaque cursor |
| Internal dashboard metrics | missing | Admin has `PlatformStat` (live counters only) and `AdminMonitorView.vue` (service health) |
| Ranking config with a change log | missing | `AuditEntry` exists and can receive `intel.config.changed` |
| A/B testing | missing | `FeatureFlag.rollout_pct` is on the client only. In dev the table holds 42 junk `flag_*` rows left by tests, all at 25% |
| Private behaviour hidden from unauthorized admins | partial | Capability RBAC exists, and `admin.users.reveal` requires a reason. The `analyst` role has no capability yet |
| Tests: chronological, negative feedback, blocked, sponsored | exists | 114 feed test functions (`test_feed.py` 55, `test_hide_rank.py` 38, ...) and web `homeFeed.spec.ts` (21) |
| Tests: candidate retrieval beyond connections, diversity, discovery, cold start, preferences, performance, privacy invariant | missing | n/a |
| Synthetic data kept apart from real analytics | missing | The seed writes through the public API (`scripts/seed/seed_dataset.py`), so its reactions land in `post_stats`, `affinity` and `reaction_state` like real ones. Nothing marks synthetic data, and the script has no `TARA_ENV=production` guard |

### 2.14 Visual identity

| Item | Status | Evidence |
|---|---|---|
| "Tara Olive" #64765A / #F8F9F5 | **not adopted** | The shipped palette is Tara Purple #6A00F4 and Neon Violet #A855F7 (`frontend/web/tailwind.config.js:3-24`). This is the owner's decision, see [README.ar.md](README.ar.md) |

---

## 3. Defects and risks found during the audit

These are existing behaviours to fix. The phase listed is where [04](04-implementation-plan.md) fixes each one.

| # | Finding | Evidence | Impact | Phase |
|---|---|---|---|---|
| D1 | Group posts never reach anyone's Home | `feed/services.py:96-99`. 91 group posts, 72 group-audience feed rows, all `self` (15:51 UTC) | Groups are invisible in Home | 3 |
| D2 | Recipients dropped by the celebrity cap never get the post | `settings.py:114`. No fan-out-on-read | A large page loses reach silently | 3 |
| D3 | A new follow shows no existing posts | `handlers.py:37-47` | Following someone feels empty | 3 |
| D4 | A realtime push resets the For You session (plausible, not reproduced) | `HomeView.vue:330-333` calls `first_page`, which replaces the session (`ranking.py:166-173`) | The next scroll falls back to latest order, and every push makes an extra ads call | 4 |
| D5 | People suggestions can return deactivated or suspended accounts | Graph does not consume `account.deactivated` / `account.suspended` | Eligibility leak | 3 |
| D6 | `FollowEdge` drift of 30 rows (2%) | Event-built, so follows made before the read model existed are missing | `following` mode misses authors | 3 |
| D7 | Hashtags dropped from the feed snapshot | `feed/services.py:59-69` | No topic signal in ranking | 2 |
| D8 | Reaction-type change emits no event | `posts/services.py:942-960` | `PostStats` per-type counts drift | 2 |
| D9 | The highest-volume events have no JSON schema | `post.created`, `.reacted`, `.commented`, `.shared`, `.updated`, `.deleted` | Contracts can drift silently | 2 |
| D10 | `redis-hot` at `noeviction` / 128 MB fits about 8k full sessions (16,161 bytes for 500 ids) | `infra/compose/docker-compose.yml:93-97`, Dokploy `docker-compose.dokploy.yml:514` | Above that, sessions fail and the feed falls back to latest order | 4 (session v2) and 13 |
| D11 | No index on `share.account_id` or `post(type, created_at)` | `pg_indexes`. In-flight `posts/migrations/0012_activity_log_idx.py` adds `comment(author_id)` and `post_reaction(account_id)` only | Interest-profile backfill and video listing get slow at scale | 3 |
| D12 | A zero-second play counts as a reel view | `reels/services.py:412-425` | Inflated `view_count` | 2 |
| D13 | Ads serve without a payment check | `ads/services.py:234-252` never reads `billing_status` (`ads/models.py:20`). Production is protected only by the `ads.E001` boot check (`ads/checks.py`) | An unfunded or suspended advertiser can serve wherever serving is on | 4 |
| D14 | `restrict` / `shadow` on an account have no effect on ranking or suggestions, and cannot be lifted by event | `moderation/services.py:36`, `:44-62` (`REVERSALS`) | A shadowed account keeps full reach | 3 |
| D15 | Reels hidden by the reconcile job emit nothing | `reels/reconcile.py:102-112` | A consumer that indexes reels keeps unplayable ones | 2 |
| D16 | The seed script has no production guard | `scripts/seed/seed_dataset.py` (no `TARA_ENV` check) | Seed accounts could be written into a production stack | 2 |

---

## 4. Measured baseline (dev, synthetic)

**First pass, measured 2026-11-05 between about 13:00 and 15:10 UTC at `HEAD` 4f105f9.**

| Store | Fact |
|---|---|
| `feed_db` | 93 MB in total, of which `feed_item` is 75 MB (39,317 rows). 411 recipients (median 225 rows, p90 475). `post_hide` 139. `affinity` 3,475. `follow_edge` 2,269. `processed_event` 19,655 |
| `post_db` | 2,275 posts, 2,113 live (public 1,976). 9,099 reactions. 3,741 comments. 316 shares. 643 saves. 101 reels. 3,943 reel views (all on one day). Outbox 16,274 |
| `graph_db` | 1,643 accepted friendships. 1,469 user follows and 824 page follows. 389 dismissed suggestions. 0 blocks, 3 mutes, 0 favorites |
| `profile_db` | 760 profiles. 240 pages (220 published). 100 groups (94 `general`). 455 active memberships |
| `search_db` | 1,812 public posts indexed. 854 public hashtag links |
| `ads_db` | 74 creatives. 344 impressions. 41 clicks |
| `moderation_db` | 40 open cases (post 9, message 29, user 1, story 1). 26 resolved |
| `redis-hot` | 4 live sessions, 16,161 bytes each for 500 ids, TTL 1800 s |

**Drift check, measured 2026-11-05 15:51 UTC at `HEAD` 0483ae3** (read-only, `docker exec tara-postgres-1 psql`):

| Fact | First pass | 15:51 UTC |
|---|---|---|
| Posts (`post_db.post`) | 2,275 | 2,354 (2,176 live, 1,885 live public) |
| Group posts | 68 | 91 (0 pending approval) |
| Active group memberships | 455 | 468 (plus 32 requested, 19 banned, 1 invited) |
| Graph `friendship` rows | 1,643 accepted | 1,687 rows: 1,658 accepted, 29 pending |
| Graph `follow_relation` / feed `follow_edge` | 2,293 / 2,269 | 2,315 / 2,291 |
| `feed_item` | 39,317 rows, 411 recipients | 39,431 rows, 439 recipients |
| Pages | 240 (220 published) | 266: 238 published, 28 draft. The draft pages authored 28 posts |
| Accounts / accounts without a date of birth | 760 / not measured | 795 / 86 (10.8%) |
| Reels by `publish_state` | 101 | 105, all `published` |

The counts move while other agents run the seed and the integration suites. That is why phase acceptance criteria compare against counts queried at run time.

Several things cannot be evaluated on this dataset:
- **Freshness decay.** All posts are about 63 hours old at most, and 798 of them were created in a single hour.
- **Long-term versus short-term interest.**
- **Retention.**
- **Block, restrict and favorite paths.** There are no rows for them.

Phase 2 adds **backdated synthetic fixtures**, tagged `data_origin=synthetic`. They will never be mixed with real analytics.

---

## 5. Where to extend safely

- **`feed/ranking.rank_items`** is the scoring seam: five batched lookups and a pure score function. Phase 4 turns it into a delegate of the new `intel.ranking.home`. Run with the `home@1` params, the new scorer must reproduce today's formula exactly, and a golden test checks that the ordering is identical.
- **The ranking session is not reusable as is for new sources.** It packs `FeedItem.id` values and re-reads later pages through `_candidates(viewer).filter(id__in=ids)` (`ranking.py:250,267-268`), under one key per viewer, `feed:rank:{viewer}` (`ranking.py:158-159`). Items without a `FeedItem` row would vanish from page 2 on, and two surfaces would overwrite each other. See [02](02-architecture.md), section 22.
- **`feed/readmodels.py` and `feed/handlers.py`** already consume 20 event types idempotently. New read models (content, friend edges, group membership, blocks, topics) belong next to them, because cross-database joins are impossible.
- **`tara_events`** provides the outbox and consumer framework. High-frequency telemetry must **not** go through it one row at a time. The relay (`tara_events/outbox.py:49-97`, `publish_pending`) locks a batch of 200 rows and publishes them one by one, with one `UPDATE` per row inside one transaction. The early estimate of "about 100 events/s per service" was replaced by a measurement in WP 2.0 ([results/phase-02.md](results/phase-02.md)): about **1,370 events/s** to RabbitMQ with publisher confirms and about 2,500 events/s for the database work alone (10,000 rows, feed, dev stack). Either way, telemetry needs its own batched ingestion path; see [02](02-architecture.md), section 12.
- **The admin service** already has `FeatureFlag`, `AuditEntry`, capability RBAC and the admin console shell, so the Intelligence dashboard plugs into it.
