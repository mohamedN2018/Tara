# Phase 3 results: candidates and eligibility

Date: 2026-11-05. Dev stack as in [phase-02.md](phase-02.md) (Docker Desktop, Windows 11,
seeded dataset in `.seed-state/`, nothing wiped). Two build tracks delivered the work
packages: track A (feed: WP 3.1, 3.2, 3.4, 3.5) and track B (graph, moderation, post, web:
WP 3.3, 3.3b, 3.6, 3.7; its own notes are in [phase-03-track-b.md](phase-03-track-b.md)).
The last section, "Verification", is the adversarial review of both tracks: what was
re-checked, the problems found and their fixes.

Every count below was taken by a query or a run at the time shown, never compared with a
fixed number (04, section 0).

## Status per work package

| WP | Status | Where |
|---|---|---|
| 3.1 Read models | Done | `services/feed/intel/models.py` (phase-3 models from line 227), `intel/readmodels.py`, `intel/readmodel_handlers.py`, `intel/topics/language.py`, `feed/models.py` (`AuthorRef` lifecycle), `feed/services.py:230` (`intel_fanout_capped` in the fan-out transaction) |
| 3.2 Backfills | Done, extended by the verifier (account lifecycle and restrictions) | `intel/backfill.py`, `intel/management/commands/intel_backfill_{content,edges,groups,pages,accounts}.py`, owner exports `posts/intel_export.py`, `graph/intel_export.py`, `profiles/intel_export.py`, `identity/intel_export.py`, `moderation/intel_export.py`, `scripts/intel/check_backfill.sh` |
| 3.3 Graph inactive and restricted accounts | Done, plus a graph backfill (verifier) | `graph/models.py` (`AccountRef`), `graph/handlers.py` (`set_lifecycle`, `set_restriction`), `graph/suggestions.py`, `graph/services.py` (`inactive_among`), `graph/internal_views.py`, `graph/management/commands/intel_backfill_{accounts,restrictions}.py` |
| 3.3b Moderation reinstate | Done | `moderation/services.py` (`REVERSALS`, `_SAME_EFFECT`, `_reversal`), `moderation.actioned.v1.json`, `appeal.resolved.v1.json` |
| 3.4 Retrieval | Done | `intel/retrieval/__init__.py`, `intel/retrieval/sources.py`, `intel/config/defaults/*.json` |
| 3.5 Eligibility | Done | `intel/eligibility.py` (one function per rule, `RULES` table), `intel/metrics.py` (`intel_eligibility_drop_total{rule}`), `hypothesis` in `services/feed/requirements-dev.txt` |
| 3.6 Hydration contract | Done; the integration check was strengthened by the verifier | `posts/hydration.py`, `reels/views.py` (`ReelBatchView`), `reels/services.py` (`reels_by_ids`), `frontend/web/src/services/{feed,post}.ts`, `scripts/integration/intel_privacy.py` |
| 3.7 Indexes | Done | `posts/migrations/0013_intel_indexes.py` |

## Acceptance evidence

### WP 3.1

- Every handler is newest-wins on its own guard time and keeps tombstones, so a redelivered
  or reordered event changes nothing: `test_readmodels_intel.py` delivers every event twice
  and in reversed order (18 tests).
- `test_language.py` (12): ar, en, mixed, und, and Arabizi labelled `en` (documented in the
  module).
- `test_fanout_capped.py` (2): a truncated fan-out writes exactly one row, also on a retry;
  an untruncated one writes none. The row is written in the same transaction as the
  `FeedItem` bulk insert.
- `test_account_restriction.py` (11): `restrict` / `shadow` / `reinstate` in both orders;
  `warn` / `dismiss` change nothing.
- Live: RabbitMQ shows `feed.events` bound to `post.approved`, `group.post.published`,
  `reel.state.changed`, `page.created/updated`, `moderation.actioned`, `media.processed`,
  `friendship.*`, `user.blocked/unblocked`, `group.*` and `account.*`.

### WP 3.2

`bash scripts/intel/check_backfill.sh` at 2026-11-05T19:11:15Z (both sides counted between
19:11:15 and 19:11:18), exit 0:

| Criterion | Reader | Owner |
|---|---|---|
| `intel_friend_edge` (active) = 2 x accepted friendships | 3,350 | 3,350 |
| `follow_edge` (active) = graph `follow_relation` | 2,335 | 2,335 |
| active `intel_group_membership` = profile active `group_member` | 478 | 478 |
| `intel_page_ref` = profile `page` | 293 | 293 |
| `intel_content_ref` (not deleted) = published/held, not removed posts | 2,318 | 2,318 |
| feed `author_ref` not active = identity accounts deactivated or suspended (verifier) | 10 | 10 |
| graph `account_ref` not active = the same identity count (verifier) | 10 | 10 |
| feed active `intel_account_restriction` = moderation users with a standing restrict/shadow (verifier) | 0 | 0 |
| graph restricted `account_ref` = the same moderation count (verifier) | 0 | 0 |
| groups (reported only) | 120 | 120 |
| block directions (reported only) | 0 | 0 |

The counts grew between track A's run (18:33Z: 3,348 / 2,334 / 2,317) and this one; the
live consumers kept both sides equal. Before the verifier's account backfill the same script
reported `0 != 10` for both lifecycle rows (see Verification, finding 1).

Backfill runs: track A's content, edges, groups and pages backfills took about 22 s in all
and swept nothing. The verifier's `intel_backfill_accounts` (feed) read 10 accounts and wrote
20 flags; graph's `intel_backfill_accounts` listed 10 and applied 20 flags;
`intel_backfill_restrictions` (feed kind and graph command) listed 0.

### WP 3.3

- `test_suggestions_inactive.py` (9) and `test_suggestions_restricted.py` (11): a deactivated
  or suspended account leaves PYMK and fan-out (flags independent, newest event wins per
  flag); a restricted or shadowed account leaves PYMK and keeps its fan-out.
- `test_intel_backfill_accounts.py` (9, verifier): the identity and moderation backfills,
  newest-wins against the events, and the sweep.
- Live after the backfill: people suggestions for 200 active accounts contained 0 of the 10
  suspended accounts.

### WP 3.3b

`test_reinstate.py` (9): an overturned `(user, restrict)`, `(user, shadow)` or
`(page, restrict)` emits `moderation.actioned` with `reinstate` inside the appeal's
transaction, validated against both schemas; another case's standing restrict/shadow keeps
the account restricted; a warning does not; an upheld appeal emits nothing; with
`MODERATION_EMIT_REINSTATE=false` the overturn is only audited. Feed and graph lift the
restriction on `reinstate` (`test_account_restriction.py`, `test_suggestions_restricted.py`).

### WP 3.4

`test_retrieval.py` (12): group posts of joined groups appear in Home candidates; an author
with 5,001 followers and `FANOUT_MAX_RECIPIENTS=5` reaches every follower either as a
connection or through `follow_pull`; a new follow shows the last 7 days and nothing older; a
post already in the viewer's feed (even hidden) is never pulled again; every window comes
from the config.

### WP 3.5

- `test_eligibility.py` (43): at least one test per rule, plus fail-closed cases (no content
  row, unknown group or page, empty audience, no age claims, unknown source counted as `E0`).
- `test_eligibility_property.py`: 120 random worlds per run with blocks both ways,
  public/private/hidden groups (some suspended or deleted), banned and requesting members,
  pending group posts, draft/suspended/deleted pages, unplayable reels, restricted, shadowed
  and deactivated authors, friends-only / followers-only / `only_me` posts, minor and
  unknown-age viewers; every account is the viewer on every surface through every source.
  Every returned id must pass a reference copy of post's `visible_to_viewer`, and every
  returned reel must be published. Track A switched each privacy rule off in turn (E1, E1b,
  E1c, E2, E2b, E3, E4, E6b, E7, E9, E11) and the property test failed every time.
- The filter loads its data in at most 16 queries whatever the number of candidates.

### WP 3.6

`python scripts/integration/intel_privacy.py` (all 120 seeded viewers, 2 min 32 s), with the
verifier's second stage:

| Stage | Requested | Missing |
|---|---|---|
| Served Home, all four modes (`recent`, `for_you`, `following`, `favorites`), 2 pages each | 14,348 (follow 9,095, friend 5,183, self 70) | 0 |
| Intel candidates, home / connections | 36,176 | 0 |
| Intel candidates, home / `follow_pull` | 2,563 | 0 |
| Intel candidates, home / `groups` | 1,622 | 0 |
| Intel candidates, groups / `groups` | 2,754 | 0 |
| Intel candidates, reels / connections + `reels` (through `/reels/batch/`) | 2,368 + 12,632 | 0 |
| Intel candidates, video / connections + `video` | 1,462 + 12,932 | 0 |

