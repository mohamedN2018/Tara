# Tara technical and deployment documentation plan

| | |
|---|---|
| Status | Plan only. Nothing in this document has been written yet. |
| Date | 2026-11-03 |
| Branch | `feat/web-social-platform` |
| Audience | Tara engineers and the product owner (Mohammed) |
| Scope | Which documents the ten-module build needs, where they live, who writes them and when they must be finished. It covers technical docs, deployment and upgrade notes, runbooks, decision records and staff guides. |

Companion documents: [04-roadmap.md](04-roadmap.md) (build order and milestones) and [05-database-architecture.md](05-database-architecture.md) (data layer).

---

## 1. Why this plan exists

The roadmap counts docs inside each milestone's estimate (04 §1). Its definition of done (04 §3.2, items 5, 7 and 8) requires event documentation, updated docs and a deploy note for every milestone. Before this plan, nothing said which documents those are. The only documentation work the roadmap mentioned was runbook updates in 10.7, a LiveKit runbook and the event contracts. This plan fills that gap.

---

## 2. What exists today (verified, read-only)

| Document | Location | State |
|---|---|---|
| Architecture phase docs | `docs/architecture/phase-0/` (`00` to `09`) and `docs/architecture/phase-1/` to `phase-9/` | Phase 0 holds the domain map, service boundaries, API and event contracts, data model, infrastructure, rollout, risk register and decision log |
| Decision log | `docs/architecture/phase-0/09-decision-log.md` | ADR-001 to ADR-009, all from Phase 0 |
| Event catalogue | `docs/architecture/phase-0/04-event-contracts.md` (§5 catalogue per service, §6 schema governance) | prose only |
| Event JSON Schemas | `libs/tara_events/tara_events/schemas/` | a `README.md` only |
| API reference | every Django service serves `/api/v1/schema/` and `/api/v1/docs/` (drf-spectacular; for example `services/post/config/urls.py`) | generated at runtime, not committed, not checked in CI |
| Deploy guide | `docs/deploy/DOKPLOY.md` | prerequisites, environment generation, service creation, deploy, operations, backups and notes. There are no per-release upgrade notes. It gives "~40 containers" and "about 4.6 GB at idle", while `docs/architecture/project-review-and-plan.md` gives 43 containers and 5.7 GB. The step 1 deploy note reconciles the two. |
| Project status | `docs/architecture/project-review-and-plan.md` | status and open items |
| Brand | `docs/design/brand.md` | the brand system |
| Ecosystem review | `docs/ecosystem/01` to `06` | review and plan |
| Per-service READMEs | none (`services/*/README.md` does not exist) | none |
| Runbooks | none as documents; short operations notes in `docs/deploy/DOKPLOY.md` §5 | none |
| Staff guides (admin, moderator, finance) | none | none |

---

## 3. The documentation set

