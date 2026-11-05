# R1 Track A: backend feed and deploy (WP 4b.0, 4b.1, 4b.6, 4b.10, 4b.11, 4b.14, 4b.15)

Date: 2026-11-06. Dev stack on Docker Desktop, seeded dataset in `.seed-state/`, nothing
wiped. Not committed and not pushed (the verifier merges this file into `phase-04b.md`
and writes the work log). Built in the order of 07 line 159:
4b.1 → 4b.15 → 4b.0 → 4b.10 → 4b.11 → 4b.14 → 4b.6. The harness baseline ran on the
unchanged code, before any other edit.

Every number below was taken by a query or a harness run at the time shown. Nothing was
activated: `home@1` is still the active Home version on dev.

## Work packages

| WP | Status | Where |
|---|---|---|
| 4b.1 Repetition harness | Done | `services/feed/intel/repetition.py` (the maths); `intel/management/commands/intel_measure_repetition.py` (in-process and read-only); `scripts/intel/measure_repetition.py` (host wrapper: `--mount-source`, `--visit-gap`, `--http-users`, `--warm-ages`) |
| 4b.15 Test clock guard | Done | `intel/clock.py:63` `request_now`; feed `feed/views.py:190` (ranking `now`); feed-signals `intel/views.py:56` (`received_at`); check `intel/checks.py:71` (`intel.E005`, deploy); readiness `intel/readiness.py:24` (`/readyz/` check `intel_test_clock`); setting `config/settings.py:171` |
| 4b.0 redis-hot 384 MB, keys, metrics | Done | `infra/compose/docker-compose.yml` (redis-hot `--maxmemory 384mb`; the feed-relay beat worker now gets `REDIS_HOT_URL`); `docker-compose.dokploy.yml` (`384mb`, `mem_limit: 448m`, still `noeviction`); raw keys `intel/hot.py:74` `raw_keys`, `:94` `raw_set` (fail-soft, counted), `:122` `used_ratio`, `:146` `forget_account`; metrics `intel/metrics.py` (`intel_hot_write_failed_total{key}`, `intel_first_page_overlap`, `intel_repeat_display_total`, `intel_caught_up_total`, `intel_pool_rebuild_total{outcome}`, collector `HotMemoryCollector` at `:97` for `intel_redis_hot_used_ratio`); alert `infra/observability/alerts.yml` (`IntelRedisHotMemoryHigh`); promtool unit test `infra/observability/tests/intel-alerts.test.yml` |
| Config schema v2 | Done | `intel/config/schema.py:28` (`SCHEMA_VERSION = 2`), `:246` `POOLS`, `:261` `MIX`, `:269` `CONTINUATION`, `:271` `HEAD`, `:408` `HOME_SOURCES` with `discovery`, `:512` `_version_rules`; REASONS + `rec_popular`, `rec_fresh`; `intel/config/defaults/home.v2b.json`; migration `intel/migrations/0006_home_v2b_drafts.py` |
| 4b.10 Diversity in home@2b | Done | `home.v2b.json` keeps the `home@2` diversity block (`max_same_format_run: 2`, `max_per_author_page: 2`); the recommended slots are placed inside the re-ranker (`intel/ranking/diversity.py:144` `insert`, `intel/ranking/home.py:198` `_mix_diverse`) |
| 4b.11 Repeat-exposure metrics | Done | `intel/head.py:36` `record` (head `feed:head:home:{viewer}`, 16 B per id, TTL `head.ttl_s`); called from `feed/views.py:220`; `intel_caught_up_total` at `feed/views.py:215` |
| 4b.14 E9b, feed side | Done | migration `feed/migrations/0011_author_age_class.py`; model `feed/models.py` `AuthorRef.age_class`; capture `intel/age.py:70` (memo `intel:age:{account}`), called at `feed/views.py:140`; rule `intel/eligibility.py:283` `e9b_author_age`, in DISCOVERY at `:332`, in `RECHECK` at `:495`; `ports.author_refs` returns `age_class` |
| 4b.6 Pools, mix, continuation, caught_up | Done | `intel/discovery.py` (rebuild `:222`, read `:289`, share `:78`, continuation `:89`, why lookup `:342`); retriever `intel/ranking/home.py:49` (`SOURCE_FUNCS["discovery"]`), `:114` `eligible_inventory`, `:249` `rank`; session and pages `feed/ranking.py:264` `_caught_up`, `:296` (`cu` in the session); `meta.caught_up_index` at `feed/views.py:233`; session wire codes `intel/ranking/session.py:59`; why `intel/why.py:147`; beat `intel/tasks.py:31` `intel.rebuild_pools`, scheduled in `config/settings.py:147` |

