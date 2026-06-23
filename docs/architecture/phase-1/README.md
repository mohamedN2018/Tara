# Phase 1 — Foundation (Report)

> Status: **implemented**. Delivers the foundation every later phase builds on:
> monorepo layout, Dockerized dev environment, the shared kernel, the **Identity
> service** (full auth), the edge **gateway + BFF**, an observability baseline,
> and CI. Decisions locked in [Phase 0 ADRs](../phase-0/09-decision-log.md):
> true microservices, monorepo, RabbitMQ(+Kafka-later), OpenSearch, Channels.

---

## 1. Architecture changes

- Established the **monorepo** skeleton (`services/`, `libs/`, `infra/`,
  `frontend/`, `docs/`) per [ADR-002](../phase-0/09-decision-log.md).
- Stood up the **shared kernel** (`libs/tara_*`) — the only code shared across
  services, kept thin: error/response envelope, cursor pagination, JWKS auth,
  request-id correlation, health probes, the event envelope + outbox + swappable
  publisher, resilience primitives, and observability helpers.
- Implemented the first microservice end-to-end: **Identity** (own DB, own API,
  own outbox, own pipeline) + the **BFF** edge aggregator + **Traefik** edge.
- Wired the **outbox pattern** (Identity writes domain events transactionally;
  a Celery-beat relay drains them to RabbitMQ).
- Established **decentralized auth**: Identity signs RS256 access tokens and
  publishes a **JWKS**; every other service (and the BFF) verifies locally —
  no per-request call to Identity.

## 2. Files created / changed

**Root:** [`README.md`](../../../README.md), [`Makefile`](../../../Makefile),
[`.env.example`](../../../.env.example), [`.gitattributes`](../../../.gitattributes),
[`.dockerignore`](../../../.dockerignore), [`pyproject.toml`](../../../pyproject.toml).

**Shared kernel (`libs/`):**
- `tara_common/` — `responses.py`, `exceptions.py` (uniform error envelope +
  DRF handler), `pagination.py` (cursor), `auth.py` (JWKS `JWTAuthentication`),
  `middleware.py` (request id), `health.py` (liveness/readiness).
- `tara_events/` — `envelope.py` (envelope + UUIDv7), `models.py` (abstract
  outbox/processed), `publisher.py` (Null/Kombu, swappable), `outbox.py`
  (`record_event`, `publish_pending`), `tasks.py` (relay), `consumer.py`
  (idempotency guard), `schemas/`.
- `tara_resilience/` — `idempotency.py`, `retry.py`, `circuit_breaker.py`.
- `tara_observability/` — `logging.py` (JSON), `tracing.py` (OTel, optional),
  `metrics.py` (Prometheus).

**Identity service (`services/identity/`):** `config/` (settings, urls, celery,
asgi, wsgi), `identity/` (`models.py`, `managers.py`, `keys.py`, `tokens.py`,
`events.py`, `emails.py`, `services.py`, `serializers.py`, `views.py`,
`urls.py`, `admin.py`, `apps.py`, management commands `ensure_jwt_keys` &
`seed_dev_data`, `tests/`), `Dockerfile`, `entrypoint.sh`, `requirements*.txt`,
`pytest.ini`, `conftest.py`, `scripts/wait_for_db.py`.

**BFF (`services/bff/`):** `app/main.py`, `app/auth.py`, `app/config.py`,
`app/tests/`, `Dockerfile`, `requirements*.txt`, `pytest.ini`.

**Infra (`infra/`):** `compose/docker-compose.yml`, `postgres/init/01-create-databases.sh`,
`observability/{prometheus.yml,otel-collector-config.yaml,grafana/...}`.

