# Tara

> *Tara* — a Sanskrit word meaning "star" or "crossing."

A production-grade, horizontally-scalable **social networking platform** built
as **true microservices** (web today; mobile-ready API contracts). Backend in
Django/DRF, real-time in Django Channels, frontend in Vue 3.

## Status

All backend services and the Vue web client exist and run together locally.
Production hardening is in progress; the current state and plan live in
[`docs/architecture/project-review-and-plan.md`](docs/architecture/project-review-and-plan.md).

## Architecture in one paragraph

14 Django services plus a small FastAPI BFF, each independently deployable with
its own database, REST API (`/api/v1/`), and event channels. Services talk to
each other **asynchronously** via an outbox → RabbitMQ event bus, and
**synchronously** only for read-time composition behind timeouts + retries +
circuit breakers. They live in **one monorepo** for development speed with no
runtime coupling. Full detail in [`docs/architecture/phase-0/`](docs/README.md).

## Prerequisites

- Docker + Docker Compose v2
- (Optional, for running tests/lint outside containers) Python 3.12 + `ruff`
- On Windows: use the **WSL2** Docker backend; the repo enforces LF line endings
  via `.gitattributes`.

## Quickstart

```bash
make env     # copies .env.example -> .env
make up      # builds and starts the stack; each web service migrates at boot
make smoke   # end-to-end API check through the gateway

cd frontend/web && npm ci && npx vite   # web app on http://localhost:5173
```

### Handy URLs (dev)

Everything is published on `127.0.0.1` only.

| Service | URL |
|---------|-----|
| Web app (Vite) | http://localhost:5173 |
| Edge (Traefik) | http://localhost:8080 |
| Traefik dashboard | http://localhost:8081 |
| Identity API + Swagger | http://localhost:8100/api/v1/docs/ |
| BFF | http://localhost:8090/healthz |
| RabbitMQ management | http://localhost:15672 |
| MinIO console | http://localhost:9001 |
| Mailpit (captured email) | http://localhost:8026 |
| Prometheus (`make up-observability`) | http://localhost:9090 |
| Grafana | http://localhost:3001 |

Host ports for identity and Mailpit can be changed with `IDENTITY_HOST_PORT`,
`MAILPIT_UI_HOST_PORT` and `MAILPIT_SMTP_HOST_PORT` in `.env`.

## Common commands

```bash
make help                   # list all targets
make logs SERVICE=identity
make test                   # all services (SERVICE=post for one)
make lint                   # ruff lint + format check
make makemigrations SERVICE=post   # generate, review, commit
make lock                   # refresh pinned dependency versions
make down                   # stop (keeps data)
make clean                  # stop + delete volumes (destroys local data)
```

Migrations are committed. Services only apply them at boot and never generate them.

## Repository layout

```
services/   one microservice per bounded context
libs/       thin shared kernel (tara_common, tara_events, tara_resilience, tara_observability)
infra/      compose, postgres init, traefik, observability configs
frontend/   Vue 3 web app
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