## Acceptance criteria, measured

Harness commands below are run from the repo root, as
`python scripts/intel/measure_repetition.py --mount-source -- <args>`. Every run is
read-only (`SET TRANSACTION READ ONLY`, rolled back), ranks under the stored version given
by `--variant` without activating it, and keeps sessions, heads and pools in redis-hot
db 9. Viewers are treated as adults. The output holds no account id.

Version mapping, read from `intel_ranking_config`: **`home@2b` = home@3**,
**`home@2b-r15` = home@4**, **`home@2b-r30` = home@5**. All three are `draft`,
`schema_version` 2, with one `created` change-log row each. `home@1` is active and
`home@2` is archived.

### 4b.1: the baseline reproduces 06 §1.1

The run was made before any other change:
`-- --users 20 --opens 4 --pages 3 --modes for_you,recent --clock-offset 1,6,24,72,168`,
with `--visit-gap`.

- **Population, by query:**
  - 498 recipients, 129 of them with ≥ 20 rows, and 39,934 `feed_item` rows;
  - `author_ref`: 526 users and 316 pages;
  - 120 synthetic (seed) accounts;
  - 2,134 public live non-group posts.
- **Selection:** 68 recipients scanned in md5 order; 20 have ≥ 60 eligible candidates
  (63 to 500, p50 309).
- **Page-1 Jaccard, open 1 against opens 2 to 4:** 1.0 for all 60 pairs, in both `for_you`
  and `recent`. The 3-page Jaccard is also 1.0 for all 60.
- **Recommended items on page 1:** 0 for all 20 users, in both modes. Items outside the
  connections: 0.
- **Clock offsets** (top-20 Jaccard against now, n = 20): +1 h gives 1.0 everywhere. +6 h,
  24 h, 72 h and 168 h give a minimum of 0.905 and p50 1.0. 06 measured 1.0 / 1.0 / 0.905
  / 0.905 / 0.905.
- **Diversity of `for_you`:**
  - max per author per page: p50 8, max 20;
  - 60 of 60 pages hold more than 2 by one author;
  - 50 pages have a run of 3 of one format;
  - distinct authors on page 1: 1 to 12.
- **Inventory arrival:**
  - over 505 (recipient, day) pairs, p10 1, p50 1, p90 339.2, max 607 rows;
  - 3 days hold data, and the busiest day has 95.5% of the rows;
  - arrival lag p50 0.0005 h.

  This is the seed burst, not organic arrival.
- **Visit gap** (identity `user_session`, read-only through psql in the postgres
  container): 31,274 sessions, 30,391 gaps over 549 accounts. Gaps are p10 0.19 s, p50
  1.28 s, p90 9.98 s: scripted logins. The production run was not made (owner note in 05).
- **Reels and video overlap** (`--http-users 5`, through the gateway, measured on
  2026-11-06 against the post service as deployed):
  - reels `for_you`: Jaccard 1.0 for 5 of 5 users, pages of 10;
  - `/posts/?type=video`: Jaccard 1.0, pages of 20.

  Post is Track B's.

**Regression check after every change** (`after-home1`, the same command under the active
`home@1`): every distribution matches the baseline exactly. That covers both Jaccards, the
recommended count, distinct authors, max per author, longest run, crawl length and the
selection.

### 4b.15: the test clock

`intel/tests/test_test_clock_guard.py` (16 tests) covers each gate separately:

