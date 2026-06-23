# Tara

> *Tara* — a Sanskrit word meaning "star" or "crossing."

A production-grade, horizontally-scalable **social networking platform** built
as **true microservices** (web today; mobile-ready API contracts). Backend in
Django/DRF, real-time in Django Channels, frontend in Vue 3.

## Status

| Phase | State |
|-------|-------|
| Phase 0 — Discovery & Architecture | ✅ Complete — see [`docs/`](docs/README.md) |
| **Phase 1 — Foundation** | 🚧 In progress (this delivery) |
| Phases 2–9 | ⏳ Planned ([roadmap](docs/README.md)) |

Phase 1 delivers the foundation everything else builds on: monorepo layout,
Dockerized dev environment, shared libraries, the **Identity service** (auth,
JWT + rotating refresh, sessions, email verification, password reset), the
edge **gateway + BFF**, an observability baseline, and CI.

## Architecture in one paragraph

17 bounded contexts, each an independently deployable microservice with its own
database, REST API (`/api/v1/`), and event channels. Services talk to each other
**asynchronously** via an outbox → RabbitMQ event bus (Kafka for the analytics
firehose later), and **synchronously** only for read-time composition behind
timeouts + retries + circuit breakers. They live in **one monorepo** for
development speed with no runtime coupling. Full detail in
[`docs/architecture/phase-0/`](docs/README.md).

## Prerequisites

- Docker + Docker Compose v2
- (Optional, for running tests/lint outside containers) Python 3.12 + `ruff`
- On Windows: use the **WSL2** Docker backend; the repo enforces LF line endings
  via `.gitattributes`.

## Quickstart

```bash
# 1. Create your local env file
make env                # copies .env.example -> .env

# 2. Build & start the foundation stack
make up                 # Postgres, Redis, RabbitMQ, MinIO, Mailpit, Identity, BFF, Traefik

# 3. Apply database migrations
make migrate

# 4. Verify
curl http://localhost:8080/api/v1/health/        # via Traefik -> identity
curl http://localhost:8000/.well-known/jwks.json # identity JWKS (public keys)
```

### Handy URLs (dev)

| Service | URL |
|---------|-----|
| Edge (Traefik) | http://localhost:8080 |
| Traefik dashboard | http://localhost:8081 |
| Identity API + Swagger | http://localhost:8000/api/v1/docs/ |
| BFF | http://localhost:8090/healthz |
| RabbitMQ management | http://localhost:15672 |
| MinIO console | http://localhost:9001 |
| Mailpit (captured email) | http://localhost:8025 |
| Prometheus (`make up-observability`) | http://localhost:9090 |
| Grafana | http://localhost:3001 |

## Common commands

```bash
make help            # list all targets
make logs SERVICE=identity
make test            # run identity tests (SERVICE=bff for the BFF)
make lint            # ruff lint + format check
make down            # stop (keeps data)
make clean           # stop + delete volumes (destroys local data)
```

## Repository layout

```
services/   one microservice per bounded context (Phase 1: identity, bff)
libs/       thin shared kernel (tara_common, tara_events, tara_resilience, tara_observability)
infra/      compose, postgres init, traefik, observability configs
frontend/   Vue 3 web app (Phase 8)
docs/       architecture & phase documentation
.github/    CI/CD pipelines
```

## Documentation

Start at [`docs/README.md`](docs/README.md). Each phase ends with a report under
`docs/architecture/phase-<n>/`.

## Security & honesty notes

- Secrets come **only** from environment / secret manager — never committed.
- This platform does **not** implement end-to-end encryption, mobile apps, or
  real payments. Those are explicitly deferred (see
  [decision log](docs/architecture/phase-0/09-decision-log.md)) and are never
  claimed as built.
