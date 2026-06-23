# 07 — Migration & Rollout Strategy

## 1. Migration from an existing monolith — Not Applicable

The brief asks for a "migration plan from existing monolith **if applicable**."
Discovery (doc 00) confirmed the repository is **greenfield**: only `README.md`
and `.gitignore` exist; there is no code, database, or service to migrate.

Therefore there is **no monolith migration**. This document instead defines:
1. the **service-extraction (strangler-ready) strategy** that keeps future
   carve-outs cheap, and
2. the **phase-by-phase build & rollout** plan with rollback discipline, and
3. the **disaster-recovery** approach.

## 2. Service-extraction (strangler-ready) strategy

We start as true microservices in a monorepo (ADR-001/002). To make moving any
context into its own repo/team a *lift-out, not a rewrite*, we enforce from day
one:

- **Own database per context** — no shared schema, no cross-DB FKs. Extraction
  needs no data untangling.
- **Public API + events only** between contexts — no importing another
  context's Django models. The seam is already a network boundary in contract.
- **Shared kernel stays thin** (`libs/`) — only envelope, auth, resilience,
  observability helpers. The less shared code, the cheaper the split.
- **`EventPublisher` abstraction** — transport (RabbitMQ→Kafka) and topology
  changes don't touch business code.
- **Independent settings/Dockerfile/migrations per service** — each is already
  shippable alone.

**Promotion checklist** (when a context needs its own repo/team/scaling):
1. Move `services/<x>` + its slice of `libs` usage into a new repo (or its own
   pipeline).
2. Point it at its already-separate database.
3. Re-bind its event queues; no schema migration of *other* services.
4. Route its paths at the gateway to the new deployment.
5. Done — consumers are unaffected because the contract (API + events) is unchanged.

## 3. Build order (phases) and what unblocks what

```
P1 Foundation ─────────────► everything (gateway, identity/auth, observability, CI)
   ├─ P2 Profile+Graph ─────► P3, P4, P5 (need identities, relationships, display)
   │     └─ P3 Posts+Feed+Media ─► P6 (search/notif indexing), P7 (sponsored feed)
   │            └─ P4 Chat+Realtime ─► P5 buyer/seller chat
   │                   └─ P5 Marketplace ─► P6 moderation/search of listings
   │                          └─ P6 Notif+Search+Moderation+Admin
   │                                 └─ P7 Ads
   └────────────────────────────────────► P8 Frontend completion ─► P9 Scale/Sec/Prod
```

Each phase is independently demoable and leaves the system in a working,
deployable state (no "big bang").

## 4. Per-phase deliverable contract (every phase ends with this)

Per the execution rules, each phase report contains:
1. Architecture changes · 2. Files created/changed · 3. Services added/changed ·
4. Database changes · 5. API endpoints · 6. Event contracts · 7. Tests ·
8. Commands · 9. Risks · 10. Rollback notes · 11. Completion checklist.

## 5. Database migration discipline (within a service)

- **Expand/contract** (a.k.a. parallel-change): add new columns/tables (expand)
  → deploy code that writes both/reads new → backfill → switch reads →
  remove old (contract) in a later release. Rolling deploys never see an
  incompatible schema.
- Migrations are **forward-only in production**; "rollback" = a new corrective
  migration, plus a tested restore path for data-loss cases.
- Every migration reviewed for lock impact on large tables (use
  `CREATE INDEX CONCURRENTLY`, batched backfills, no long table rewrites in peak).

## 6. Rollback strategy (general)

| Layer | Rollback mechanism |
|-------|--------------------|
| App code | Redeploy previous image tag (immutable, versioned per service). |
| Schema | Expand/contract means previous image still works against new schema; if not, corrective migration + restore. |
| Feature | **Feature flag off** — fastest rollback for a misbehaving module (no deploy). |
| Events | Stop a bad consumer, fix, replay from DLQ / re-drive from offset. |
| Data corruption | PITR restore of the affected context's DB (isolation limits blast radius). |
| Traffic | Canary/blue-green: shift traffic back to the stable version at the ingress. |

Because each context is isolated (own DB, own deploy), a rollback in one service
does **not** force rollbacks elsewhere — a direct benefit of the boundaries.

## 7. Disaster recovery (matured in Phase 9, planned now)

- **Backups:** automated per-DB backups + WAL/PITR; object storage versioning;
  config/secret backups in the secret manager.
- **RPO/RTO targets** (to confirm with you): e.g. RPO ≤ 5 min (PITR),
  RTO ≤ 1 hour for core contexts. Non-core (analytics) looser.
- **Restore testing:** scheduled restore drills into an isolated environment;
  a DR runbook per service.
- **Multi-AZ** for managed datastores; cross-region backup copies for the
  worst case.
- **Degradation-first:** even during partial DR, the degradation matrix
  (doc 02 §5) keeps core browsing alive while a failed context recovers.

## 8. Rollout safety checklist (per release)

- [ ] Migrations are expand/contract & lock-safe.
- [ ] New events are additive or version-bumped with consumer notes.
- [ ] Feature flag wraps any user-visible new behavior.
- [ ] Health/readiness reflects new dependencies.
- [ ] Dashboards/alerts updated for new metrics.
- [ ] Smoke tests + automated rollback wired in CD.
- [ ] Rollback note written (what flag/tag/restore to use).
