# 09 — Decision Log (ADRs)

Architecture Decision Records. Status: **Proposed** until you approve Phase 0.
The first four ADRs are the ones we most want your explicit confirmation on
before Phase 1 — they shape the repo layout and ops surface.

---

## ADR-001 — True microservices: each context is an independently deployable service

- **Status:** ✅ **Accepted** (user decision, 2026-06-23)
- **Context:** The brief mandates microservices, fault isolation, database-per-
  service, and horizontal scaling. When presented the choice, the user
  explicitly chose **microservices** (over a modular-monolith-in-cells).
- **Decision:** Each of the **17 bounded contexts is its own independently
  deployable microservice** — own process, own container image, own database,
  own REST API, own event channels, own CI/CD pipeline, own scaling policy.
  **No shared schema, no cross-context model imports, no cross-DB foreign keys.**
  All cross-context communication is via versioned REST (read-time only, wrapped
  in timeout + retry + circuit breaker + fallback) or async events
  (outbox → broker).
- **Why this satisfies the brief:** true per-process fault isolation (one
  service crashing cannot take down another), independent horizontal scaling per
  service (own HPA), real database-per-service from day one, event-driven via
  the outbox pattern.
- **Consequences:** Higher operational surface (17 deployments, pipelines,
  dashboards). Managed by: (a) a **monorepo** for shared tooling + atomic
  contract changes (ADR-002); (b) **Compose profiles** so dev runs only the
  services in play; (c) **strict phasing** — Phase 1 builds only the foundation
  + Identity; remaining services come online phase by phase, never all 17 at
  once; (d) **managed datastores** in prod to cap ops load.
- **Boundary discipline:** enforced in code review + CI (an import-linter rule
  forbids cross-context imports; each service gets its own DB credentials so a
  cross-DB query is impossible) — this prevents the monorepo degrading into a
  distributed monolith.

---

## ADR-002 — Monorepo hosting independent microservices (chosen for dev speed)