| # | Document | Location | Contents | Written by | Finished when | Checked by |
|---|---|---|---|---|---|---|
| D1 | API reference per service | generated at `/api/v1/schema/`; committed snapshot `docs/api/<service>.openapi.yaml` (new) | every public and internal endpoint, with `extend_schema` annotations for the `{"data": ...}` envelope, cursor parameters and error codes | the milestone's engineer | in the PR that changes an endpoint | CI: `manage.py spectacular --validate --fail-on-warn` per service, plus a diff of the snapshot that flags breaking changes |
| D2 | Service README | `services/<service>/README.md` (new) | purpose; Django apps; models owned; internal endpoints and which callers may use them (including the 1.0d caller-specific secrets); events produced and consumed; queue and DLQ names; periodic jobs; env var **names**; management commands (backfills, `privatize_*`, `relabel_*`, `classify_*`) | the engineer of the first milestone that touches the service | that milestone, then kept current | review |
| D3 | Event catalogue and schemas | `docs/architecture/phase-0/04-event-contracts.md` §5 and `libs/tara_events/tara_events/schemas/<event_type>.v<n>.json` | per event: producer, consumers, payload (ids and enums only, 04 §3.3), version, the emission flag, and the release in which emission was turned on (two-release rule, 1.0g) | the milestone's engineer | in the milestone that adds or changes the event; older events backfilled in 10.2 | review until 10.2, then CI contract tests |
| D4 | Architecture decision records | `docs/architecture/adr/NNNN-<slug>.md` (new folder, numbering continues from ADR-010; `09-decision-log.md` keeps ADR-001 to ADR-009 and links to the folder) | context, decision, consequences, status (Proposed → Accepted), and a link to the row in 04 or 05 | the engineer drafts; the product owner accepts | before the milestone that implements the decision | product owner sign-off |
| D5 | Runbooks | `docs/runbooks/<topic>.md` (new) | symptom, the alert that fires, diagnosis commands, fix, rollback, who to tell | the engineer of the milestone named in §4 | with that milestone | rehearsed once in 10.7 |
| D6 | Deploy and upgrade notes | `docs/deploy/DOKPLOY.md`, new section "Upgrade notes", one entry per step and per milestone that changes the deploy | env var names added or removed (never values); new containers with their memory limits; migration order and one-off commands with expected run time; event types whose emission flag flips; compatibility windows (WebSocket `?token=`, refresh token in the body, the old ads serve-token key); rollback steps. `scripts/gen-dokploy-env.sh` is changed in the same PR. | the milestone's engineer | same PR (04 §3.2, item 8) | review; rehearsed in 10.7 |
| D7 | Staff guides, Arabic and English | `docs/guides/staff/ar/` and `docs/guides/staff/en/` (new) | see §3.2 | the engineer drafts English; Arabic by the product owner or a translator | each guide with its milestone; the full set reviewed in step 8 | product owner |
| D8 | User-facing policies | stored as versioned `ContentPolicy` rows (8.10), seller terms (4.12), age-gate text (2.12), privacy notice | community standards, seller terms, age wording, privacy | product owner with legal counsel | before the milestone that shows them | legal review (04 §21, decision 6) |
| D9 | Data architecture | [05-database-architecture.md](05-database-architecture.md) | the §7.3 milestone tag and any changed model row, when a migration merges | the milestone's engineer | same PR | review |
| D10 | Design | `docs/design/brand.md` and the shared component docs | tokens, components, RTL rules | the frontend engineer | 9.1 and 9.4 | review |
| D11 | Capacity record | `docs/deploy/capacity.md` (new) | numbers measured on the target server: transcode throughput (5.16), k6 results, WebSocket sockets, Redis and Postgres headroom (10.6) | the engineer of 5.16 and 10.6 | 10.6 | product owner (server-size decision) |

### 3.1 ADR backlog

The ADR backfill (2 days, weeks 3–4 of step 1, counted in 04 §16 as part of the "Docs" row) writes short records for decisions that are already made in the plan, so later engineers can find the reason. Overlapping rows become one ADR.

- [05](05-database-architecture.md) §5, decisions 1–18.
- [04](04-roadmap.md) §4, D1–D13. D2 matches 05 row 2, D5 matches row 3 and D8 matches row 6, so each pair becomes one ADR.
- Decisions from the critic review:
  - caller-specific internal secrets for identity (1.0d) and an ads-only serve-token secret (1.0e);
  - dead-letter routing set by RabbitMQ policy (1.0c);
  - two-release event rollout and the alternate exchange (1.0g);
  - content media private by default, with the owning service minting URLs (1.5);
  - age leaves identity only as token claims (2.12);
  - suspension ordering: identity first, with an idempotency key, then reconcile (8.4);
  - the file-scanning choice (3.10);
  - Redis `noeviction` with `maxmemory`, and `redis-hot` (1.0h, 1.7);
  - dedicated beat (L.2).

### 3.2 Staff guides (D7)

| Guide | Milestone |
|---|---|
| Listing pre-review queue | 4.1 |
| Ad review and creative policy | 6.4, 6.5, 6.12 |
| Top-up verification for the `finance` role, with separation of duties | 6.3 |
| Report triage and actions per target type | 8.2 |
| Suspensions and feature restrictions | 8.4, 8.5 |
| Appeals and four-eyes resolution | 8.8 |
| Blocked terms: when to use "flag" and when "hold" | 8.9 |
| Reading reported private messages (policy, retention, audit) | 8.2, legal review |
| Company page verification and page moderation | 7.3, 7.10, 8.7 |
| Staff two-factor enrolment and recovery | L.4 |
| CSAM escalation (restricted access) | L.6 |

---

## 4. Documentation owed per step

A step is not closed until its row exists. Runbooks are named by topic and live in `docs/runbooks/`.