`post_batch_dropped_total` showed no change for any label during the run, so post refused
none of the ids that feed's eligibility kept. Tests: `test_reels_batch.py` (7),
`test_batch_drop_counter.py` (10).

### WP 3.7

Both indexes are valid in dev, and `EXPLAIN` of the video query
(`type='video'`, published, not deleted, no group, newest first) uses
`Index Scan using post_type_published_idx`. `test_intel_indexes.py` (4) checks the
definitions and both query plans.

## Tests

Each backend suite through `bash scripts/test-service.sh <svc>` after rebuilding the image
(`makemigrations --check` clean in every one):

| Suite | Before phase 3 | After phase 3 | Failed |
|---|---|---|---|
| feed | 220 | 351 | 0 |
| graph | 95 | 129 | 0 |
| moderation | 139 | 152 | 0 |
| post | 565 | 588 | 0 |
| profile | 186 | 192 | 0 |
| identity | 411 | 418 | 0 |
| web vitest | 800 | 802 | 0 |

Also green: `npm run lint`, `npm run typecheck`, e2e `home-feed`, `feed-hide`,
`intel-signals` and `reels` against the preview on :4173 (14 passed, 1.3 min, after
`VITE_STORAGE_PROXY=true npm run build`), `python scripts/smoke_test.py` (all checks
passed), `uvx ruff@0.17.3 check` and `format --check` (838 files), Dokploy compose size
74,546 (limit 100,000).

## Migrations, events, env vars, routes

- **Migrations (additive):** feed `intel/0002_readmodels`, `feed/0009_author_ref_lifecycle`;
  graph `0003_account_ref_state` (database defaults); post `0013_intel_indexes`
  (`CREATE INDEX CONCURRENTLY`, non-atomic). All applied in dev.
- **Events:** no new event type. `moderation.actioned` gains the action `reinstate` and
  `appeal.resolved` the reversal `reinstate` (additive; rows updated in
  `docs/architecture/phase-0/04-event-contracts.md`). New consumers: feed (phase-3 read
  models) and graph (`account.*`, `moderation.actioned`).
