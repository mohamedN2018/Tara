# Phase 3 results, track B: graph, moderation and post (WP 3.3, 3.3b, 3.6, 3.7)

Date: 2026-11-05. Dev stack as in [phase-02.md](phase-02.md). Track A (feed: WP 3.1, 3.2, 3.4, 3.5) reports separately.

## What was built

| WP | Where | Behaviour |
|---|---|---|
| 3.3 | `services/graph/graph/{models,handlers,suggestions,services,internal_views}.py`, migration `graph.0003_account_ref_state` | `AccountRef` gains `deactivated`, `suspended` (each with its own event timestamp, newest wins) and `active = not (deactivated or suspended)`, fed by `account.deactivated` / `reactivated` / `suspended` / `unsuspended`. It also gains `restriction` (`""`, `restrict`, `shadow`), `restriction_case_id` and `restriction_event_at`, fed by `moderation.actioned` with `target_type=user` (`reinstate` clears it and keeps the timestamp as a tombstone). People suggestions drop inactive and restricted candidates. The `fanout/` audience drops inactive recipients and keeps restricted accounts. Edges are never deleted, so the change is reversible |
| 3.3b | `services/moderation/moderation/services.py` (`REVERSALS`, `_SAME_EFFECT`, `_reversal`), `config/settings.py` | An overturned `(user, restrict)`, `(user, shadow)` or `(page, restrict)` emits `moderation.actioned` with `reinstate`, and `appeal.resolved.reversal = "reinstate"`. It is emitted only when no other case's `restrict`/`shadow` on the target stands, because consumers drop every restriction of the account. It sits behind `MODERATION_EMIT_REINSTATE` (default true). `reinstate` is not a moderator action |
| 3.6 | `services/post/posts/hydration.py`, `posts/views.py` (`PostBatchView`), `reels/{views,services,serializers,urls}.py` (`ReelBatchView`, `reels_by_ids`); web `services/post.ts`, `services/feed.ts`, `types/index.ts` | `POST /api/v1/reels/batch/`: at most 50 ids, in request order, with the same answer as `/reels/<id>/` per id. Both batches accept optional `surface` / `src` hints (`src` is a string or a list parallel to `ids`) and count every requested id they do not return in `post_batch_dropped_total{caller,surface,src}`. Labels come from a closed vocabulary (anything else is `other`, a missing hint is `none`). The counts live in post's Redis cache, so every gunicorn worker (`WEB_CONCURRENCY=2`) reports the same value. The web passes `surface: "home"` and each item's `source ?? reason` |
| 3.7 | `services/post/posts/models.py`, migration `posts.0013_intel_indexes` (`AddIndexConcurrently`, `atomic=False`) | `share_account_idx (account_id, created_at DESC)` and the partial `post_type_published_idx (type, created_at DESC) WHERE state='published' AND group_id IS NULL` |

## Acceptance criteria

- **3.3:** a deactivated or suspended account disappears from PYMK and fan-out, and comes back on reactivation or unsuspension. A restricted or shadowed account disappears from PYMK and keeps its fan-out as author and as recipient. Evidence: `test_suggestions_inactive.py` (9 tests) and `test_suggestions_restricted.py` (11 tests). The live graph queue `graph.events` is bound to the four `account.*` keys and to `moderation.actioned`.
- **3.3b:** an overturned `restrict` or `shadow` emits `reinstate`, and the payload validates against both schemas (`test_reinstate.py`, 9 tests). Graph lifts it (`test_a_restricted_account_leaves_pymk_until_reinstated`). Track A covers feed's side (`test_account_restriction.py`).
- **3.6:** on the server, `python scripts/integration/intel_privacy.py` signed in all 120 seed viewers and read 2 pages of each Home mode (14,348 ids: follow 9,095, friend 5,183, self 70). Hydrating them through `/posts/batch/` with the hints returned 14,348 of 14,348. Post's counter delta was empty: 0 drops in every source, discovery included. **Caveat:** feed serves no discovery source yet (phase 9), so the discovery-is-0 check passes vacuously today, and the script fails as soon as one such source drops an id. The live probe through the edge checked: the reels tab's 10 ids came back in order from `/reels/batch/`, an unknown id was counted once per call on every scrape, anonymous got 401, and 51 ids got 400.
- **3.7:** `EXPLAIN` of `video_posts_queryset()` on the dev data (2,510 posts, seqscan allowed) shows `Index Scan using post_type_published_idx`. Both indexes are `indisvalid` in dev. `test_intel_indexes.py` checks the definitions and both plans.

## Tests

| Suite | Before | After | New |
|---|---|---|---|
| graph | 95 | 120 (5 from track A's backfill export) | 20 |
| moderation | 139 | 145 | 9 (3 parametrized cases moved out of `test_hardening.py`) |
| post | 565 | 588 (includes track A's export tests at run time) | 21: `test_reels_batch.py` 7, `test_batch_drop_counter.py` 10, `test_intel_indexes.py` 4 |
| web vitest | 800 | 802 | 2 (`feed.spec.ts`: hints passed, chunked and dropped when mismatched) |
| e2e on :4173 | `home-feed`, `feed-hide`, `intel-signals`, `reels` | 14 passed | |

Lint and typecheck are clean, `makemigrations --check` is clean in all three services, `scripts/smoke_test.py` passes, `check_deploy.sh` passes, and the Dokploy compose size is 73,474 (limit 100,000).

## Deviations

- Graph keeps two lifecycle flags plus the derived `active`, not a single `active`. Deactivation and suspension are independent in identity: an account that reactivates while suspended must stay inactive.
- `reinstate` means "no restriction stands on the target". Moderation therefore emits it only when no other case's `restrict`/`shadow` stands, and the standing check treats `restrict` and `shadow` as one effect.
- The drop counter is stored in Redis and exposed by a collector, because an in-process counter is invisible to half of the scrapes with 2 workers.
- No web caller of `/reels/batch/` yet: feed's reels surface ships in phase 5.

## Open items

- Accounts deactivated, suspended or restricted before this release are unknown to graph until their next event. There is no bulk state export in identity or moderation to backfill from.
- Feed's intel `Prometheus` counters (`intel_signal_*`) use in-process counters and have the same multi-worker blind spot (`WEB_CONCURRENCY`).
- The page `reinstate` has no consumer: nothing enforces a page `restrict` today.