**CI:** [`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml).

## 3. Services added / changed

| Service | Role | Port (dev) | Notes |
|---------|------|-----------|-------|
| **identity** | auth/accounts microservice | 8000 | Django/DRF + gunicorn |
| **identity-worker** | Celery worker | — | events, async work |
| **identity-beat** | Celery beat | — | drains outbox every 2s |
| **bff** | edge aggregator | 8090 | FastAPI; JWKS verify + degrade |
| **traefik** | edge proxy | 8080 / 8081 | routing, TLS-ready |
| postgres / redis / rabbitmq / minio / mailpit | backing services | std | dev infra |
| prometheus / grafana / otel-collector | observability | 9090 / 3001 | `observability` profile |

## 4. Database changes

New logical DB **`identity_db`** (created by the Postgres init script; own role
with least privilege). Tables (owned solely by Identity): `account`,
`device`, `user_session`, `refresh_token`, `email_verification`,
`password_reset`, `security_event`, `two_factor_secret`, plus the platform
tables `outbox_event`, `processed_event`, `idempotency_record`. UUIDv7 public
IDs; Argon2id password hashing; DB-level uniqueness on email, token hashes, and
the idempotency key.

> **Migrations:** for Phase-1 dev speed the container generates migrations from
> the models on first boot (`RUN_MAKEMIGRATIONS=true`) and applies them. **Before
> staging/prod**, run `make makemigrations`, commit the files, and set
> `RUN_MAKEMIGRATIONS=false` (expand/contract discipline, [doc 07](../phase-0/07-migration-and-rollout.md)).
> Tests build the schema directly from models (`pytest --no-migrations`).

## 5. API endpoints (live)

Identity, under `/api/v1/`:
`POST auth/register`, `POST auth/login`, `POST auth/refresh`, `POST auth/logout`,
`POST auth/verify-email`, `POST auth/password/forgot`, `POST auth/password/reset`,
`GET auth/sessions`, `DELETE auth/sessions/{id}`, `GET/PATCH me`.
Plus `GET /.well-known/jwks.json`, `GET /healthz`, `GET /readyz`, `GET /metrics`,
`GET /api/v1/docs` (Swagger), `GET /api/v1/schema` (OpenAPI).

BFF: `GET /healthz`, `GET /readyz`, `GET /bff/v1/whoami` (JWKS-verified,
degrades if Identity is down).

All responses use the uniform envelope; errors use stable machine `code`s
([doc 03](../phase-0/03-api-contracts.md)).

## 6. Event contracts (emitted)

Via the outbox → RabbitMQ exchange `tara.events` (routing key = event_type):
`account.registered` (v1), `account.verified` (v1), `session.created` (v1).
Envelope per [doc 04](../phase-0/04-event-contracts.md). No consumers yet
(Profile/Notification arrive in Phase 2); events accumulate durably and publish
reliably regardless.

## 7. Tests

- **Identity** (`pytest`, Postgres-backed): register → pending account + outbox
  event; weak-password & duplicate-email error envelopes; login blocked until
  active; login success + token + cookie; wrong password 401; `/me` auth
  gating; **refresh rotation + reuse detection** (family + session revoked);
  email verification activates account; JWKS shape; session list/revoke;
  UUIDv7 bits; envelope round-trip; access-token JWKS verification; outbox relay
  publishes & marks rows; password reset revokes all sessions.
- **BFF** (`pytest`): health; whoami requires bearer; garbage token rejected;
  uniform error envelope.
- **Quality gates:** `ruff check` + `ruff format --check` clean across `libs`
  and `services`; CI runs lint + per-service tests (Postgres+Redis services) +
  Docker image builds, path-filtered.

Run: `make test` (identity) · `make test SERVICE=bff` · `make lint`.

## 8. Commands

```bash
make env            # create .env from .env.example
make up             # build + start the core stack (Postgres, Redis, RabbitMQ,
                    # MinIO, Mailpit, identity (+worker/beat), bff, traefik)
make migrate        # apply identity migrations (also auto-run on first boot)
make seed           # synthetic dev accounts (DEBUG only)
make up-observability   # Prometheus + Grafana + OTel collector
make test           # identity tests   |   make test SERVICE=bff
make lint           # ruff lint + format check
make logs SERVICE=identity
make down           # stop (keep data)  |  make clean (delete volumes)
```

Smoke check after `make up && make migrate`:
```bash
curl http://localhost:8000/healthz/
curl http://localhost:8000/.well-known/jwks.json
curl -X POST http://localhost:8000/api/v1/auth/register/ \
  -H 'Content-Type: application/json' \
  -d '{"email":"a@tara.local","password":"DevPassw0rd!"}'
# verification link is captured by Mailpit at http://localhost:8025
```

## 9. Risks

| Risk | Mitigation |
|------|------------|
| Uncommitted migrations (dev makemigrations) | Documented expand/contract + commit before staging; tests use `--no-migrations`. |
| Refresh token in response body (mobile) + cookie (web) | Web should rely on the httpOnly cookie; body token documented for mobile keystore. Revisit per-client split in Phase 2. |
| Dev JWT keys are auto-generated to a volume | Prod injects keys via secret manager (`IDENTITY_JWT_*`); rotation supported by `kid`. |
| Single Postgres instance hosts the logical DB in dev | Mirrors prod's DB-per-service logically; staging uses separate managed instances. |
| `ip_region` relies on an edge-provided header | Documented; the edge must set `X-Geo-Region` and never forward raw client IP into logs. |
| In-process circuit breaker (not shared) | Fine per-pod now; back with Redis when traffic warrants. |

## 10. Rollback notes

- Phase 1 is additive (new files only; the original `README`/`.gitignore`
  remain). Full rollback: `git revert` the Phase-1 commit(s) or drop the new
  directories.
- Runtime: `make clean` removes containers **and volumes** (destroys local data
  incl. the dev JWT keys and DB). `make down` keeps data.
- No production data or external systems are touched by this phase.

## 11. Completion checklist

- [x] Monorepo structure + `.gitattributes` (LF discipline for Windows).
- [x] Docker Compose dev env with profiles (Postgres multi-DB, Redis, RabbitMQ,
      MinIO, Mailpit, Traefik, observability).
- [x] Shared kernel: errors, pagination, JWKS auth, health, events/outbox,
      resilience, observability.
- [x] Identity service: register/login/logout, JWT access + rotating refresh
      with reuse detection, email verification, password reset, sessions/devices,
      JWKS, security log, 2FA schema.
- [x] Outbox → RabbitMQ relay (Celery beat) with idempotent consumers' guard.
- [x] BFF edge aggregator with JWKS verification + graceful degradation.
- [x] Observability baseline (structured JSON logs, `/metrics`, health probes,
      optional OTel).
- [x] CI: lint + format + per-service tests + Docker builds (path-filtered).
- [x] OpenAPI/Swagger published by Identity.
- [x] Tests green; `ruff` clean; `docker compose config` valid; Identity image
      builds and its suite passes (see verification log).
- [ ] **Your approval to proceed to Phase 2 — Profile & Social Graph.** ← gate

---

### What Phase 2 will add (preview)

Profile service (handles, field-level privacy, Pages) + Social Graph service
(friends/follows/blocks), each consuming `account.registered` to provision a
profile, and publishing their own events. First **cross-service** event flow and
the first read-model/degradation path through the BFF.