- **Env vars:** `MODERATION_EMIT_REINSTATE` (track B, all four places). The verifier adds
  `MODERATION_INTERNAL_URL` (`http://moderation:8000`) to the compose's shared env next to
  the other service addresses, commented defaults in `.env.example`, a note in
  `.env_prod.example` and `scripts/gen-dokploy-env.sh` (the compose fixes it, like
  `POST_INTERNAL_URL`), and `IDENTITY_INTERNAL_URL` / `MODERATION_INTERNAL_URL` settings in
  feed and graph (identity's was already in the shared env).
- **Routes:** public `POST /api/v1/reels/batch/` is under the already routed `/api/v1/reels`.
  The exports are internal (`/internal/v1/intel/export/...`, internal token per owner
  audience); the edge answers 404 for `/internal/`.
- **Deploy note:** `docs/deploy/DOKPLOY.md`, "Upgrading: Tara Intelligence eligibility",
  now lists the one-off backfills to run after the deploy.

## Deviations from the plan

- **WP 3.1, language:** Arabizi is `en`, so any mostly-Latin text (French too) is `en`;
  documented in `intel/topics/language.py`.
- **WP 3.2, edges:** read from graph's paged export instead of one `fanout/` call per
  account (fewer requests, resumable; same D6 fix).
- **WP 3.2, account state (verifier):** the plan lists no backfill for account lifecycle or
  restrictions, but rules E6 and E11 and the D5 criterion of WP 3.3 depend on them; see
  finding 1.
- **WP 3.3:** two lifecycle flags instead of one `active` column (an account that
  reactivates while still suspended stays inactive). `reinstate` is emitted only when no
  other restrict/shadow stands, because consumers lift every restriction of the account.
- **WP 3.6:** the drop counter lives in Redis (post runs 2 gunicorn workers). No web caller
  of `/reels/batch/` yet; feed's reels surface arrives in phase 5. The served Home has no
  discovery source until phase 9, so the plan's "discovery drops = 0" is measured on the
  intel candidates of every pull and pool source instead (finding 2).

## Verification (adversarial review of both tracks)

Re-checked by running, not from the reports: every suite above, the backfill parity script,
the privacy integration against all 120 seeded viewers, RabbitMQ bindings, both indexes and
the plan, the edge for `/internal/`, the e2e specs, lint and the compose size. Code read for
fail-open paths in every eligibility rule, retrieval query and handler, events outside
transactions (the reinstate emission and the capped fan-out row are both inside the write
transaction), N+1 queries, magic numbers in ranking code (none: windows and thresholds come
from `intel/config/defaults/*.json`), and exposure of restrictions (no view, serializer or
admin exposes `intel_account_restriction` or graph's `restriction`).

1. **Fixed: accounts already inactive or restricted were "active" to feed and graph.**
   identity had 10 suspended accounts; feed's `author_ref` and graph's `account_ref` had 0
   inactive rows, so rule E6 and the D5 exclusion (PYMK and fan-out) did not apply to them
   until a future event, and the same held for any restriction decided before this
   release (rule E11). Both tracks only listed it as an open item. Fix:
   - identity `GET /internal/v1/intel/export/accounts/` (`identity/intel_export.py`): only
     the accounts that are not active, `{account_id, deactivated, suspended}`, the flags kept
     apart (a suspension over a deactivation goes back to deactivated), prefetched (no
     query per account);
   - moderation `GET /internal/v1/intel/export/restrictions/` (`moderation/intel_export.py`):
     every user case whose decision is restrict/shadow and that no appeal overturned (the
     same "standing" rule as `reinstate`);
   - feed kinds `accounts` and `restrictions` in `intel/backfill.py` (same newest-wins
     writers as the events; a complete scan sweeps what the owner no longer lists, never a
     flag newer than the scan) and the command `intel_backfill_accounts`;
   - graph `set_lifecycle` / `set_restriction` (the handlers now call them) and the commands
     `intel_backfill_accounts` / `intel_backfill_restrictions` (`graph/intel_backfill.py`);
   - `check_backfill.sh` now also compares both lifecycle and restriction counts.
   Tests: identity `test_intel_export.py` (7), moderation `test_intel_export.py` (7), graph
   `test_intel_backfill_accounts.py` (9), feed `test_backfill.py` (+8). Live result: 10 = 10
   on both sides.
2. **Fixed: the WP 3.6 integration measured nothing that eligibility decided.** It hydrated
   only the served Home, whose items are all fan-out rows, so the "0 discovery drops" was
   vacuous. `intel_privacy.py` now also asks feed's pipeline (`manage.py intel_candidates`,
   now taking many viewers and each viewer's own age claims from its access token) for every
   surface's eligible candidates and hydrates them as that viewer, failing on any drop from a
   non-connection source. Result: 0 of 32,503 pull and pool ids refused. Test:
   `test_intel_candidates_command.py` (4).
3. **Checked, no change needed:** retrieval and eligibility stay outside the served Home
   (that is phase 4), so every Home mode works as before for all 120 seeded viewers; fan-out
   still writes `FeedItem` rows exactly as before and adds the capped row in the same
   transaction; the reinstate event is emitted inside `resolve_appeal`'s transaction;
   notifications never announce `shadow` or `reinstate`; the property test's newest
   assertion (published reels) is in the rebuilt feed image and passes.

## Open items

- Page `reinstate` has no consumer: nothing enforces a page `restrict` today.
- `intel_eligibility_drop_total` and feed's `intel_signal_*` counters are per process; when
  feed serves eligibility with several gunicorn workers (phase 4) they need the shared-store
  approach post's drop counter uses, or Prometheus multiprocess mode.
- Rule E9: all 120 seeded viewers have a date of birth, so the live run exercised adults
  only; limited viewers are covered by the unit and property tests. `minor_allowed_topics`
  is empty until phase 6 topics exist, so a limited viewer discovers nothing (fail closed).
- Rule E8 knows only explicit `dislike_creator` hides until phase 6 adds disliked topics;
  E10 applies no language filter until the viewer's content languages are stored (phase 8).
- The plan's integration counter reading includes other clients' traffic; the per-id check
  of stage 2 is exact.
