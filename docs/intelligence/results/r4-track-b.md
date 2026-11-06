# R4 Track B: web (My Algorithm, feedback menus, onboarding) and the other services

Branch `feat/web-social-platform`, on top of `e9b68a9` (R3). Not committed and not pushed.
Track A (services/feed, the tara_common helpers and the event schemas) ran in parallel.
This track built against Track A's contracts.

## WPs and where they live

### Services

| WP | Done | Where |
|---|---|---|
| 6.7 identity `account.updated` | yes | `identity/views.py:313-322` (PATCH /me/, same transaction, only when the language changed), `identity/account_center.py:199` `emit_account_updated` (language only), `config/settings.py:226` `IDENTITY_EMIT_ACCOUNT_UPDATED` |
| 7.4 moderation system-sourced case | yes | `moderation/models.py:13` `SYSTEM_REPORTER_ID`, `:25` `Report.source`, `:61` `ModerationCase.system_signal`; `services.py:462` `ingest_system_flag`; `handlers.py:51`; `serializers.py:25` (`reporter_id: null` for system rows); `account_status.py` (My reports: `source=user` only) |
| 8.4-B2 post reels reset | yes | `reels/models.py:93` `ReelsReset`; `reels/services.py:414` (the seen window starts at `reset_at`); `posts/handlers.py:351` |
| 7.5-B2 on reels (extra) | yes | `reels/models.py:108` `ReelsHiddenCreator`, `reels/services.py:399` (for_you leaves out hidden creators unless they are friends or followed), `posts/handlers.py:372` |
| 5.5 graph | yes | `graph/intel_config.py:45` (`discovery@1` defaults with bounds), `:115` `served` (`assign_variant`), `:134` `_expose` (once per account and experiment, outbox, behind the flag), `:173` `apply_published` (newest `published_at`/`version`; other surfaces ignored); models `graph/models.py:286,300`; `social_views.py:87-125` (limits from the config, `meta.variant`) |
| 5.5 profile | yes | `groups/intel_config.py` (same module), `groups/services.py:933-990` (`groups.max_suggestions`, `groups.friend_preview`), `groups/views.py:95-107` (`meta.variant`), `groups/handlers.py:21` |
| 5.5 marketplace | handler and cache only | `marketplace/intel_config.py:47` (no params), `handlers.py:36` |
| 7.5-B2 graph hidden creators | yes | `graph/models.py:263` `HiddenCreator`, `handlers.py:231` (newest wins), `suggestions.py:60,113,209-223` (people and pages) |
| 4b.14 graph part (E9b) | yes | `graph/models.py:53` `AccountRef.age_class` (class only), `graph/age.py:29` (feed's mapping), `:66` capture, `:82` middleware (`config/settings.py:44`); `suggestions.py:184` (only `adult` candidates, fail closed); `social_views.py:101` (minor viewer: no people suggestions, decision 9a) |
| 8.7-B2 search signal | yes | `searchsvc/models.py:177` `SearchSignalOptIn`, `:191` `OutboxEvent`; `signals.py:51` handler logic, `:72` (cache only, no SQL on the search path), `:80` beat re-warm, `:88` `record_query` (term keys only); `views.py:76` (first page with a query); `handlers.py:288`; `config/celery.py`, `CELERY_BEAT_SCHEDULE` |

### Web (frontend/web)

| WP | Where |
|---|---|
| Typed clients | `src/services/feed.ts`: types from `FEED_FORMATS` on; `itemTopics` `:294`; clients `:468-540` (preferences PATCH with version, undo, profile, topics, onboarding, reset in two steps, debug consent, feedback and undo) |
| 7.3 / 7.5-B2 post menu | `components/post/PostCard.vue:196-240` (`canFeedback`, `canHideCreator` on suggestions only, `giveFeedback`), menu `:823`; `lib/feedFeedback.ts` (undo toast through `DELETE feed/feedback/{id}/`); `views/HomeView.vue:170` (optimistic removal and restore), topics map |
| Reels overlay | `views/ReelsView.vue:259` `reelFeedback` (Interested, Don't recommend; Not interested stays the reel's hide) |
| Profile menu | `components/social/PersonActionsMenu.vue:110` `dontRecommend` (item_type=profile), `ProfileHero.vue` (`hide-creator` unless own profile) |
| 7.6-B2 Why | `components/post/WhyThisPost.vue:42-57` and the `default` branch: new codes, `rec_generic` fallback |
| 8.2 My Algorithm | `views/MyAlgorithmView.vue`, `components/feed/InterestProfile.vue`; route `router/index.ts:84`; links in `components/settings/ContentPreferences.vue` and `components/feed/FeedPreferences.vue` |
| personalization_off | `lib/personalization.ts` (preference on sign-in, `App.vue:93`), `HomeView.vue:313,673` (`meta.personalization_off`), `MyAlgorithmView.vue` (on toggle); `lib/signals.ts::setPersonalizationOff` drops the queue |
| 6.6 onboarding | `components/feed/OnboardingTopics.vue`, `views/OnboardingTopicsView.vue`, route `router/index.ts:85`, `lib/onboarding.ts` (marker set in `RegisterView.vue`, used in `LoginCard.vue`) |
| 7.4 staff UI | `components/moderation/ReportList.vue:25,82-100`, `views/AdminModerationView.vue:280`, `services/admin.ts` types |
| i18n | `src/i18n/myAlgorithm.ar.ts` / `.en.ts`, two lines each in `ar.ts` and `en.ts`; the block toast copy in `postsFeed.*.ts` now follows 06 §10 |

## The moderation system-source choice

The choice is a `report.source` column (`user` | `system`, database default `user`) plus a reserved nil reporter id (`00000000-0000-0000-0000-000000000000`). With this choice the migration is purely additive and `reporter_id` stays NOT NULL.

- A system report:
  - never increments `report_count`;
  - is served with `reporter_id: null` and `source: "system"`;
  - is excluded from My reports through `source=user`.
- The case carries `system_signal`, so the queue can label it.
- Redelivery adds nothing, and a second flag while the case is open adds nothing either.
- A user report joins the same open case.
- A new flag after the case is resolved opens a new case.

## Acceptance evidence (real runs)

- **identity:** 5 new tests:
  - one event on a language change, with the payload `{account_id, changed:["language"], language}`;
  - nothing on a no-op, on another field, with the flag off, or on a failed PATCH;
  - no DOB, gender or email in the payload;
  - schema valid.
- **moderation:** 7 new tests:
  - one system case with `report_count` 0 and API `reporter_id: null`;
  - redelivery dedupes;
  - a user report joins and counts 1;
  - My reports holds only the person's own reports, and the nil id sees none;
  - a malformed event is dropped;
  - after a resolution a new case opens.
- **post:** page 1 after a reset equals a newcomer's cold-start page, and the 3 `reel_view` rows are kept. Also covered:
  - views after the reset count again;
  - the newest reset wins and is idempotent;
  - another viewer is unaffected;
  - a hidden creator leaves for_you and the undo restores them;
  - a hidden friend stays.
- **graph** (25 new tests):
  - Parity: with no row, and with a `discovery@1` row, the output is identical (10 by default, 15 at `limit=30`).
  - Published limits apply, and out-of-range values fall back.
  - Variants: 8 fixed fixtures equal `assign_variant`, and partial allocation leaves 6 of 8 out.
  - Exposure: `meta.variant` is set, there is exactly 1 exposure event over 4 requests, and it is schema valid. The flag off records nothing.
  - E9b: a minor or unknown author is never suggested (follower fill too), stays a friend and follower, and is suggested again once their token says adult. A minor viewer gets `[]` with no exposure. Graph has no DOB column.
  - Hidden creators: removed from people and pages, the undo restores exactly, an older undo is ignored, and following is untouched.
- **profile:**
  - parity: 20 groups and 3 friend ids per group, unchanged with `discovery@1`;
  - params apply (5 groups, 0 previews);
  - the variant equals `assign_variant` and gives one exposure event.
- **marketplace:** the cache keeps the newest version and ignores other surfaces. The 5 allocated fixture accounts get the same variant as `assign_variant`, with one exposure each.
- **search:**
  - off by default, and after turning it off: 0 events;
  - on: 1 event whose payload keys are exactly `{account_id, term_keys, queried_at}`, all 64-hex, with no text, and schema valid;
  - later pages, empty or 1-character queries and other accounts emit nothing;
  - the search path reads the opt-in with 0 SQL. The existing query-budget test is still green.
- **Dev broker:** these bindings are present on the dev broker:
  - `graph.events`: `intel.config.published`, `intel.creator.hidden`;
  - `profile.events` and `marketplace.events`: `intel.config.published`;
  - `moderation.events`: `intel.integrity.flagged`;
  - `post.events`: `feed.recommendations.reset`, `intel.creator.hidden`;
  - `search.events`: `intel.search_signal.changed`.
- **Dokploy:** the rewritten-compose size is **76,168** (limit 100,000).

## Test counts

`bash scripts/test-service.sh <svc>`, all green. `makemigrations --check` is clean for each service.

| Service | Tests |
|---|---|
| identity | 423 |
| moderation | 159 |
| post | 613 |
| graph | 154 |
| profile | 198 |
| marketplace | 145 |
| search | 155 |

- **Web checks:**
  - lint and typecheck are clean;
  - vitest: 79 files. The 7 new specs are `postCardMenu`, `myAlgorithm`, `interestProfile`, `onboardingTopics`, `signalsPersonalization`, `bucketParity` (240 fixture rows) and `moderationSystemSignal`, plus additions to `whyThisPost`;
  - `VITE_STORAGE_PROXY=true npm run build` is OK.
- **Smoke and lint:** `python scripts/smoke_test.py` passes. `ruff check` and `format --check` pass on the seven services.
- **e2e regressions (preview :4173, `--workers=1`), all passed:**
  - home-feed, home-modes, home-refresh and intel-signals: 19;
  - graph-suggestions, auth and reels: 20.
- **New e2e specs** (against feed's live R4 endpoints): `feed-feedback`, `my-algorithm` and `onboarding-topics`, 6 of 6 passed in ar and en, with axe on the menu group, the page and the dialog. RTL and dark mode are checked.
- **Last regression run:** home-feed, home-modes, home-refresh, intel-signals and onboarding-topics gave 20 of 21 passed. The one failure was a home-refresh pull-to-refresh fan-out timing case in ar; it passed 2 of 2 when rerun alone.

## Migrations, events, env vars, routes

- **Migrations (all additive):**
  - `graph/0004_intel_r4`
  - `groups/0002_intel_config` (profile)
  - `marketplace/0010_intel_config`
  - `moderation/0004_system_report_source`
  - `reels/0003_reels_reset` (`reels_reset`, `reels_hidden_creator`)
  - `searchsvc/0009_search_signal_outbox`
  All six are applied on dev, and the owned containers are recreated.
- **Events consumed:**
  - `intel.config.published`: graph, profile, marketplace;
  - `intel.creator.hidden`: graph, post;
  - `intel.integrity.flagged`: moderation;
  - `feed.recommendations.reset`: post;
  - `intel.search_signal.changed`: search.
- **Events produced:**
  - `account.updated`: identity;
  - `intel.experiment.exposed`: graph, profile, marketplace;
  - `search.queried`: search.
- **Env vars** (in `.env.example`, `.env_prod.example`, `docker-compose.dokploy.yml`, `scripts/gen-dokploy-env.sh` and the k8s configmaps):
  - `IDENTITY_EMIT_ACCOUNT_UPDATED`;
  - `INTEL_EMIT_EXPOSURE_EVENTS`, one `&intel-exposure` alias in the Dokploy compose;
  - `SEARCH_EMIT_QUERY_SIGNALS`.
  The deploy note is in `docs/deploy/DOKPLOY.md` (R4 other services).
- **New worker:** search's outbox relay. It is `search-relay` in dev compose, `search-worker` in Dokploy (192 MB), and the `worker` component in the k8s search overlay; the k8s README table is updated. Search gains `celery>=5.3`, already pinned in `constraints.txt`.
- **Routes:** the client-side routes `/settings/my-algorithm` and `/welcome/topics` are covered by the nginx SPA fallback (both return 200 on preview). There are no new edge routes.

## Deviations and why

1. **Marketplace** has no ranked surface: it keeps a handler and cache only. No view calls `served`, so nothing is exposed today.
2. **Unknown "Why" codes:** an unknown code renders as `rec_generic` only when it is a `rec_*` code or the item is a suggestion. An unknown non-recommendation code on a friend's post stays skipped. This keeps the R1 test, and saying "Suggested" about a friend's post would be false.
3. **Reels "Not interested"** stays the existing reel hide. Feed reads it as `not_interested` through `reel.hidden` (WP 7.2), so there is no double write. The overlay adds Interested and Don't recommend.
4. **Post also consumes `intel.creator.hidden`.** Without it, "Don't recommend" from a reel would not reach the reels for_you tab, which post serves. The contract row in `04-event-contracts.md` now lists post as a consumer.
5. **"Don't recommend" in the post menu is offered on suggestions only** (06 §10), and on profiles. A page profile menu does not get it yet.
6. **E9b in graph fails closed.** A candidate is suggested only when its own token said adult in a graph request since deploy. There is no backfill (decision 37, the same as feed), so "People you may know" can be short on dev until accounts sign in. A minor viewer gets no people suggestions (decision 9a). Unknown-age viewers still get adults-only suggestions.
7. **Search reads the opt-in from the cache only,** to keep the search-page query budget. A lost cache reads as off (the private direction), and a 10-minute beat re-warms it from the table.
8. **The onboarding picker** shows on the first sign-in after a sign-up in the same browser (an id marker, as for "Complete your profile"), and only while `onboarded_at` is null. A server without onboarding skips it. The auth and register e2e specs skip it through `skipTopicPicker`.
9. **The block toast copy** in the post menu now follows 06 §10.

## Open items

- **Open post menu stacking:** the R4 menu is longer and ran past its card. `content-visibility: auto` clipped it, so the next card covered it. Fixed in `HomeView.vue` (`[data-feed-item]:has(post-menu-panel)` gets visible content and z-index 30). The verifier should look at the same pattern on other feeds.
- **E9b dev impact:** existing accounts reach PYMK only after their next graph request.
- **Page profiles** ("Don't recommend" with `item_type=page`) have no menu entry yet.