| Step | Documents that must exist when the step closes |
|---|---|
| 1 | READMEs for post, feed, graph, search, profile, moderation, media, identity and ads. Runbooks: DLQ inspection and replay (`consume_events --replay-dlq`, `tara.events.unrouted`); the broker topology migration and its rollback (1.0c); secret rotation for `INTERNAL_JWT_SECRET`, the identity caller secrets and the ads serve-token secret (1.0d, 1.0e); Redis full under `noeviction` and `redis-hot` (1.0h, 1.7); deploys and upgrades (two-release events, migrate wait, rolling back a release, 1.0g); the private-media rollout and 404 spikes on `/tara-media/` (1.5). Events and schemas: the four new `*.reported` events, comment, story, group and gathering events. The ADR backfill. The step 1 deploy note, including the container-count reconciliation. |
| 2 | READMEs for notification and realtime. Event catalogue entries for the new notification sources and kinds. The age-claims ADR. The deploy note, including the refresh-token-in-body compatibility window (2.13). The age-gate text (D8). |
| 3 | README for chat. Runbooks: LiveKit and TURN (ports, external IP, lost webhooks and the reconcile job, 3.7); `media-scanner` (down, signature updates, releasing a quarantined file, 3.10). The scanning-choice ADR. The deploy note: firewall ports, `Permissions-Policy`, the `?token=` compatibility window, the `media-scanner` memory limit. |
| 4 | README for marketplace. Staff guide: listing pre-review. The deploy note: the 4.3 data commands with their run times, the `geolocation=(self)` header. Seller terms (D8). |
| 5 | Runbook: transcoder backlog, crash loop, and the raised RabbitMQ consumer timeout (5.2, 5.16). The deploy note: the transcoder container, the restricted MinIO user, the video-creation switch turned back on. First capacity numbers from 5.16 (D11). |
| 6 | Staff guides: ad review, top-up verification. Runbook: ads money incidents (settlement rerun, invalid-traffic refunds, turning the serving switch on and off). The deploy note: `ADS_SERVING_ENABLED` turned on after 6.3, `ads-consumer`, `ADS_AGE_TARGETING_ENABLED` left off. |
| 7 | The careers section of the profile README. Staff guide: company page verification. |
| 8 | README for admin. Staff guides: triage, suspensions, appeals, blocked terms, private-message access. Runbook: suspension incidents (a dead-lettered consumer leaves content visible; reading the reconcile job's output). The suspension-ordering ADR. The content policy (D8). The full staff-guide review in Arabic and English (3 days, the "Docs" row in 04 §16). |
| 9 | `docs/design/brand.md` and the shared component docs (D10). |
| 10 | Capacity record (D11). Every runbook rehearsed once (10.7). The event schema backfill complete (10.2). |
| L | L.1: alert catalogue (what each alert means, which runbook it points to). L.2: beat container down and missed periodic jobs. L.3: Postgres connections and the PgBouncer switch. L.4: staff 2FA guide, and secret rotation completed for JWT signing keys (JWKS `kid`), MinIO users and the Redis and RabbitMQ passwords. L.5: erasure requests and a stuck erasure in one service, plus the user-facing deletion text. L.6: CSAM escalation (restricted). |

---

## 5. The documentation line in the definition of done

04 §3.2 items 5, 7 and 8 are the rule. As a PR checklist:

```text
- [ ] OpenAPI: `manage.py spectacular --validate` passes; snapshot in docs/api/ updated
- [ ] Events: catalogue entry and JSON Schema for each new or changed event; emission flag noted
- [ ] Service README updated (endpoints, callers, events, queues, jobs, env var names, commands)
- [ ] Runbook added or updated if this milestone adds an alert, a container or a one-off command
- [ ] ADR accepted if this milestone implements a decision
- [ ] Deploy note in docs/deploy/DOKPLOY.md (env var names only, containers, migration order,
      commands, flags, compatibility windows, rollback); gen-dokploy-env.sh updated
- [ ] Arabic and English text for any staff guide or user-facing policy touched
```

---

## 6. Ownership and rules

- With one engineer, the engineer who builds a milestone writes its docs, and the product owner reviews ADRs, staff guides and policies. With two engineers, each reviews the other's docs.
- No document contains a secret value. Env documentation lists variable names and says where they are generated (`scripts/gen-dokploy-env.sh`).
- Staff guides and user-facing policies are written in both Arabic and English, and the Arabic text is reviewed by a native speaker.
- When a document and the code disagree, the code wins, and the document is fixed in the next PR that touches that area.

---

## 7. Effort

- **Inside milestone estimates** (04 §1): API annotations, READMEs, event entries and schemas, runbooks, deploy notes and the 05 updates.
- **Separate, 5 days** (the "Docs" row in 04 §16): the ADR backfill (2 days, step 1) and the staff-guide review and translation check (3 days, step 8).
- **Not estimated:** legal drafting of the policies (product owner and counsel), and translation done by someone other than the engineer.

---

## 8. Sources

Read directly for §2: the `docs/architecture/` directory listing, `docs/architecture/phase-0/09-decision-log.md` (ADR headings), `docs/architecture/phase-0/04-event-contracts.md` (headings), `libs/tara_events/tara_events/schemas/` (directory listing), `services/post/config/urls.py` (schema and docs routes), `docs/deploy/DOKPLOY.md` (headings and notes), `docs/architecture/project-review-and-plan.md` (lines 38 and 184), and a check that no `services/*/README.md` exists.
