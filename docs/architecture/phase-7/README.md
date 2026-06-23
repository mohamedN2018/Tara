# Phase 7 — Advertisement (Report)

> Status: **implemented**. Adds the **Advertisement** service (advertisers,
> campaigns, ad sets, creatives, review, serving, impression/click tracking,
> budgeting) and blends **sponsored slots** into the Feed — degrading to organic
> content if Ads is unavailable.

---

## 1. Architecture changes

- **Ads** service (`ads_db`): advertiser accounts → campaigns → ad sets →
  creatives, with a **review workflow** (RBAC `ad_reviewer`/`admin`), eligibility
  serving (approved + active + in-schedule + in-budget), **frequency capping**
  (Redis, per viewer/creative), and **impression/click ingest** that is
  **deduplicated** (Idempotency-Key) and **rate-limited**, debiting an
  append-only **budget ledger** and emitting firehose events.
- **Privacy-safe metrics:** impression/click rows store only a coarse
  `viewer_bucket` (2-hex of a hash) — never the raw viewer id (brief §10).
- **Feed integration:** the Feed home endpoint blends one sponsored creative
  via the Ads **internal feed-slot** API behind a circuit breaker; if Ads is
  down it returns `sponsored: null` and the organic feed is unaffected —
  the brief's "if ads fail, show organic feed" requirement, demonstrated.
- **Targeting & billing are architecture-only:** targeting JSON is stored but
  not evaluated yet; the budget ledger is a simple debit model, not a real
  billing/payments system (placeholder, per the brief).

## 2. Files created / changed

**Ads** (`services/ads/`): full Django service — `config/*`,
`ads/{models,services,events,serializers,views,internal_views,urls,
internal_urls,permissions,apps}.py`, packaging, tests.

**Feed (extended):** `feed/ads_client.py` (circuit-broken internal call) +
`HomeFeedView` blends the sponsored slot + 2 regression tests.

**Infra:** `postgres/init` (+ads_db), `compose` (+ads, ads-relay; Traefik
`/api/v1/ads`), `prometheus.yml` (+ads), `.env.example`.

## 3. Services added / changed

| Service | Role | Port | Notes |
|---------|------|------|-------|
| **ads** + relay | advertiser/campaign/serving/events | 8013 | RBAC review; frequency cap; budget ledger; internal feed-slot |
| feed (extended) | + sponsored slot | 8005 | circuit-broken Ads call; degrades to organic |

## 4. Database changes

- **`ads_db`**: `advertiser_account` (unique owner), `campaign` (budget/spent/
  schedule/status), `ad_set` (placement, cpc/cpm, frequency_cap, targeting json),
  `ad_creative` (review_status), `ad_review`, `ad_impression_event` /
  `ad_click_event` (day-partition + Kafka-firehose candidates; `viewer_bucket`
  only), `ad_budget_ledger` (append-only) + outbox/processed/idempotency.

## 5. API endpoints (live)

`/api/v1/ads/`: `GET/POST campaigns`, `GET campaigns/{id}/report`,
`POST campaigns/{id}/ad-sets`, `POST ad-sets/{id}/creatives`,
`POST creatives/{id}/review` (reviewer), `POST events` (impression/click,
deduped + throttled). Internal: `GET /internal/v1/ads/feed-slot?viewer=`.

## 6. Event contracts

**Published (v1):** `ad.review.decided`, `ad.impression.recorded`,
`ad.click.recorded` (firehose-bound; carry only `viewer_bucket`). No inbound
consumers (Analytics, Phase 0 placeholder, will consume the firehose).

## 7. Tests

- **Ads:** create campaign + serve eligible creative; **pending creative not
  served**; **frequency cap** (capped viewer skipped; others unaffected);
  impression+click **debit budget** + emit events (+ bucket is 2 chars, no raw
  id); **budget exhaustion completes campaign** (no longer served); **review
  RBAC** (403 non-reviewer / 200 reviewer); **events dedupe** via Idempotency-Key;
  internal feed-slot requires internal token.
- **Feed (regression):** home feed **blends a sponsored slot**; **degrades to
  `sponsored: null`** when Ads is unavailable (feed still 200) + existing
  fan-out tests still pass.
- **Quality gates:** `ruff` clean (343 files); `docker compose config` valid.

## 8. Commands

```bash
make up   # builds ads (+relay); Feed now calls ads for a sponsored slot
# direct dev: ads http://localhost:8013/api/v1/docs/
```

## 9. Risks

| Risk | Mitigation |
|------|------------|
| Ad-event firehose volume on the transactional broker | Events isolated; move to Kafka/Redpanda firehose at scale (ADR-003); dedup + rate-limit at ingest. |
| Sponsored insertion adds a sync call to feed reads | Circuit breaker + short timeout + degrade-to-organic; only on the first page. |
| Targeting not evaluated | **Architecture only** (stored, not matched) — clearly labeled; real targeting + privacy/consent review is a later phase. |
| Billing/payments | **Placeholder ledger** only — no real charging/invoicing/tax until the payments module's compliance is defined. |
| Frequency cap in Redis is best-effort | Acceptable; exact accounting via the impression event store if needed. |

## 10. Rollback notes

- Additive: 1 DB (`ads_db`) + 2 compose services + a Feed client/2 tests + a
  setting. Rollback = revert the Phase-7 commit / drop `services/ads` + its
  compose blocks; the Feed `ads_client` import is local to the view and inert if
  Ads is absent (returns null → organic feed). Earlier services untouched.
- `make clean` wipes dev volumes (incl. `ads_db`).

## 11. Completion checklist

- [x] Advertiser accounts, campaigns, ad sets, creatives
- [x] Review workflow (RBAC reviewer/admin) + `ad.review.decided`
- [x] Serving: eligibility (approved/active/in-schedule/in-budget) + frequency cap
- [x] Impression/click ingest: dedup (Idempotency-Key) + rate-limit + budget ledger + firehose events
- [x] Privacy-safe metrics (viewer_bucket, never raw id)
- [x] Sponsored slot blended into Feed; **degrades to organic** if Ads down
- [x] Campaign reporting (impressions/clicks/CTR/spend)
- [x] Infra: ads_db, compose, Traefik route, Prometheus
- [x] `ruff` clean (343 files); `docker compose config` valid
- [x] **Verified: Ads 8/8 and Feed 6/6 green against PostgreSQL**; `ruff` clean
      (343 files); `docker compose config` valid.
- [ ] **Your approval to proceed to Phase 8 — Frontend.** ← gate

### Verification notes

Run on the host venv against Dockerized Postgres (in-container image build
blocked only by the sandbox corporate-CA TLS limit; CI builds images). No
service-code bugs; one Feed **test** assertion was corrected (`sponsored` is a
sibling of `data` in the response envelope, not nested).
