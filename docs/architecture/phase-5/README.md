# Phase 5 — Marketplace (Report)

> Status: **implemented**. Adds the **Marketplace** microservice (listings,
> categories, search, saves, reports, status state machine) and the
> **buyer/seller chat** flow — a cross-service event that the Chat service
> consumes to open a conversation.

---

## 1. Architecture changes

- **Marketplace** service (`market_db`): listings with a full **status state
  machine** (`draft → pending_review → active → reserved → sold`, plus
  `rejected`/`archived`), categories, media (Media `media_id`s), saves, reports,
  seller profiles, and DB-based search/filter (category, price range, condition,
  location, text).
- **Buyer/seller chat via event:** `POST contact` emits
  `marketplace.contact.requested`; the **Chat** service consumes it and opens
  (idempotently) a `marketplace`-type conversation linked to the listing — the
  first time a Phase-N service extends a Phase-(N-1) service purely through an
  event (no synchronous coupling).
- **Moderation-ready:** Marketplace already consumes `moderation.actioned`
  (listing remove/approve) and emits `listing.reported`, so the Phase-6
  Moderation service wires in without touching Marketplace code. A dev flag
  `MARKETPLACE_AUTO_APPROVE` activates listings immediately until then.
- Block-aware: consumes `user.blocked` so blocked sellers/buyers are hidden
  from each other in search and detail.

## 2. Files created / changed

**Marketplace** (`services/marketplace/`): `config/*`, `marketplace/{models,
services,events,serializers,views,urls,handlers,apps}.py`, `consume_events` +
`seed_categories` commands, tests, Dockerfile (seeds categories), packaging.

**Chat (extended):** `services.create_marketplace_conversation` +
`@on_event("marketplace.contact.requested")` handler + a regression test.

**Infra:** `postgres/init` (+market_db), `compose` (+3 services: marketplace
web/relay/consumer; Traefik `/api/v1/marketplace`), `prometheus.yml`
(+marketplace), `.env.example` (+market DB, secret, `MARKETPLACE_AUTO_APPROVE`).

## 3. Services added / changed

| Service | Role | Port | Notes |
|---------|------|------|-------|
| **marketplace** + relay + consumer | listings/search/saves | 8007 | status machine; consumes `moderation.actioned`, `user.blocked` |
| chat (extended) | + buyer/seller threads | 8006 | consumes `marketplace.contact.requested` |

## 4. Database changes

- **`market_db`**: `marketplace_category`, `seller_profile`, `listing`
  (indexed by status+category+time and by seller), `listing_media`,
  `listing_save` (unique per account+listing), `listing_report`, `blocked_pair`
  + platform tables. Money stored as `numeric(19,4)` + ISO-4217 `currency`.

## 5. API endpoints (live)

`/api/v1/marketplace/`: `GET categories`; `GET listings` (search/filter) +
`POST listings`; `GET my-listings`; `GET saved`; `GET/PATCH listings/{id}`;
`POST listings/{id}/{publish,transition,save,report,contact}`;
`DELETE listings/{id}/save`.

## 6. Event contracts

**Published (v1):** `listing.created`, `listing.updated`,
`listing.status.changed`, `listing.reported`, `marketplace.contact.requested`.
**Consumed:** `moderation.actioned` (status), `user.blocked`/`unblocked` (hide).
Chat consumes `marketplace.contact.requested`.

## 7. Tests

- **Marketplace:** create→publish→active & searchable; draft hidden from others
  (404); full status-transition machine incl. illegal-transition 409;
  search filters (price/category); save/unsave idempotent + count;
  contact emits event; can't contact own listing; report emits event;
  **moderation removal via handler** sets `rejected`.
- **Chat (regression):** `marketplace.contact.requested` creates exactly one
  marketplace conversation with both members (idempotent on re-delivery).
- **Quality gates:** `ruff` clean (232 files); `docker compose config` valid.

## 8. Commands

```bash
make up   # now also builds marketplace (+relay,+consumer); seeds categories
# direct dev access: marketplace http://localhost:8007/api/v1/docs/
# GET /api/v1/marketplace/categories/   (8 seeded categories)
```

## 9. Risks

| Risk | Mitigation |
|------|------------|
| DB-based search (icontains) won't scale | Phase 6 introduces the Search service (OpenSearch); Marketplace emits create/update events for indexing. |
| Buyer can't see the conversation id synchronously | Event-driven by design; the thread appears in the buyer's chat list (eventual). A `conversation.created` echo can be added later. |
| Auto-approve bypasses review in dev | `MARKETPLACE_AUTO_APPROVE` flag; off in prod → `pending_review` until Moderation (Phase 6) approves. |
| Payments / shipping | **Out of scope** (placeholders only) until compliance/provider/dispute/tax/fraud defined — never claimed as built. |
| Fraud detection | Hooks only (report + moderation pipeline); real detection is later. |

## 10. Rollback notes

- Additive: 1 new DB (`market_db`) + 3 compose services + an additive Chat
  handler/event. Rollback = revert the Phase-5 commit / drop
  `services/marketplace` + its compose blocks; the Chat handler is inert without
  the event. Earlier services untouched.
- `make clean` wipes dev volumes (incl. `market_db`).

## 11. Completion checklist

- [x] Listings: title/description/price/currency/condition/location/media
- [x] Categories (+ seed command); seller profiles
- [x] Status state machine (draft/pending_review/active/reserved/sold/rejected/archived)
- [x] Search/filter (category, price range, condition, location, text); cursor pagination
- [x] Save/unsave, report; block-aware visibility
- [x] Buyer/seller chat via `marketplace.contact.requested` → Chat conversation
- [x] Consumes `moderation.actioned` (Phase-6 ready) + `user.blocked`
- [x] Infra: market_db, compose services, Traefik route, Prometheus
- [x] `ruff` clean (232 files); `docker compose config` valid
- [x] **Verified: Marketplace 9/9 and Chat 10/10 green against PostgreSQL**;
      `ruff` clean (232 files); `docker compose config` valid.
- [ ] **Your approval to proceed to Phase 6 — Notifications, Search, Moderation, Admin.** ← gate

### Verification notes

Run on the host venv against Dockerized Postgres (in-container image build
blocked only by the sandbox corporate-CA TLS limit; CI builds images). One real
code bug fixed: the Chat `dm_key` field (max 80) overflowed for the marketplace
thread key (`mkt:<listing>:<buyer>:<seller>` ≈ 114 chars) → widened to 160, with
the Chat regression test now covering it.