- flag off;
- `TARA_ENV` production, staging, test or empty;
- an account that is not registered;
- no header, or a header that is not a time.

It runs both processes through their views: the feed first-page `now`, and feed-signals
`received_at`, which a fake-clock batch stores as `2026-12-24T10:30Z`.

With the flag on and `TARA_ENV=production`, `manage.py check --deploy` raises
`SystemCheckError` (`intel.E005`) and `/readyz/` returns 503.

Live: the Dokploy compose pins `INTEL_TEST_CLOCK_ENABLED: "false"` (`check_deploy.sh`).

### 4b.0: redis-hot

- **Live limit:** `redis-cli CONFIG SET maxmemory 402653184`, then `CONFIG GET maxmemory`
  returns **402653184**; the policy is `noeviction`. redis-hot was not recreated.
- **Dev host memory:**
  - the Docker VM has 31.2 GiB, and the containers used about 8.5 GiB;
  - more than 512 MB is free;
  - the Dokploy host could not be checked (open item).
- **Dokploy size check** (the brief's `node -e` command): **74,890**, below 100,000.
- **`bash scripts/intel/check_deploy.sh`:** all 24 checks pass. They include 8 new R1
  checks:
  - Dokploy 384mb noeviction and 448m;
  - dev 384mb;
  - the test clock pinned false;
  - post `REELS_SEEN_WINDOW_H`;
  - the dev beat worker reaches redis-hot;
  - promtool fires `IntelRedisHotMemoryHigh` at 0.81 and not at 0.79;
  - live maxmemory 402653184.
- **Gauge on dev `/metrics`:** `intel_redis_hot_used_ratio 0.0033`.
- **Account deletion:** `test_raw_keys_are_gone_as_stored` writes `feed:exp`,
  `feed:sess`, `feed:si`, `feed:head:{home,reels,video,groups,discover}` and `intel:age`
  with the raw client under `make_key`. After deletion `exists == 0` for every one; the
  other account keeps all of them. The new pool keys lose the account's posts at once
  (`test_home_pool_members_of_the_account_are_removed`).
- **Fail-soft:** a refused write (OOM) on the head, pool or age memo is counted and never
  raises (`test_hot_metrics.py`, `test_overlap_metric.py`, `test_pools_basic.py`).

### 4b.10 and 4b.6: diversity, share, continuation (harness, after the dev warm-up below)

| Run (`--variant`, selection) | Users | Recommended on page 1 | Share per user | Pages with >2 by one author | Pages with a run of 3 | `has_more=false` with pool items left |
|---|---|---|---|---|---|---|
| `home@3`, ≥ 60 connection candidates | 20 | 0 | 0.00 (all) | 6 | 5 | 0 |
| `home@3`, 20 to 59 connection candidates | 4 (of 502 scanned) | 8 | 0.10 (all 4) | 10 | 10 | 0 |
| `home@3`, any (≥ 60 incl. pools) | 20 | 0 | 0.00 | 3 | 2 | 0 |
| `home@4`, ≥ 60 connection candidates | 20 | 60 | **0.15 (min 0.15, max 0.15)** | 6 | 5 | **0** |
| `home@4`, any (≥ 60 incl. pools) | 20 | 301 | 0.15 to 1.00 (p50 0.95) | 3 | 2 | 0 |
| `home@5`, ≥ 60 connection candidates | 20 | 120 | **0.30 (min 0.30, max 0.30)** | 6 | 5 | 0 |

Command: `-- --variant home@N --users 20 --opens 2 --pages 3 --modes for_you --scan 600`,
plus `--min-connections 60` or `--min-connections 20 --max-connections 60`.

**Against the criteria:**

- **Under `home@2b` (home@3):** 0 recommended items for every viewer above the threshold
  (20 of 20). Below it the share is at most 10%: exactly 0.10 for the 4 viewers with 20
  to 59 connection items. Viewers with 0 to 2 connection items get 0, because the first
  10% slot is position 9.
- **Under `home@2b-r15` (home@4):**
  - page 1 has recommended items for 20 of 20 users with non-empty pools, in both
    selections;
  - the share over the 20 users with enough connection inventory is exactly 0.15;
  - no user ended with `has_more=false` while eligible pool items remained (crawl to the
    end, up to 80 pages).

  Users with almost no connections get mostly pool items on page 1 through continuation
  (p50 0.95). That is the "continue into suggestions instead of ending" behaviour.
- **Under r30 (home@5):** exactly 0.30 for 20 of 20.
- **E9b:** 0 recommended items by a `minor` or `unknown` user author in every run
  (`rec_by_non_adult_user` = 0, checked against `author_ref` by query).
- **Reasons:** every recommended item has a `rec_*` reason (`rec_without_reason` = 0).
- **Author cap and 8 distinct authors:** the capped pages all belong to 2 viewers (3 pages
  each). Page 1 had fewer than 8 distinct authors only for the viewer with 2 connection
  authors: 0 pages under the control, 1 under r15 and r30, where its 3 or 6 pool authors
  join its 2 connection authors. In the control their most prolific author holds 85% and 89% of
  the eligible connection inventory (11 and 2 connection authors). Under r15 and r30 that
  share is 26% and 58% of everything servable, but recommendations are held at their
  share, so they cannot stand in for the missing connection authors. The re-ranker breaks
  the cap only when no alternative is left in the list (WP 4.5). The thin-control row is
  the same story: 4 viewers whose 20 to 59 connection items come from 3 authors.
- **Format runs:** no run of 3 of one format when alternatives exist. The 5 runs belong to
  the same 2 viewers.
- **`caught_up`:** `caught_up_index` marked the page for 16 of 20 users under r15 and 10
  of 20 under r30. These are the users whose sessions continue into pools. For the rest,
  either the connection window was full (older rows follow in latest order, so the
  inventory had not run out), or the share used up every eligible pool item before the
  connection items ended.
- **Latency:** p50 6.0 ms per page for every variant. p90 is 111 ms for the control,
  120 ms for r15 and 118 ms for r30. The max is 156 / 154 / 181 ms. The first-page p90 is
  the open phase-4 cost item; r15 adds no SQL query to it.
- **Pools on dev:**
  - a rebuild takes 175 ms and reads 2,150 candidates, of which 864 are pool-eligible;
  - 706 members in 8 sorted sets, 46,208 bytes in all, every set `listpack`;
  - a first page reads 223 candidates in one pipelined round trip of 0.58 ms.

**Dev warm-up for E9b** (4b.14): before the warm-up, user authors were
`{adult: 2, unknown: 528}`, and the pools held 353 eligible posts (pages, plus the 2
adults). `--warm-ages 120` logged the 120 seed accounts in through the gateway and opened
each one's feed once (120 feed requests, 0 failures). The real capture path stored each
account's own class. By query afterwards:

- seed accounts: 120 adult;
- all user authors: 122 adult and 408 unknown;
- pools: 864 eligible.

No class was written by the harness itself; its transaction is read-only. A run made
before the warm-up under r15 already gave recommended items to 20 of 20 users (page posts
only) and 0 non-adult authors.

### 4b.11: overlap metrics

`intel/tests/test_overlap_metric.py` (5 tests) covers:

- the head is written with ids only and the TTL from `head.ttl_s`;
- the second first page observes a Jaccard of 10/30, and `intel_repeat_display_total`
  rises by 10;
- nothing is written under `personalization_off`, or under a version without the `head`
  block (`home@1`);
- a refused write is counted and the page goes on;
- the Home view records the head of a ranked first page.

`/metrics` on dev exports the four new families.

### Query count

`test_continuation.py::test_first_page_costs_no_more_queries_than_home_v2` uses the same
world under `home@2` and then under r15 with filled pools. The r15 first page issues ≤ the
SQL queries of `home@2`, so pools add 0 SQL reads. How:

- the ids come from Redis;
- author, time, type and `in_feed` come from the eligibility content read, which runs
  anyway;
- the head is materialized from that same read.

A side effect: `home@2` first pages with pulled items now skip one `intel_content_ref`
query too.

## Tests

| Check | Result |
|---|---|
| `bash scripts/test-service.sh feed` (image rebuilt) | 641 collected: **640 passed, 1 skipped** (the alert-file test, which needs `infra/`, passes with `TARA_REPO` mounted: 5 of 5 in `test_hot_metrics.py`). `makemigrations --check`: "No changes detected". Phase 4 had 534 |
| Flaky, not R1 | `intel/tests/test_synthetic_origin.py::test_seed_command_scale_and_replace` failed in 2 full runs and in 1 of 10 isolated runs. Its RNG is seeded from a random account uuid and it touches no ranking code. On HEAD: 10 of 10 isolated passes |
| Migrations applied on dev (feed recreated) | `feed.0011_author_age_class`, `intel.0006_home_v2b_drafts` |
| `python scripts/smoke_test.py` (after recreating feed, feed-signals, feed-relay, feed-consumer) | all checks passed (twice) |
| `uvx ruff@0.17.3 check` / `format --check` (`services/feed`, `scripts/intel`) | clean |
| Dokploy size check | 74,890 < 100,000 |
| `scripts/intel/check_deploy.sh` | all checks ok |
| `promtool check rules` / `test rules` | 9 rules ok; the alert fires at 0.81, not at 0.79 |

New or extended test files, with their test counts:

- `test_measure_repetition.py` (8)
- `test_test_clock_guard.py` (16)
- `test_hot_metrics.py` (5)
- `test_overlap_metric.py` (5)
- `test_author_age.py` (16)
- `test_pools_basic.py` (13)
- `test_pools_suspect.py` (5)
- `test_continuation.py` (5)
- `test_account_deletion.py` (+2)
- `test_config_schema.py` (+15)
- `test_diversity.py` (+3)
- `test_eligibility.py` (+11, E9b)
- `test_eligibility_property.py`: the world now draws author age classes (adult, minor,
  unknown, no row), and asserts that no DISCOVERY item has a non-adult user author. It
  covers the new `discovery` source too.

The golden tests `test_home_v1_parity.py` and `test_home_v2.py` are unchanged and green.

## Migrations, events, env vars, beat tasks, routes

- **Migrations (additive):**
  - `feed/0011_author_age_class`: `author_ref.age_class` varchar(8), `adult | minor |
    unknown`, `db_default 'unknown'`;
  - `intel/0006_home_v2b_drafts`: data only. Three draft rows plus three `created`
    change-log rows, like `0004`, with no outbox event. Reversible: drafts may be deleted.
- **Events:** none new. `intel.config.changed` is unchanged.
- **Env vars:**
  - `INTEL_TEST_CLOCK_ENABLED` (feed, default false): in `.env.example`, a note in
    `.env_prod.example` (the compose file pins it), dev `x-feed-intel-env`, Dokploy
    `feed-env` (`"false"`), `scripts/gen-dokploy-env.sh` (a comment), the k8s feed
    configmap, and `docs/deploy/DOKPLOY.md`;
  - `REELS_SEEN_WINDOW_H` (post, read by Track B, default 72): in `.env.example`,
    `.env_prod.example`, Dokploy `post-env` (`${REELS_SEEN_WINDOW_H:-72}`),
    `gen-dokploy-env.sh`, `infra/k8s/overlays/post/configmap.yaml` and `DOKPLOY.md`. Dev
    compose post reads it from `.env` through `env_file`, since it lists no POST_* vars.
  - The k8s feed configmap also gains `REDIS_HOT_URL` (db 6 of the shared Redis). The k8s
    feed pods had none, so their hot cache pointed at localhost.
- **Beat task:** `intel.rebuild_pools`, a 60 s tick; it rebuilds only when
  `pools.rebuild_s` (300) has passed, and never under a version without pools. Wiring:
  - dev `feed-relay` (`celery worker -B`): `REDIS_HOT_URL` added;
  - Dokploy `feed-worker` (`-B`, `*feed-env` has `REDIS_HOT_URL`);
  - k8s `components/worker` (`-B`), already in the feed overlay.
- **Routes:** none new.

## Deviations, and why

1. **Pool source name `discovery`** (07 says `recommended_basic`), with reasons
   `rec_popular` and `rec_fresh`. This reuses the eligibility DISCOVERY class, post's
   hydration allowlist and why.py, as the planner decided.
2. **No activation.** `home@2b` and its arms are drafts. The phase-4 first-page cost open
   item still stands: p90 about 110 ms on dev in the control.
3. **The recommended slots are claimed inside the diversity re-ranker**
   (`diversity.rerank(..., insert=)`), instead of interleaving after it.
   - Interleaving after re-ranking shifted page boundaries, and so broke the author cap.
   - A second, position-based re-rank pass moved pool items forward. It gave a share of
     up to 0.30 under the 10% control: the decision-23 cap was broken.
   - With the slots claimed during selection, the share is exact (floor of k × share in
     every prefix), and the connection items are diversified around it.
   - At each slot, the best pool item that keeps the author, gap and format rules is
     taken.
4. **`continuation` follows the variant, not the viewer.** Under the control (home@2b)
   `continuation.pools` is false, so a thin viewer gets at most 10%, and a viewer with
   0 to 2 connection items gets none. Their first 10% slot is position 9. This follows
   07 ("only when the active variant has `mix.recommended > 0`") and the planner's note;
   decision 23's "empty home is worse" case stays empty under the control.
5. **Continuation when the connections window is full:** pool items still go into the
   session tail, before the older connection rows that follow in latest order. This
   keeps `has_more=false` from happening while pool items remain. `caught_up_index` is
   null there, because the inventory has not run out.
6. **The `head` block is a v2 block**, so `home@1` and `home@2` store no head and
   observe no overlap. The TTL must come from the config, and adding the block to the v1
   package defaults would have needed a v1 schema change.
7. **Data migration without an outbox event** (like `0004`). The rows are drafts. The
   staff actions that change live order still emit `intel.config.changed`.
8. **The test clock accepts `TARA_ENV` = `development` or `dev`.** Dev runs
   `TARA_ENV=development`, and 07 wrote "dev".
9. **The fresh-pool floor** is the freshness decay (`freshness.half_life_hours`) times
   the bait and duplicate multipliers, at or above `pools.fresh.min_score` (0.2).
   **`pools.max_members`** is the number of members read from each set per first page.
   07 left both undefined.
10. **The age-memo TTL** (7 days, `intel/age.py`) is a cache lifetime, not a ranking
    value. A lost memo costs one indexed read.
11. **Phase-4 finding, logged and not re-fixed:** WP 4.5 ("no 3 consecutive") against
    02's `max_same_format_run: 3` (02:347). Phase 4 resolved it as a deviation: home@2
    uses 2, and home@2b keeps 2.

## Open items

- **Activation of `home@2b` (home@3)** is a verifier or owner step:
  `intel_config activate home 3 --reason ...`. Before it, the phase-4 first-page cost:
  32 queries against a budget of 12, and p90 about 110 ms on dev.
- **The Dokploy host free memory (≥ 512 MB)** must be checked before deploying the
  384 MB / 448m redis-hot. The planner could not reach the host, and neither could this
  track.
- **E9b for graph people suggestions** moves to R4 (7.5-B2).
- **Thin viewers under the control:** with 0 to 2 connection items they see no
  recommendation and a short feed (decision 23's intent). Whether `continuation.pools`
  should apply to thin viewers in the control is an owner or config decision; it is one
  key in a new version.
- **k8s has no dedicated redis-hot.** The feed configmap points `REDIS_HOT_URL` at db 6
  of the shared Redis, which has no maxmemory or noeviction of its own.
- **Dev age classes:** 408 user authors are still `unknown`, because they have never made
  an authenticated feed request; they stay out of pools (fail closed).
- **The flaky seed-command test** (`test_seed_command_scale_and_replace`) should seed its
  RNG from a fixed account id.
