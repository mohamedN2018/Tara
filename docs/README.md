# Tara — Documentation Index

**Tara** is a production-grade, horizontally-scalable social networking platform
(web today; iOS/Android-ready API contracts). This directory holds the living
architecture and engineering documentation.

> **Status:** all phases have been implemented and are being hardened. Start with
> the [review and plan](architecture/project-review-and-plan.md). Deployment:
> [Dokploy guide](deploy/DOKPLOY.md). The Phase 0 documents below describe the
> original design; where they differ from the code, the code wins.

## Phase 0 deliverables

| # | Document | Purpose |
|---|----------|---------|
| 00 | [Overview & Discovery](architecture/phase-0/00-overview-and-discovery.md) | Executive summary, repo inspection, scope, glossary |
| 01 | [Domain Map](architecture/phase-0/01-domain-map.md) | Bounded contexts, ubiquitous language, context relationships |
| 02 | [Service Boundaries](architecture/phase-0/02-service-boundaries.md) | The 17 services, ownership, sync/async deps, deployment topology, degradation matrix |
| 03 | [API Contracts](architecture/phase-0/03-api-contracts.md) | REST conventions, versioning, pagination, errors, idempotency, endpoint catalog |
| 04 | [Event Contracts](architecture/phase-0/04-event-contracts.md) | Event envelope, catalog, outbox pattern, topics, retries, DLQ |
| 05 | [Data Model Plan](architecture/phase-0/05-data-model-plan.md) | Database-per-context, core entities, keys, indexes, partitioning, soft delete |
| 06 | [Infrastructure Plan](architecture/phase-0/06-infrastructure-plan.md) | Dev (Compose) & prod (K8s), gateway, observability, CI/CD, secrets |
| 07 | [Migration & Rollout](architecture/phase-0/07-migration-and-rollout.md) | Greenfield note + service-extraction (strangler-ready) strategy |
| 08 | [Risk Register](architecture/phase-0/08-risk-register.md) | Risks, severity, mitigation, owners |
| 09 | [Decision Log (ADRs)](architecture/phase-0/09-decision-log.md) | Key decisions + the ones needing your confirmation |

## How to read this

1. Start with **00 — Overview & Discovery**.
2. Read **09 — Decision Log** to see the choices that need your sign-off before Phase 1.
3. The rest provide the depth behind those decisions.

## Phase roadmap (high level)

`Phase 0` Discovery & Architecture ·
`Phase 1` Foundation (gateway, identity, observability, CI) ·
`Phase 2` Profile & Social Graph ·
`Phase 3` Posts & Feed & Media ·
`Phase 4` Chat & Real-Time ·
`Phase 5` Marketplace ·
`Phase 6` Notifications, Search, Moderation, Admin ·
`Phase 7` Advertisement ·
`Phase 8` Frontend completion ·
`Phase 9` Scale, security, production readiness.

Each phase ends with a fixed report: architecture changes, files, services, DB
changes, endpoints, events, tests, commands, risks, rollback notes, and a
completion checklist (per the execution rules).