- **Status:** ✅ **Accepted** (architect decision; user delegated: "do what
  suits development, speed, and robustness")
- **Decision:** The microservices of ADR-001 live in a **single git repo**:
  `services/*` (each an independently deployable service), `libs/*` (thin shared
  kernel), `frontend/web`, `infra/*`. Path-filtered CI builds/tests/ships only
  the changed services. Each service still has its **own image, DB, pipeline,
  and deployment** — the monorepo is a development-time convenience, not runtime
  coupling.
- **Rationale:** A monorepo gives a small team atomic cross-cutting changes, one
  source of truth for event schemas/API contracts, and shared tooling — the
  fastest way to develop true microservices without polyrepo versioning
  overhead. A context can still be lifted into its own repo later (ADR-001's
  extraction path).
- **Consequences:** Need path filters, `CODEOWNERS`, and an import-linter rule
  forbidding cross-context imports so the monorepo never degrades into a
  distributed monolith.

---

## ADR-003 — RabbitMQ first (events + Celery); Kafka for the ad/analytics firehose

- **Status:** ✅ **Accepted** (architect decision; user delegated this choice to
  "what suits development, speed, and robustness")
- **Decision:** Use **RabbitMQ** as the broker for domain events (via the
  `EventPublisher` abstraction + outbox) **and** as the Celery task broker in
  Phases 1–6. Introduce **Kafka/Redpanda** for the **high-volume, replayable
  ad-impression/click + analytics firehose** in Phase 7 (optional Redpanda
  profile available earlier for testing).
- **Rationale:** RabbitMQ is simpler to operate, pairs naturally with Celery,
  and is more than sufficient for transactional domain-event volumes early.
  Kafka's partitioned, replayable log is the right tool specifically for the
  firehose. The abstraction means the transport can change without touching
  business code.
- **Consequences:** Two brokers eventually (acceptable; different jobs). If you
  prefer **Kafka for everything from day one**, we adopt it now (more ops, but
  one event backbone) — your call.

---

## ADR-004 — OpenSearch for search

- **Status:** ✅ **Accepted** (architect decision; user delegated this choice)
- **Decision:** **OpenSearch** (Apache-2.0) over Elasticsearch.
- **Rationale:** Avoids Elastic's SSPL licensing considerations; API-compatible
  enough; strong for the user/page/post/listing/hashtag + autocomplete needs.
- **Consequences:** None blocking. If you have an existing Elasticsearch
  investment/license, we switch — the search adapter abstracts the client.

---

## ADR-005 — JWT access + rotating refresh, Argon2id, JWKS verification

- **Status:** Proposed
- **Decision:** Short-lived access JWT (~15 min) + opaque rotating refresh
  token with **family reuse detection**; web stores refresh in `httpOnly;
  Secure; SameSite=Strict` cookie, mobile in secure keystore. Passwords hashed
  with **Argon2id**. Services verify access tokens locally via Identity's
  **JWKS** (no per-request call to Identity). 2FA (TOTP) schema present, enabled
  later.
- **Rationale:** Standard, secure, mobile-friendly, decentralized verification
  (no auth hotspot), replay-resistant.

---

## ADR-006 — Django Channels for the realtime gateway (extractable later)

- **Status:** ✅ **Accepted** (architect decision; user delegated this choice)
- **Decision:** Implement the WebSocket gateway with **Django Channels (ASGI)**
  backed by a **Redis channel layer**, bridged to the event bus. Source of truth
  for messages/notifications stays in Chat/Notification, never only in a socket
  node. Clients reconnect with backoff and fall back to polling.
- **Rationale:** Keeps the stack uniformly Python early; good enough for initial
  connection volumes. If connection counts demand it, extract a dedicated
  Node/Go gateway — the contract (event envelope over WS) doesn't change.
- **Consequences:** Python WS has a lower per-node connection ceiling than
  Node/Go; mitigated by horizontal scaling and revisited in Phase 9.

---

## ADR-007 — UUIDv7 public identifiers

- **Status:** Proposed
- **Decision:** UUIDv7 (time-ordered) for public-facing PKs; optional `bigint`
  surrogate + UUID external id for very high-volume internal tables.
- **Rationale:** Globally unique (safe across distributed services & future
  splits), non-enumerable in URLs, and time-ordering keeps B-tree index locality
  good (unlike random UUIDv4).

---

## ADR-008 — Edge proxy (Traefik) + thin BFF, not a fat gateway

- **Status:** Proposed
- **Decision:** Traefik at the edge (TLS, routing, global rate-limit, request-id)
  + a **thin BFF** for client-shaped aggregation, per-user rate limiting,
  circuit breaking, and degradation fallbacks. Internal endpoints never exposed
  to clients.
- **Rationale:** Separates raw routing from business aggregation; keeps the BFF
  focused and the security boundary clear.

---

## ADR-009 — PostgreSQL native partitioning for high-volume tables

- **Status:** Proposed
- **Decision:** Declarative range/hash partitioning for `message`,
  `notification`, ad events, `feed_item`, audit/security logs, analytics
  (doc 05 §4), auto-managed (pg_partman or scheduled task).
- **Rationale:** Keeps hot tables performant and enables cheap retention/archival
  without app changes.

---

## Decisions explicitly deferred (placeholders only — never claimed as built)

| Topic | Why deferred | Revisit |
|-------|-------------|---------|
| End-to-end encryption | Needs full key mgmt, multi-device, backup/recovery | dedicated future phase |
| Real payments & shipping | Compliance, provider, dispute, tax, fraud undefined | post-MVP module |
| iOS / Android apps | Out of scope this cycle; APIs designed to support them | future |
| Stories / Reels | Architecture placeholder only this cycle | later |
| AI auto-moderation as sole decider | Must not rely solely on AI | interface only now |

---

## Summary: decisions resolved at the Phase 0 gate (2026-06-23)

| ADR | Decision | Source |
|-----|----------|--------|
| ADR-001 | **True microservices** — each context independently deployable | user |
| ADR-002 | Monorepo hosting those microservices (dev speed) | architect (delegated) |
| ADR-003 | RabbitMQ first + Kafka for the firehose | architect (delegated) |
| ADR-004 | OpenSearch | architect (delegated) |
| ADR-006 | Django Channels | architect (delegated) |

All Phase 0 ADRs are now **Accepted**. **Phase 1 — Foundation** can begin on the
user's "go." Assumptions in [Risk Register §3](08-risk-register.md) (small team,
cloud prod, no hard deadline, ar+en locales) remain in effect unless changed.
